#!/usr/bin/env python3
"""Final-study preflight gate (Amendment A1 preflight_prompt_render_gate +
E2_resolution_hardware_and_placement.residency_gate_checks, extended by Amendment A2 E9,
Clarification C1_2, and Amendment A3 F1/F2/F3 + R1-R4). Must pass before any of the
578-task x 4-scorer x 6-condition real scoring run.

Five things are checked, together, for every one of the 4 scorers:

  1. TEMPLATE-AUDIT: 4 scorers x 6 conditions = 24 renders of the canonical task
     (lexicographically smallest source_task_id among the 500-task primary population --
     wildbench/00c7916a072b4947, verified against the frozen manifest and its pinned
     question_sha256 before rendering). For each render: full text, text sha256, token-ID
     sequence, token-ID sha256, token count, first/last token IDs, chat_template sha256,
     attn_implementation, transformers version, decode settings -- then run the three
     testable fail conditions from silent_influence.final_preflight_checks (residual
     content, date leakage, persona leakage; the reproducibility test is a hash comparison
     against a previously frozen baseline, via --verify-against).

  2. RESIDENCY GATE: for the one loaded copy of each scorer, the 6-point BF16/no-offload/
     no-quantization/full-GPU check (silent_influence.exact_generation.check_gpu_residency
     + check_vram_allocated).

  3. USE_CACHE ASSERTION (Olmo-3.1-32B only, Amendment A2 E9 / Clarification C1_2): after
     load, both model.config.use_cache and model.generation_config.use_cache must read
     back as True -- config.json ships use_cache=False, and this confirms the explicit
     override in exact_generation.load_exact_model actually took effect rather than being
     silently overwritten by a later step.

  4. PRODUCTION-PATH REPRODUCIBILITY (Olmo-3.1-32B only, Amendment A3 F2 -- SUPERSEDES
     Clarification C1_2's cache-on/cache-off equivalence check): 18 calls (6 frozen
     conditions x 3 repetitions), ALL with use_cache=True, on the canonical task with the
     placeholder answer. Within each condition the rendered input text, the tokenized input
     IDs, the generation kwargs dict and the generated token-ID sequence must all be
     byte-identical across every repetition. The superseded gate compared two different
     computational paths; this one tests the only path the study executes. A missing
     repetition is a hard failure, never a smaller comparison.

  5. FROZEN RENDER-HASH COMPARISON (Amendment A3 R4): every render for which a frozen
     hash exists -- Llama's six from A3 F1 and OLMo's six from A2 E8 -- must reproduce it
     exactly, so a template, tokenizer or revision change is caught even when the
     residual/date/persona scans pass. Fails closed if a frozen hash was never compared.

Note also that fail-condition 1 now honours two named per-scorer permitted structures
(A3 R1/R2): Llama's fixed 134-byte template preamble (exactly once, position 0) and Gemma's
terminal <start_of_turn>model cue (exactly once, terminal). Both are enumerated byte-exactly
in silent_influence.final_preflight_checks and neither adds a word to any global token list.

Any render/message-shape failure, residency failure, use_cache assertion failure,
reproducibility mismatch or frozen-hash mismatch aborts before any inference on the real
578-task manifest and returns a non-zero exit code, per Amendment A1's "on_failure: abort
before any inference and return for review" (reaffirmed by A2/C1 and A3).

    python scripts/verify_final_preflight_gate.py --stub   # no-GPU plumbing check
    python scripts/verify_final_preflight_gate.py           # real GPU check, all 4 scorers
    python scripts/verify_final_preflight_gate.py --verify-against results/final_behavioral_study/preflight_gate_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import exact_generation as eg
from silent_influence import final_preflight_checks as fpc
from silent_influence import final_study_messages as fsm
from silent_influence import scaled_conditions as sc

MANIFEST_FILE = REPO / "data/prompts/final_tasks_v2_english_seed20260817.json"
MANIFEST_SHA256 = "a001d48b7769311da33cba1a8ef51bb4e9d1a27b2cc0d007bce85adab606037f"
# Public-release adaptation: two credentials in a different, noncanonical task were
# redacted. Accept only this exact audited public copy, never arbitrary changed inputs.
# Historical freeze records retain MANIFEST_SHA256; see PUBLIC_REDACTIONS.json.
PUBLIC_MANIFEST_SHA256 = "fd99e9fe26a5b8274a63c7796a0531c998f636514dc8609114e0e4a39f6e6818"
CANONICAL_DATASET = "wildbench"
CANONICAL_SOURCE_TASK_ID = "00c7916a072b4947"
CANONICAL_QUESTION_SHA256 = "462b09c2e8ef464bbd896acb386ba928e5dc97dddbb39388014469c1dd72c0f4"

# Amendment A4: per-scorer ceilings. 512 for llama/qwen/gemma, 2048 for olmo32b alone.
# Read from the spec at every call site so the gate exercises the production value.
DEFAULT_MAX_NEW_TOKENS = 512
OLMO32B_MAX_NEW_TOKENS = 2048

SCORERS = [
    eg.ExactModelSpec(key="llama", hf_id="meta-llama/Llama-3.1-8B-Instruct",
                      revision="0e9e39f249a16976918f6564b8830bc894c89659"),
    eg.ExactModelSpec(key="qwen", hf_id="Qwen/Qwen3-8B",
                      revision="b968826d9c46dd6066d109eabc6255188de91218",
                      disable_thinking=True),
    eg.ExactModelSpec(key="gemma", hf_id="google/gemma-2-9b-it",
                      revision="11c9b309abf73637e4b6f9a3fa1e92e615547819"),
    eg.ExactModelSpec(key="olmo32b", hf_id="allenai/Olmo-3.1-32B-Instruct",
                      revision="ac0587e4a7744a551c059d8cd17ba220bc940dae",
                      force_use_cache=True, requires_memory_preflight=True,
                      # Amendment A4: this scorer only. All others stay at 512.
                      max_new_tokens=OLMO32B_MAX_NEW_TOKENS),
]
DECODE_SETTINGS = {"skip_special_tokens": True, "clean_up_tokenization_spaces": False,
                   "pad_token_id_source": "tokenizer.eos_token_id"}

# ---- Amendment A3 R4: frozen render hashes folded into the reproducibility comparison ----
# A template, tokenizer or revision change shows up here as a hash mismatch even when the
# residual/date/persona scans still pass. Llama's six come from A3 F1
# (frozen_render_hashes); OLMo's six come from A2 E8
# (frozen_render_hashes_for_preflight_reproducibility_test). Both sets are for the canonical
# preflight task with the standard placeholder answer.
A3_FROZEN_RENDER_SHA256 = {
    "llama": {
        "no_history":      "0cf47086465e7cd88f10da3ca2c5111195864262149fffc36aba4698e448f8d9",
        "self_low_2":      "9a2ba5d7dbf695bbb918f9eb5c44720977f4313081dc057de39d23febc086276",
        "other_low_2":     "56a3c8d4583196d606e303e333fd83973e4c35fdc7b04e8b8f70ecb254cc02eb",
        "unrelated_low_2": "dae0f0f59bd9ecb957deca7e9b35070f833f22ec5137173cb05cfebb97a04be7",
        "verbal_negative": "108a9d7745883e671310ebc7e25509500ab92a4ffbfd3681673d078d174c1c0f",
        "self_high_10":    "a4b97b0e31059f35f13b1b44956df57cd28fab6332e00d8f526400b933132065",
    },
    "olmo32b": {
        "no_history":      "fbdd9919fb1c3a0d5321f6a691e6eb42627e813490631c31d71663719e7730a9",
        "self_low_2":      "02752c84fc561381717f72c8ee3be4b9f7e6ec5f9ef0c0ae3537c05d9feaa650",
        "other_low_2":     "89a6eccddf80fb6b68e64e09231efc116138e157aee5e07070af5dad994382f7",
        "unrelated_low_2": "2bd0148649e9d95b592a2aef17ff500d16938ac972362385121a7c10c5d2ac5a",
        "verbal_negative": "10e19e1c734f65a0dedeabb37baca910007bc48277beaeb454104d0ebdd44fdd",
        "self_high_10":    "056a182d3b121f4d6201734e80d3c49d9919d01a1d2dbf241478f1a5a7876681",
    },
}

# Amendment A3 F2: the production-path reproducibility gate replaces C1_2's superseded
# cache-on/cache-off equivalence check. Three repetitions of each of the six frozen
# conditions, all with use_cache=True.
PRODUCTION_REPRODUCIBILITY_REPETITIONS = 3

# Scorers for which Amendment A2 E9 / Clarification C1_2 MANDATE the use_cache assertion
# and (as amended by A3 F2) the production-path reproducibility check. Deliberately a
# frozen constant
# here rather than being derived only from ExactModelSpec.force_use_cache: if that flag
# were ever cleared on the spec, a spec-derived requirement set would become empty and the
# gate would pass vacuously, having skipped the very check C1_2 requires. The spec flag
# controls HOW the check is wired; this constant controls WHETHER it may be skipped.
CACHE_CHECK_REQUIRED_SCORERS = ("olmo32b",)
PLACEHOLDER_ANSWER = ("This is a placeholder candidate answer used only to verify the "
                      "scoring input path. It is not real experimental content.")


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def load_canonical_task(manifest_file: Path, skip_hash_check: bool) -> dict:
    if not skip_hash_check:
        got = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
        if got not in {MANIFEST_SHA256, PUBLIC_MANIFEST_SHA256}:
            raise SystemExit(f"FROZEN ARTIFACT MISMATCH: {manifest_file} sha256={got} "
                             f"expected historical={MANIFEST_SHA256} or "
                             f"documented public copy={PUBLIC_MANIFEST_SHA256}")
    with open(manifest_file, encoding="utf-8") as f:
        manifest = json.load(f)
    for t in manifest["datasets"][CANONICAL_DATASET]["selected"]:
        if t["source_task_id"] == CANONICAL_SOURCE_TASK_ID:
            if t["question_sha256"] != CANONICAL_QUESTION_SHA256:
                raise SystemExit("canonical task question_sha256 mismatch")
            if sha256_text(t["question"]) != CANONICAL_QUESTION_SHA256:
                raise SystemExit("canonical task question bytes mismatch")
            return t
    raise SystemExit(f"canonical task {CANONICAL_DATASET}/{CANONICAL_SOURCE_TASK_ID} "
                     "not found in manifest")


def _stub_render(scorer_key: str, messages: list) -> str:
    """A no-GPU stand-in that reproduces each scorer's real chat-template SHAPE.

    Deliberately structural rather than generic: the A3 R1/R2 rules require Llama's fixed
    preamble and Gemma's terminal cue to be PRESENT (absence is a failure), so a generic
    <role>...</role> stub would fail the very rules it is supposed to exercise. Emulating
    the real shapes lets the --stub plumbing path test those rules honestly instead of
    forcing the rules to special-case stub mode.

    Never a source of experimental data, and never compared against the frozen render
    hashes (check_frozen_render_hashes skips stub runs, since these are synthetic)."""
    user = next(m["content"] for m in messages if m["role"] == "user")
    has_system = any(m["role"] == "system" for m in messages)

    if scorer_key == "llama":
        # Real template emits the fixed preamble unconditionally (A3 F1).
        return (fpc.LLAMA_TEMPLATE_PREAMBLE
                + "<|start_header_id|>user<|end_header_id|>\n\n" + user
                + "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n")
    if scorer_key == "gemma":
        return (f"<bos><start_of_turn>user\n{user}<end_of_turn>\n"
                f"{fpc.GEMMA_TERMINAL_CUE}\n")
    if scorer_key == "qwen":
        # enable_thinking=False pre-closes an empty reasoning block.
        return (f"<|im_start|>user\n{user}<|im_end|>\n"
                f"<|im_start|>assistant\n<think>\n\n</think>\n\n")
    if scorer_key == "olmo32b":
        head = "<|im_start|>system\n<|im_end|>\n" if has_system else ""
        return (f"{head}<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")
    return "".join(f"<{m['role']}>{m['content']}</{m['role']}>" for m in messages)


def render_and_gate(loaded, scorer_key: str, condition, question: str, stub: bool) -> dict:
    prompt = sc.render_prompt(question, PLACEHOLDER_ANSWER, condition)
    messages = fsm.build_scorer_messages(scorer_key, prompt)
    allow_empty_system_tags = scorer_key in fsm.EMPTY_SYSTEM_SCORER_KEYS

    if stub:
        rendered_text = _stub_render(scorer_key, messages)
        gen_fn = eg.generate_exact_stub
    else:
        rendered_text = loaded.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        gen_fn = eg.generate_exact

    result = gen_fn(loaded, messages, max_new_tokens=1, seed=42)
    # Take "the model's control/special tokens" (fail-condition 1) from the loaded
    # tokenizer itself rather than only from the hardcoded list, so a model whose template
    # emits a structural token this module has never seen is not failed for a template
    # artefact. Only the token strings are stripped; any content between them still tests.
    tokenizer_special = [t for t in (getattr(loaded.tokenizer, "all_special_tokens", None) or [])
                        if isinstance(t, str) and t]
    check = fpc.check_render(rendered_text, prompt, scorer_key=scorer_key,
                             condition_name=condition.name,
                             allow_empty_system_tags=allow_empty_system_tags,
                             extra_control_tokens=tokenizer_special)

    prompt_verbatim = prompt in rendered_text
    return {
        "scorer_key": scorer_key, "condition": condition.name,
        "rendered_text": rendered_text, "rendered_text_sha256": sha256_text(rendered_text),
        "input_token_ids": result.get("input_token_ids"),
        "input_token_ids_sha256": sha256_text(str(result.get("input_token_ids"))),
        "input_token_count": result["prompt_tokens"],
        "first_input_token_id": result["first_input_token_id"],
        "last_input_token_id": result["last_input_token_id"],
        "chat_template_sha256": loaded.chat_template_sha256,
        "attn_implementation": loaded.attn_implementation,
        "transformers_version": loaded.transformers_version,
        "decode_settings": DECODE_SETTINGS,
        "tokenizer_special_tokens_stripped": tokenizer_special,
        "fail_conditions": {
            "1_residual_content_primary_gate": {"passed": not check.residual_words,
                                                "residual_words": check.residual_words},
            "2_date_test": {"passed": not check.date_hits, "hits": check.date_hits},
            "3_persona_test": {"passed": not check.persona_hits, "hits": check.persona_hits},
            "4_instruction_test": {"passed": not check.residual_words,
                                   "note": "subsumed by test 1"},
            # A3 R1/R2. Reported explicitly: a structural violation fails gate_passed, and an
            # auditor reading this JSON must be able to see which rule fired and why.
            "6_permitted_structure": {"passed": not check.structure_problems,
                                      "problems": check.structure_problems,
                                      "rule": ("llama: one 134-byte preamble at position 0"
                                               if scorer_key in fpc.PERMITTED_PREAMBLE_SCORER_KEYS
                                               else "gemma: one terminal <start_of_turn>model cue"
                                               if scorer_key in fpc.PERMITTED_TERMINAL_CUE_SCORER_KEYS
                                               else "no permitted structure for this scorer")},
            # A3 F1/F3 acceptance criterion, asserted directly rather than inferred from the
            # residual scan happening to come back clean.
            "7_frozen_prompt_verbatim": {"passed": prompt_verbatim},
        },
        # Reported AND enforced: a verbatim failure must fail the render, not merely appear
        # in the JSON.
        "gate_passed": check.passed and prompt_verbatim,
    }


def run_production_reproducibility_check(loaded, question: str, stub: bool,
                                         repetitions: int = PRODUCTION_REPRODUCIBILITY_REPETITIONS
                                         ) -> dict:
    """Amendment A3 F2 (supersedes Clarification C1_2's cache-on/cache-off equivalence).

    Three use_cache=True repetitions of each of the six frozen conditions -- 18 calls on the
    canonical task with the PLACEHOLDER answer, so no study observation is consumed. Within
    each condition all four invariants must be byte-identical across every repetition:
    rendered input text, tokenized input IDs, the generation kwargs dict, and the generated
    token-ID sequence.

    The superseded gate compared two different computational paths; this one tests the only
    path the study actually executes. A2/C1's reasoning that a cross-path mismatch implies
    non-reproducibility was empirically falsified on the A100 (cache-on reproduced 6/6 while
    the cross-path check failed 3/6), so A3 does not claim path equivalence -- it requires
    production-path determinism."""
    gen_fn = eg.generate_exact_stub if stub else eg.generate_exact
    per_condition = {}
    n_calls = 0
    mismatched = []
    missing = []
    token_id_problems = []
    observed_use_cache = []

    for cond in sc.CONDITIONS:
        reps = []
        for _ in range(repetitions):
            # Every input is rebuilt from the condition on each repetition -- prompt,
            # messages, kwargs, render. Constructing them once and reusing the objects would
            # make three of the four invariants identical by construction and the gate
            # vacuous: it would prove only that a string equals itself.
            prompt = sc.render_prompt(question, PLACEHOLDER_ANSWER, cond)
            messages = fsm.build_scorer_messages(loaded.spec.key, prompt)
            kwargs = eg.build_generate_kwargs(
                loaded.spec, max_new_tokens=loaded.spec.max_new_tokens,
                pad_token_id=getattr(loaded.tokenizer, "eos_token_id", None), use_cache=True)
            r = gen_fn(loaded, messages, max_new_tokens=loaded.spec.max_new_tokens, seed=42,
                       use_cache=True)
            n_calls += 1
            rendered = (_stub_render(loaded.spec.key, messages) if stub
                        else loaded.tokenizer.apply_chat_template(
                            messages, tokenize=False, add_generation_prompt=True))
            # An absent token-ID list would otherwise hash str(None) identically in all three
            # repetitions and pass this invariant without ever comparing token IDs.
            ids = r.get("input_token_ids")
            if not ids:
                token_id_problems.append(
                    f"{cond.name}: call returned no input_token_ids; the input-token-ID "
                    f"invariant cannot be evaluated and must not be reported as identical")
            reps.append({
                "rendered_text_sha256": sha256_text(rendered),
                "input_token_ids_sha256": sha256_text(str(ids)),
                "generation_kwargs": kwargs,
                "generated_token_ids_sha256": r["generated_token_ids_sha256"],
            })
            # Observed, not assumed: the value actually handed to this call. The previous
            # version reported all_calls_use_cache as a hardcoded True, which asserted
            # nothing about the 18 calls it had just made.
            observed_use_cache.append(kwargs.get("use_cache"))

        # A missing repetition is a hard failure, never a silently smaller comparison.
        if len(reps) != repetitions:
            missing.append(cond.name)

        first = reps[0]
        differing = sorted({
            field
            for rep in reps[1:]
            for field in ("rendered_text_sha256", "input_token_ids_sha256",
                          "generation_kwargs", "generated_token_ids_sha256")
            if rep[field] != first[field]
        })
        if differing:
            mismatched.append({"condition": cond.name, "differing_invariants": differing})
        per_condition[cond.name] = {
            "repetitions": len(reps),
            "identical_across_repetitions": not differing,
            "differing_invariants": differing,
            "rendered_text_sha256": first["rendered_text_sha256"],
            "input_token_ids_sha256": first["input_token_ids_sha256"],
            "generated_token_ids_sha256": first["generated_token_ids_sha256"],
        }

    enough = all(v["repetitions"] == repetitions for v in per_condition.values())
    complete = len(per_condition) == len(sc.CONDITIONS)
    # A3 fixes the repetition count at 3; a caller passing fewer would shrink the gate while
    # still reporting "passed", so a non-frozen count is itself a failure.
    frozen_reps = repetitions == PRODUCTION_REPRODUCIBILITY_REPETITIONS
    all_use_cache = bool(observed_use_cache) and all(v is True for v in observed_use_cache)
    return {
        "gate": "A3_production_path_reproducibility",
        "supersedes": "C1_2 cache-on/cache-off exact equivalence",
        "repetitions_per_condition": repetitions,
        "n_conditions": len(per_condition),
        "n_calls": n_calls,
        "n_calls_expected": repetitions * len(sc.CONDITIONS),
        "all_calls_use_cache": all_use_cache,
        "n_calls_observed_use_cache_true": sum(1 for v in observed_use_cache
                                               if v is True),
        "repetitions_match_frozen_requirement": frozen_reps,
        "input_token_id_problems": token_id_problems,
        "invariants_compared": ["rendered_text_sha256", "input_token_ids_sha256",
                                "generation_kwargs", "generated_token_ids_sha256"],
        "n_mismatched_conditions": len(mismatched),
        "mismatches": mismatched,
        "conditions_with_missing_repetitions": missing,
        "per_condition": per_condition,
        # Fails closed on a mismatch, a missing repetition, a short call count, or a
        # condition that never ran at all.
        "passed": (not mismatched and not missing and enough and complete
                   and not token_id_problems and all_use_cache and frozen_reps
                   and n_calls == repetitions * len(sc.CONDITIONS)),
    }


def check_frozen_render_hashes(renders: list, stub: bool = False) -> dict:
    """Amendment A3 R4: compare this run's rendered-text hashes against the frozen values
    for every scorer that has them (Llama from A3 F1, OLMo from A2 E8). A template,
    tokenizer or revision change is detected here as a hash mismatch.

    Skipped (not failed) under --stub: the stub render is a synthetic stand-in for a real
    chat template, so it cannot reproduce hashes taken from real tokenizer output. The
    comparison is only meaningful, and is mandatory, in a real run."""
    if stub:
        return {"skipped": True, "reason": "--stub renders are synthetic, not real "
                                           "chat-template output", "passed": True,
                "n_frozen_hashes_available": sum(len(v) for v in
                                                 A3_FROZEN_RENDER_SHA256.values()),
                "n_checked": 0, "n_mismatches": 0, "mismatches": []}
    checked, mismatches = 0, []
    for r in renders:
        want = A3_FROZEN_RENDER_SHA256.get(r["scorer_key"], {}).get(r["condition"])
        if want is None:
            continue
        checked += 1
        if r["rendered_text_sha256"] != want:
            mismatches.append({"scorer_key": r["scorer_key"], "condition": r["condition"],
                               "frozen": want, "actual": r["rendered_text_sha256"]})
    expected = sum(len(v) for v in A3_FROZEN_RENDER_SHA256.values())
    return {
        "n_frozen_hashes_available": expected,
        "n_checked": checked,
        "n_mismatches": len(mismatches),
        "mismatches": mismatches,
        # Fails closed if a frozen hash was never compared (e.g. a scorer silently dropped).
        "passed": not mismatches and checked == expected,
    }


def check_use_cache_assertion(loaded, stub: bool) -> dict:
    """Amendment A2 E9 / Clarification C1_2: after load, both model.config.use_cache and
    model.generation_config.use_cache must read back as True. config.json ships
    use_cache=False for Olmo-3.1-32B; this confirms exact_generation.load_exact_model's
    explicit override actually took effect."""
    if stub:
        return {"skipped": True, "reason": "--stub"}
    cfg_val = getattr(loaded.model.config, "use_cache", None)
    gc = getattr(loaded.model, "generation_config", None)
    gc_val = getattr(gc, "use_cache", None) if gc is not None else None
    passed = (cfg_val is True) and (gc_val is True)
    return {"model_config_use_cache": cfg_val, "generation_config_use_cache": gc_val,
           "passed": passed}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest-file", default=str(MANIFEST_FILE))
    ap.add_argument("--skip-hash-check", action="store_true")
    ap.add_argument("--out", default=str(REPO / "results/final_behavioral_study"
                                             "/preflight_gate_report.json"))
    ap.add_argument("--verify-against", default=None,
                    help="path to a previously frozen preflight report; if given, this "
                         "run's rendered_text/token-ID hashes must reproduce it exactly "
                         "(test 5, reproducibility) or the gate fails")
    ap.add_argument("--stub", action="store_true",
                    help="no-GPU plumbing check only; never verifies real model behavior "
                         "or real residency")
    args = ap.parse_args()

    # Fail closed BEFORE any work: a --stub run must not write a report claiming
    # gate_passed into the protected final-results directory.
    fpc.assert_stub_output_is_not_a_protected_dir(Path(args.out).parent, stub=args.stub,
                                                 repo_root=REPO)

    task = load_canonical_task(Path(args.manifest_file), args.skip_hash_check)
    actual_manifest_sha256 = hashlib.sha256(Path(args.manifest_file).read_bytes()).hexdigest()
    manifest_variant = ("public_redacted" if actual_manifest_sha256 == PUBLIC_MANIFEST_SHA256
                        else "historical_frozen" if actual_manifest_sha256 == MANIFEST_SHA256
                        else "unverified")
    question = task["question"]

    renders = []
    residency_reports = {}
    use_cache_reports = {}
    reproducibility_reports = {}
    hf_token = __import__("os").environ.get("HF_TOKEN")
    for spec in SCORERS:
        loaded = eg.load_stub_model(spec) if args.stub else eg.load_exact_model(
            spec, hf_token=hf_token)
        try:
            for cond in sc.CONDITIONS:
                renders.append(render_and_gate(loaded, spec.key, cond, question, args.stub))

            if args.stub:
                residency_reports[spec.key] = {"skipped": True, "reason": "--stub"}
            else:
                problems = eg.check_gpu_residency(loaded.model)
                expected_bytes = sum(p.numel() * p.element_size()
                                    for p in loaded.model.parameters())
                problems += eg.check_vram_allocated(expected_bytes)
                residency_reports[spec.key] = {"problems": problems, "passed": not problems,
                                               "expected_weight_bytes": expected_bytes}

            if spec.force_use_cache:
                use_cache_reports[spec.key] = check_use_cache_assertion(loaded, args.stub)
                reproducibility_reports[spec.key] = run_production_reproducibility_check(
                    loaded, question, args.stub)
        finally:
            eg.unload(loaded)

    assert len(renders) == 24, f"expected 24 renders, got {len(renders)}"

    reproducibility = {"checked": False}
    if args.verify_against:
        baseline_path = Path(args.verify_against)
        if baseline_path.exists():
            with open(baseline_path, encoding="utf-8") as f:
                baseline = json.load(f)
            baseline_hashes = {(r["scorer_key"], r["condition"]):
                               (r["rendered_text_sha256"], r["input_token_ids_sha256"])
                              for r in baseline["renders"]}
            mismatches = []
            for r in renders:
                key = (r["scorer_key"], r["condition"])
                if key not in baseline_hashes:
                    mismatches.append({"key": key, "reason": "missing from baseline"})
                    continue
                b_text, b_tok = baseline_hashes[key]
                if r["rendered_text_sha256"] != b_text or r["input_token_ids_sha256"] != b_tok:
                    mismatches.append({"key": key, "baseline": [b_text, b_tok],
                                       "current": [r["rendered_text_sha256"],
                                                  r["input_token_ids_sha256"]]})
            reproducibility = {"checked": True, "baseline": str(baseline_path),
                              "n_mismatches": len(mismatches), "mismatches": mismatches,
                              "passed": not mismatches}

    template_gate_passed = all(r["gate_passed"] for r in renders)
    residency_gate_passed = args.stub or all(v.get("passed", False)
                                             for v in residency_reports.values())
    # use_cache assertion is skipped (not failed) under --stub, matching the residency
    # gate's pattern; the A3 production-reproducibility check is NOT stub-skipped, because
    # it is meaningful harness plumbing even against the deterministic stub (see
    # run_production_reproducibility_check's docstring and the stub's own
    # use_cache-is-ignored note in exact_generation.generate_exact_stub).
    # Every scorer whose spec demands the C1_2 checks MUST have produced a report. Without
    # this, an empty reports dict would make `all(...)` vacuously true and the gate would
    # announce PASS having performed zero checks -- a fail-OPEN if force_use_cache were
    # ever cleared on the spec.
    # Union of the frozen mandate and whatever the specs currently request, so neither a
    # cleared spec flag nor an unlisted new scorer can shrink the required set to nothing.
    expected_cache_checked = ({s.key for s in SCORERS if s.force_use_cache}
                              | {k for k in CACHE_CHECK_REQUIRED_SCORERS
                                 if k in {s.key for s in SCORERS}})
    cache_checks_ran = (set(use_cache_reports) >= expected_cache_checked
                        and set(reproducibility_reports) >= expected_cache_checked)
    if not cache_checks_ran:
        print(f"\nC1_2 CHECKS DID NOT RUN for: "
             f"{sorted(expected_cache_checked - set(reproducibility_reports))} "
             f"-- refusing to report a pass for checks that were never performed.")
    use_cache_gate_passed = cache_checks_ran and (
        args.stub or all(v.get("passed", False) for v in use_cache_reports.values()))
    reproducibility_gate_passed = cache_checks_ran and all(
        v.get("passed", False) for v in reproducibility_reports.values())
    # A3 R4: frozen render-hash comparison is a gate in its own right (stub-skipped, since
    # synthetic stub renders cannot reproduce real-template hashes).
    frozen_hash_report = check_frozen_render_hashes(renders, stub=args.stub)
    frozen_hash_gate_passed = frozen_hash_report["passed"]
    reproducibility_passed = (not reproducibility["checked"]) or reproducibility["passed"]
    overall_passed = (template_gate_passed and residency_gate_passed
                      and use_cache_gate_passed and reproducibility_gate_passed
                      and frozen_hash_gate_passed
                      and reproducibility_passed)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stub": args.stub,
        "manifest_provenance": {"variant": manifest_variant,
                                "actual_sha256": actual_manifest_sha256,
                                "historical_sha256": MANIFEST_SHA256,
                                "whole_manifest_hash_checked": not args.skip_hash_check},
        "canonical_task": {"dataset": CANONICAL_DATASET,
                          "source_task_id": CANONICAL_SOURCE_TASK_ID,
                          "question_sha256": CANONICAL_QUESTION_SHA256},
        "scorers": [{"key": s.key, "hf_id": s.hf_id, "revision": s.revision,
                    "force_use_cache": s.force_use_cache,
                    "requires_memory_preflight": s.requires_memory_preflight}
                   for s in SCORERS],
        "n_renders": len(renders), "renders": renders,
        "residency_reports": residency_reports,
        "use_cache_reports": use_cache_reports,
        "production_reproducibility_reports": reproducibility_reports,
        "frozen_render_hash_check": frozen_hash_report,
        "reproducibility_test_5": reproducibility,
        "template_gate_passed": template_gate_passed,
        "residency_gate_passed": residency_gate_passed,
        "use_cache_gate_passed": use_cache_gate_passed,
        "production_reproducibility_gate_passed": reproducibility_gate_passed,
        "frozen_render_hash_gate_passed": frozen_hash_gate_passed,
        "gate_passed": overall_passed,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    for r in renders:
        status = "OK" if r["gate_passed"] else "FAIL"
        print(f"[{status}] {r['scorer_key']:8s} {r['condition']:16s} "
             f"tokens={r['input_token_count']} text_sha256={r['rendered_text_sha256'][:12]}")
    if not template_gate_passed:
        print("\nTEMPLATE GATE FAILED on:")
        for r in renders:
            if not r["gate_passed"]:
                print(f"  {r['scorer_key']}/{r['condition']}: "
                     f"{[k for k, v in r['fail_conditions'].items() if not v['passed']]}")
    if not residency_gate_passed:
        print("\nRESIDENCY GATE FAILED:")
        for k, v in residency_reports.items():
            if not v.get("passed", True):
                print(f"  {k}: {v.get('problems')}")
    if not use_cache_gate_passed:
        print("\nUSE_CACHE ASSERTION FAILED:")
        for k, v in use_cache_reports.items():
            if not v.get("passed", True):
                print(f"  {k}: model.config.use_cache={v.get('model_config_use_cache')} "
                     f"model.generation_config.use_cache={v.get('generation_config_use_cache')}")
    if not reproducibility_gate_passed:
        print("\nA3 PRODUCTION-PATH REPRODUCIBILITY FAILED:")
        for k, v in reproducibility_reports.items():
            if not v.get("passed", True):
                print(f"  {k}: {v.get('n_mismatched_conditions')} condition(s) mismatched "
                     f"across {v.get('repetitions_per_condition')} repetitions; "
                     f"calls={v.get('n_calls')}/{v.get('n_calls_expected')}")
                for m in v.get("mismatches", []):
                    print(f"    {m['condition']}: {m['differing_invariants']}")
                if v.get("conditions_with_missing_repetitions"):
                    print(f"    missing repetitions: "
                         f"{v['conditions_with_missing_repetitions']}")
    if not frozen_hash_gate_passed:
        print("\nA3 FROZEN RENDER-HASH COMPARISON FAILED:")
        print(f"  checked {frozen_hash_report['n_checked']} of "
             f"{frozen_hash_report['n_frozen_hashes_available']} frozen hashes")
        for m in frozen_hash_report["mismatches"]:
            print(f"  {m['scorer_key']}/{m['condition']}: frozen {m['frozen'][:16]} "
                 f"!= actual {m['actual'][:16]}")
    print(f"\nGATE {'PASSED' if overall_passed else 'FAILED'}")
    print(f"[save] {out_path}")
    return 0 if overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
