#!/usr/bin/env python3
"""Score the frozen 578 candidate answers: 4 scorers (Llama, Qwen, Gemma, Olmo-3.1-32B) x
578 tasks x 6 conditions = 13,872 calls. Writes into results/final_behavioral_study -- a
completely new output directory, never touching results/scaled_silent_influence[/
_adjudicated] (the completed, frozen 90-task run).

The fourth scorer is allenai/Olmo-3.1-32B-Instruct (Amendment A2), which replaces
mistralai/Mistral-Small-24B-Instruct-2501 (Amendment A1's pin; never run -- its pin file
is preserved unmodified as a historical artifact at configs/scorer_mistral_small_24b_pin.json).

Message wrapping is per Amendment A2's E8 resolution (silent_influence.final_study_messages):
Llama/Qwen/Gemma remain user-message-only; Olmo-3.1-32B gets an explicit empty system
message, for the same reason A1 gave Mistral one -- its official template injects a
default persona/date system message when no system turn is supplied. The scoring prompt
itself (silent_influence.scaled_conditions.render_prompt) and the parser
(silent_influence.scaled_parsing.parse_final_score) are FROZEN, byte-identical to the
90-task run, and are not modified here.

Generation is deterministic on every call (do_sample=False, seed=42 via
transformers.set_seed, and the loaded model's generation_config is reset in
exact_generation.load_exact_model to neutralize any shipped sampling defaults). For
Olmo-3.1-32B specifically (Amendment A2 E9 / Clarification C1_2), config.json ships
use_cache=False; ExactModelSpec.force_use_cache=True makes load_exact_model set
model.config.use_cache and model.generation_config.use_cache to True explicitly, and makes
every generate_exact/generate_exact_batch call for this scorer pass use_cache=True
explicitly too -- both, not either, so nothing here relies on a shipped default.

Batching defaults to size 1 per scorer. A scorer may only run with batch size > 1 if
results/final_behavioral_study/batching_equivalence_verdict.json (written by
scripts/run_batching_equivalence_smoke.py) records that scorer as having passed the
frozen batching-equivalence smoke test; a scorer with no verdict on file, or a failed
verdict, always runs at batch size 1 -- this is the "automatic permanent fallback"
required by Amendment A1's batching.on_any_mismatch. Units are length-bucketed (sorted by
rendered prompt length, then chunked) before batching, to keep batch padding small.

Every call is written to JSONL immediately (append + fsync via RecordWriter); resuming a
killed run skips every unit already present by unit_id and never regenerates it.

    python scripts/run_final_scoring.py --dry-run
    python scripts/run_final_scoring.py --stub                       # no-GPU plumbing
    python scripts/run_final_scoring.py \\
        --candidates-file data/candidates/final_olmo_answers.json \\
        --out results/final_behavioral_study
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import exact_generation as eg
from silent_influence import final_study_messages as fsm
from silent_influence import scaled_conditions as sc
from silent_influence import output_validity as ov
from silent_influence import scaled_parsing as sp
from silent_influence.environment import capture_environment
from silent_influence.logging_utils import make_logger
from silent_influence.records import RecordWriter, load_completed, write_manifest

# Amendment A4: the ceiling is per-scorer and lives on each ExactModelSpec. These two
# constants are the only values in play -- 512 for llama/qwen/gemma (frozen since plan
# v2.0) and 2048 for olmo32b alone. Call sites read spec.max_new_tokens; nothing reads a
# single study-wide ceiling any more, so one scorer cannot silently inherit another's.
# Amendment A7: the FROZEN final inference procedure. Batch size is policy, not something
# a verdict file grants: A7 prospectively supersedes A6's requirement that batch-6 output
# reproduce batch-1 output token-for-token, so there is no equivalence gate left to
# consult. Agreement with batch 1 is neither required nor tested.
#
# One task's six conditions form exactly one batch, in the frozen canonical condition
# order, because build_units() emits units task-major with sc.CONDITIONS in order and A7
# forbids reordering. 578 tasks -> 578 physical batches of 6 per small scorer.
# Amendment A8 supersedes A7's unconditional small-scorer batch-6 decision. Frozen now:
#   generator batch 6, OLMo-3.1-32B batch 1. llama/qwen/gemma are PENDING CALIBRATION and may
#   not run a real production scoring pass until a calibration verdict exists for the exact
#   hardware/software environment that will produce their outputs.
# Amendment A9: only 234 of the 578 tasks are scored, and OLMo-3.1-32B runs only the two
# primary-contrast conditions as the larger-model replication. The other 344 answers are
# preserved untouched as audit artifacts.
A9_TASK_SELECTION = REPO / "data/prompts/a9_scoring_tasks_seed20260818.json"
A9_TASK_SELECTION_SHA256 = "8deb5178ad53c5942afa00ac285eff620762027378aed67b93b33dd6c44cc11a"
A9_N_TASKS = 234
A9_PRIMARY_CONDITIONS = ("no_history", "self_low_2")
A9_SCORER_CONDITIONS = {
    "llama": None,      # None = all six frozen conditions
    "qwen": None,
    "gemma": None,
    "olmo32b": A9_PRIMARY_CONDITIONS,
}
A9_EXPECTED_LOGICAL = {"llama": 1404, "qwen": 1404, "gemma": 1404, "olmo32b": 468}
A9_EXPECTED_TOTAL = 4680

A8_FROZEN_BATCH_POLICY = {"olmo32b": 1}
A8_PENDING_CALIBRATION = ("llama", "qwen", "gemma")
A8_PROVISIONAL_BATCH_SIZE = 6          # what calibration will test; NOT yet licensed
A7_GENERATOR_BATCH_SIZE = 6

# A8 calibration thresholds, frozen BEFORE calibration and applied symmetrically -- the same
# bounds hold whether batching raises or lowers the effect. Calibrated on the existing 90-task
# study only.
A8_CALIBRATION_THRESHOLDS = {
    "max_abs_primary_delta_difference": 0.25,
    "max_abs_task_positive_fraction_change": 0.05,
    "min_batch6_a5_valid_rate": 0.95,
    "max_abs_validity_rate_difference_no_history_vs_self_low_2": 0.02,
}


def a8_calibration_verdict(path, scorer_key: str):
    """The calibration verdict for one scorer, or None. Absent, malformed, or explicitly
    failing all read as "not licensed": A8's default is batch 1, never a guess."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    entry = data.get(scorer_key)
    return entry if isinstance(entry, dict) else None

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
SCORE_SEED = 42
DEFAULT_BATCH_SIZE = 1
# Frozen collection_failure_policy: a TECHNICAL failure (exception during scoring, or
# literally empty output) is retried up to 3 times with an identical prompt and identical
# decoding config. A PARSE failure -- a non-empty response the parser cannot read -- is
# never retried, and the prompt/decoding is never altered to coax a parseable answer.
MAX_RETRIES_PER_UNIT = 3


def is_technical_failure(text, err) -> bool:
    """Exactly the frozen definition: an exception, or literally empty output. A non-empty
    but unparseable response is a PARSE failure and is deliberately not covered here."""
    return err is not None or text is None or not text.strip()


def unit_id(scorer_key: str, dataset: str, source_task_id: str, condition: str) -> str:
    return f"{scorer_key}__{dataset}__{source_task_id}__{condition}"


def load_candidates(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["accepted"]


def conditions_for(scorer_key: str) -> list:
    """A9: llama/qwen/gemma run all six frozen conditions; OLMo-3.1-32B runs only the two
    primary-contrast conditions, in frozen canonical order."""
    names = A9_SCORER_CONDITIONS.get(scorer_key, None)
    if names is None:
        return list(sc.CONDITIONS)
    return [c for c in sc.CONDITIONS if c.name in names]


def build_units(candidates: list, scorer_key: str = None) -> list:
    """Task-major, canonical condition order. With a scorer key the unit list is restricted to
    that scorer's frozen condition set (A9)."""
    conds = conditions_for(scorer_key) if scorer_key else list(sc.CONDITIONS)
    units = []
    for cand in candidates:
        for cond in conds:
            units.append({"candidate": cand, "condition": cond})
    return units


def load_a9_selection(path, skip_hash_check: bool = False) -> set:
    """The frozen 234-task set, as (dataset, source_task_id). Hash-gated: a drifted selection
    would silently change the study population."""
    p = Path(path)
    got = hashlib.sha256(p.read_bytes()).hexdigest()
    if not skip_hash_check and got != A9_TASK_SELECTION_SHA256:
        raise SystemExit(f"A9 SELECTION MISMATCH: {got} != {A9_TASK_SELECTION_SHA256}")
    d = json.loads(p.read_text(encoding="utf-8"))
    sel = {(ds, tid) for ds in d["datasets"] for tid in d["datasets"][ds]["selected"]}
    if not skip_hash_check and len(sel) != A9_N_TASKS:
        raise SystemExit(f"A9 selection has {len(sel)} tasks, expected {A9_N_TASKS}")
    return sel


def fmt_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}h{m:02d}m{s:02d}s" if h else f"{m:d}m{s:02d}s"


def load_batching_verdict(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def a7_batch_size(scorer_key: str, *, calibration_path=None, olmo_gate_path=None,
                  pin_batch_size=None, stub: bool = False) -> int:
    """The batch size A8 licenses for this scorer.

    - OLMo-3.1-32B: frozen at 1.
    - llama / qwen / gemma: PENDING. A real pass requires a passing calibration verdict for the
      production environment; batch 6 only if that verdict passed, batch 1 if it failed, and a
      HARD STOP if none exists. A8 forbids scoring these scorers on unlicensed hardware, and
      the absence of a verdict is never read as permission.
    - Under --stub the provisional size is used to exercise the batched code path. A stub pass
      generates no real tokens and cannot write a protected production target, so it licenses
      nothing.
    """
    # Amendment A10: an explicit pin fixes the batch size for this host and SHORT-CIRCUITS
    # every verdict lookup. A calibration verdict is valid only for the hardware it was
    # measured on, so on a reassigned host it must not be consulted at all -- not even to be
    # overridden afterwards, which would leave the wrong value reachable by a later edit.
    if pin_batch_size is not None:
        if pin_batch_size < 1:
            raise SystemExit(f"A10: invalid pinned batch size {pin_batch_size}")
        return int(pin_batch_size)
    if scorer_key == "olmo32b":
        # A9: batch 2 only if the bounded capacity/repeatability gate passed; otherwise the
        # A8-frozen batch 1. Absence of a gate verdict is never permission.
        v = a8_calibration_verdict(olmo_gate_path, "olmo32b") if olmo_gate_path else None
        if v is None and olmo_gate_path:
            try:
                d = json.loads(Path(olmo_gate_path).read_text(encoding="utf-8"))
                v = d if d.get("scorer") == "olmo32b" else None
            except (json.JSONDecodeError, OSError):
                v = None
        if v is not None and v.get("passed") is True:
            return 2
        return A8_FROZEN_BATCH_POLICY["olmo32b"]
    if scorer_key in A8_FROZEN_BATCH_POLICY:
        return A8_FROZEN_BATCH_POLICY[scorer_key]
    if scorer_key not in A8_PENDING_CALIBRATION:
        raise SystemExit(f"A8 defines no batch size for scorer {scorer_key!r}; refusing to guess")
    if stub:
        return A8_PROVISIONAL_BATCH_SIZE
    verdict = a8_calibration_verdict(calibration_path, scorer_key)
    if verdict is None:
        raise SystemExit(
            f"HARD STOP (A8): {scorer_key} is PENDING CALIBRATION and has no calibration "
            f"verdict for this environment. A8 forbids production scoring for llama/qwen/gemma "
            f"until batch 6 has been calibrated against batch 1 on the exact hardware that "
            f"will produce their outputs, using the frozen thresholds. Pass --calibration with "
            f"a verdict produced there, or run this scorer on its own GPU.")
    if verdict.get("passed") is True:
        return A8_PROVISIONAL_BATCH_SIZE
    return 1


def assert_a7_batch_composition(batch: list, scorer_key: str) -> None:
    """Every batch of 6 must be exactly one task's six conditions in canonical order. Checked
    per batch so a reordering or a mixed-task batch stops the run instead of silently producing
    a differently-composed inference than the one A7 froze."""
    if len(batch) == 1:
        return
    tasks = {u["candidate"]["source_task_id"] for u in batch}
    if len(tasks) != 1:
        raise SystemExit(f"A7 violation ({scorer_key}): batch spans {len(tasks)} tasks; "
                         f"one task's six conditions must form exactly one batch")
    got = [u["condition"].name for u in batch]
    want = [c.name for c in conditions_for(scorer_key)]
    if got != want:
        raise SystemExit(f"A7 violation ({scorer_key}): batch condition order {got} != "
                         f"frozen canonical order {want}")


def effective_batch_size(scorer_key: str, requested: int, verdict: dict,
                         spec: "eg.ExactModelSpec | None" = None) -> int:
    """Batch size > 1 is permitted for a scorer only if every gate that applies to it is
    independently satisfied by the verdict on file. Absence of a verdict, or of any
    required field, is treated exactly like a failed verdict -- batch size 1.

    Every condition below is re-checked HERE rather than trusting the producer's rolled-up
    "passed" flag, because that flag is the single point at which a stale, partially
    written, hand-edited, or stub-derived verdict file could license batching that was
    never actually measured:

      - `stub` true  -> refuse. A --stub smoke run measures nothing: it neither generates
        real tokens nor touches a GPU, yet it previously produced a verdict whose rolled-up
        "passed" was true for every scorer.
      - `token_equivalence_passed` must be explicitly true (Amendment A1 batching).
      - `memory_preflight_passed` must be explicitly true whenever the SPEC says this
        model needs it (Amendment A2 batching / Clarification C1_3: "any larger batch
        requires BOTH exact token-ID equivalence AND measured memory approval"). The
        requirement is taken from spec.requires_memory_preflight, not from the verdict's
        own self-reported `memory_preflight_required`, so a verdict that simply omits or
        downgrades that field cannot talk its way out of the gate.
    """
    if requested <= 1:
        return 1
    entry = verdict.get(scorer_key)
    if not isinstance(entry, dict):
        return 1
    if entry.get("stub", False):
        return 1
    if entry.get("passed", False) is not True:
        return 1
    if entry.get("token_equivalence_passed", False) is not True:
        return 1
    needs_memory = bool(spec.requires_memory_preflight) if spec is not None else bool(
        entry.get("memory_preflight_required", False))
    if needs_memory and entry.get("memory_preflight_passed", False) is not True:
        return 1
    return requested


def length_bucket(units: list) -> list:
    """Sort by rendered prompt length so consecutive chunks (the batches) have similar
    length, minimizing left-padding waste. A stable sort keeps the original unit-order
    tiebreak deterministic."""
    return sorted(units, key=lambda u: len(u["_prompt"]))


def chunk(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def score_one(loaded, scorer_spec, u, stub: bool, log=print) -> dict:
    """One unit at batch size 1, with the frozen retry policy: up to
    MAX_RETRIES_PER_UNIT attempts on a technical failure, identical prompt and identical
    decoding config every time (nothing about the call changes between attempts -- the
    retry exists to absorb environmental faults, not to change model behaviour). A
    non-empty unparseable response is returned on the first attempt and never retried."""
    cand, cond = u["candidate"], u["condition"]
    prompt = sc.render_prompt(cand["question"], cand["answer"], cond)
    messages = fsm.build_scorer_messages(scorer_spec.key, prompt)
    gen_fn = eg.generate_exact_stub if stub else eg.generate_exact

    attempts_made = 0
    for attempt in range(1, MAX_RETRIES_PER_UNIT + 1):
        attempts_made = attempt
        err = None
        try:
            result = gen_fn(loaded, messages,
                            max_new_tokens=scorer_spec.max_new_tokens,
                            seed=SCORE_SEED)
            raw = result["text"]
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            raw = None
            result = {"generation_seconds": 0.0, "prompt_tokens": None,
                     "first_input_token_id": None, "last_input_token_id": None}
        if not is_technical_failure(raw, err):
            break
        if attempt < MAX_RETRIES_PER_UNIT:
            log(f"    [{scorer_spec.key}] technical failure on "
               f"{unit_id(scorer_spec.key, cand['dataset'], cand['source_task_id'], cond.name)} "
               f"attempt {attempt}/{MAX_RETRIES_PER_UNIT}: {err or 'empty output'}")

    pr = sp.parse_final_score(raw) if err is None else sp.ParseResult(
        sp.EMPTY_OUTPUT, flagged_for_review=True, error=err)
    return _build_record(scorer_spec, cand, cond, prompt, messages, raw, result, err, pr,
                         attempts=attempts_made)


class BatchCallFailed(Exception):
    """A batched generate() call raised (typically CUDA OOM on a long-prompt bucket).

    Deliberately propagated rather than converted into per-unit technical failures: a
    batch-level fault says nothing about the individual units, and silently recording
    `batch_size` units as failures would destroy real data for an environmental reason.
    The caller catches this, permanently drops THIS scorer to batch size 1 (Amendment A1
    batching.on_any_mismatch, applied per-model and never inferred across models), and
    re-runs the same units one at a time under the normal retry policy."""


def score_batch(loaded, scorer_spec, units, stub: bool) -> list:
    prompts, messages_list = [], []
    for u in units:
        cand, cond = u["candidate"], u["condition"]
        prompt = sc.render_prompt(cand["question"], cand["answer"], cond)
        prompts.append(prompt)
        messages_list.append(fsm.build_scorer_messages(scorer_spec.key, prompt))
    gen_fn = eg.generate_exact_batch_stub if stub else eg.generate_exact_batch
    try:
        results = gen_fn(loaded, messages_list,
                         max_new_tokens=scorer_spec.max_new_tokens,
                         seed=SCORE_SEED)
    except Exception as e:
        raise BatchCallFailed(f"{type(e).__name__}: {e}") from e

    out = []
    for u, prompt, messages, result in zip(units, prompts, messages_list, results):
        raw = result.get("text")
        # A batched row that came back technically empty is not retried inside the batch;
        # it is handed back to the batch-1 path, which applies the frozen retry policy.
        if is_technical_failure(raw, None):
            raise BatchCallFailed(
                f"empty output for unit "
                f"{unit_id(scorer_spec.key, u['candidate']['dataset'], u['candidate']['source_task_id'], u['condition'].name)} "
                f"in a batched call; re-running this scorer at batch size 1")
        pr = sp.parse_final_score(raw)
        out.append(_build_record(scorer_spec, u["candidate"], u["condition"], prompt,
                                 messages, raw, result, None, pr, attempts=1))
    return out


def _build_record(scorer_spec, cand, cond, prompt, messages, raw, result, err, pr,
                  *, attempts: int = 1) -> dict:
    uid = unit_id(scorer_spec.key, cand["dataset"], cand["source_task_id"], cond.name)
    rec = {
        "unit_id": uid,
        "dataset": cand["dataset"], "source_task_id": cand["source_task_id"],
        "category": cand["category"], "question": cand["question"],
        "candidate_answer": cand["answer"], "candidate_answer_sha256": cand["answer_sha256"],
        "previously_used": cand.get("previously_used"),
        "prior_use_phases": cand.get("prior_use_phases"),
        "generator_model": cand["generator_model"], "generator_revision": cand["generator_revision"],
        "scorer_key": scorer_spec.key, "scorer_model_id": scorer_spec.hf_id,
        "scorer_revision": scorer_spec.revision,
        "condition": cond.name, "added_context": cond.added_context,
        "prompt": prompt, "messages": messages, "response": raw,
        "parse_status": pr.status, "parse_tier": pr.tier,
        "parsed_score": pr.score, "parse_ok": pr.ok,
        "flagged_for_review": pr.flagged_for_review, "parse_error": pr.error,
        "generation_error": err,
        "generation_params": {"do_sample": False,
                             "max_new_tokens_per_scorer": {sp.key: sp.max_new_tokens
                                                          for sp in SCORERS},
                              "pad_token_id": "tokenizer.eos_token_id"},
        "seed": SCORE_SEED,
        "attempts": attempts,
        "max_retries_per_unit": MAX_RETRIES_PER_UNIT,
        # Amendment A5 audit trail: what the ceiling was, whether it was reached, and
        # whether generation actually terminated. Retained for every record, valid or not.
        "max_new_tokens": scorer_spec.max_new_tokens,
        "output_tokens": result.get("output_tokens"),
        "hit_token_cap": result.get("hit_token_cap"),
        "emitted_terminator": result.get("emitted_terminator"),
        "parse_matched_text": pr.matched_text,
        "prompt_tokens": result.get("prompt_tokens"),
        "first_input_token_id": result.get("first_input_token_id"),
        "last_input_token_id": result.get("last_input_token_id"),
        "batch_size": result.get("batch_size", 1),
        "generation_seconds": round(result.get("generation_seconds", 0.0), 3),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # A5: validity is decided once, here, and stored on the record. Every later stage
    # (resume, recovery routing, adjudication, analysis) reads the stored verdict instead of
    # re-deriving it, so they cannot disagree about the same response.
    return ov.annotate(rec)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates-file",
                    default=str(REPO / "data/candidates/final_olmo_answers.json"))
    ap.add_argument("--out", default=str(REPO / "results/final_behavioral_study"))
    ap.add_argument("--task-selection", default=str(A9_TASK_SELECTION),
                    help="A9 frozen 234-task selection")
    ap.add_argument("--pin-batch-size", type=int, default=None,
                    help="A10: fix the batch size for this host and consult no calibration "
                         "verdict (small-GPU scorers are pinned to 1; a verdict from other "
                         "hardware licenses nothing)")
    ap.add_argument("--olmo-gate", default=None,
                    help="A9 OLMo batch-2 capacity/repeatability gate verdict")
    ap.add_argument("--calibration", default=None,
                    help="A8 calibration verdict JSON for llama/qwen/gemma, produced on the "
                         "hardware that will run that scorer's production outputs")
    ap.add_argument("--scorers", default=None,
                    help="comma-separated scorer keys to run (A8: this A100 runs olmo32b only; "
                         "llama/qwen/gemma run on their own GPU after calibration)")
    ap.add_argument("--batching-verdict",
                    default=str(REPO / "results/final_behavioral_study"
                                       "/batching_equivalence_verdict.json"))
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                    help="requested batch size; actually applied only for scorers with a "
                         "passed batching-equivalence verdict on file (else forced to 1)")
    ap.add_argument("--skip-hash-check", action="store_true",
                    help="skip the A9 selection hash gate (tests only; never in production)")
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N remaining units per scorer (dev use)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stub", action="store_true",
                    help="deterministic no-GPU stub for plumbing tests "
                         "(resume/idempotency/batching harness/progress) only")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = make_logger(out_dir / "run.log")
    if not args.stub:
        eg.check_transformers_version(log)

    candidates = load_candidates(Path(args.candidates_file))
    units = build_units(candidates)
    for u in units:
        u["_prompt"] = sc.render_prompt(u["candidate"]["question"], u["candidate"]["answer"],
                                        u["condition"])
    n_per_scorer = len(units)
    total_units = n_per_scorer * len(SCORERS)
    verdict = load_batching_verdict(Path(args.batching_verdict))
    log(f"[plan] {len(candidates)} candidates x {len(sc.CONDITIONS)} conditions "
       f"x {len(SCORERS)} scorers = {total_units} calls")
    log(f"[batching] requested_batch_size={args.batch_size} "
       f"verdict_file={args.batching_verdict} "
       f"verdict_present_for={sorted(verdict.keys())}")

    if args.dry_run:
        u = units[0]
        prompt = u["_prompt"]
        log(f"[dry-run] example unit_id: "
           f"{unit_id(SCORERS[0].key, u['candidate']['dataset'], u['candidate']['source_task_id'], u['condition'].name)}")
        log(f"[dry-run] example prompt:\n{prompt}")
        log(f"[dry-run] example olmo32b messages: "
           f"{fsm.build_scorer_messages('olmo32b', prompt)}")
        log("[dry-run] nothing scored.")
        return 0

    records_path = out_dir / "raw_results.jsonl"
    done = load_completed(records_path) if not args.no_resume else set()
    log(f"[resume] {len(done)} units already complete")

    # Amendment A7 resume: batch composition comes from the frozen manifest and never from
    # completion state. A batch is skipped only if EVERY unit in it is already recorded; a
    # partially complete batch is rerun in full, because a leftover-only batch would be a
    # different composition than the one A7 froze. Rerun records supersede earlier ones for
    # the same unit_id (last write wins on read).
    a9 = load_a9_selection(args.task_selection, args.skip_hash_check)
    before = len(candidates)
    candidates = [c for c in candidates
                  if (c["dataset"], c["source_task_id"]) in a9]
    log(f"[A9] task selection {len(candidates)}/{before} tasks "
        f"(sha256-gated 234-task set); {before - len(candidates)} preserved unscored")
    full_a9 = len(a9) == A9_N_TASKS
    if full_a9 and len(candidates) != A9_N_TASKS:
        raise SystemExit(f"HARD STOP (A9): {len(candidates)} tasks after selection, "
                         f"expected {A9_N_TASKS}")

    selected = ([k.strip() for k in args.scorers.split(",") if k.strip()]
                if args.scorers else [sp.key for sp in SCORERS])
    unknown = set(selected) - {sp.key for sp in SCORERS}
    if unknown:
        raise SystemExit(f"unknown scorer key(s) in --scorers: {sorted(unknown)}")
    run_specs = [sp for sp in SCORERS if sp.key in selected]
    log(f"[A8] scorers this run: {[sp.key for sp in run_specs]}")

    todo_batches_by_scorer = {}
    units_by_scorer = {}
    for scorer_spec in run_specs:
        bs = a7_batch_size(scorer_spec.key, calibration_path=args.calibration,
                           olmo_gate_path=args.olmo_gate,
                           pin_batch_size=args.pin_batch_size, stub=args.stub)
        s_units = build_units(candidates, scorer_spec.key)
        units_by_scorer[scorer_spec.key] = s_units
        n_cond = len(conditions_for(scorer_spec.key))
        expect = A9_EXPECTED_LOGICAL.get(scorer_spec.key) if full_a9 else None
        if expect is not None and len(s_units) != expect:
            raise SystemExit(f"HARD STOP (A9): {scorer_spec.key} has {len(s_units)} logical "
                             f"units, expected {expect}")
        log(f"[A9] {scorer_spec.key}: {len(candidates)} tasks x {n_cond} conditions "
            f"= {len(s_units)} logical units at batch {bs}")
        # batch size must divide the condition count so a batch is exactly one task's block
        if bs > 1 and n_cond % bs != 0:
            raise SystemExit(f"HARD STOP (A9): batch {bs} does not partition {n_cond} "
                             f"conditions for {scorer_spec.key}")
        all_batches = list(chunk(s_units, bs))
        if args.limit is not None:
            all_batches = all_batches[:max(1, args.limit // bs)]
        pending = []
        n_skipped = 0
        for batch in all_batches:
            uids = [unit_id(scorer_spec.key, u["candidate"]["dataset"],
                            u["candidate"]["source_task_id"], u["condition"].name)
                    for u in batch]
            if all(uid in done for uid in uids):
                n_skipped += 1
                continue
            pending.append(batch)
        todo_batches_by_scorer[scorer_spec.key] = pending
        if n_skipped:
            log(f"[resume] {scorer_spec.key}: {n_skipped} complete batches skipped, "
                f"{len(pending)} to run at batch_size={bs}")
    n_total_todo = sum(len(b) for bs_ in todo_batches_by_scorer.values() for b in bs_)

    t0 = time.time()
    n_done_this_run = 0
    stats_by_status = {}
    batch_fallbacks = []          # per-model permanent fallbacks, recorded in the manifest
    effective_batch_used = {}     # scorer_key -> batch size actually in force at the end
    hf_token = os.environ.get("HF_TOKEN")

    with RecordWriter(records_path) as writer:
        for scorer_spec in run_specs:
            scorer_batches = todo_batches_by_scorer[scorer_spec.key]
            scorer_units = [u for b in scorer_batches for u in b]
            if not scorer_batches:
                log(f"[model] {scorer_spec.key}: nothing to do, skipping load")
                continue

            # Amendment A7 defines the batch size; the superseded equivalence gate is
            # no longer consulted.
            bs = a7_batch_size(scorer_spec.key, calibration_path=args.calibration,
                               olmo_gate_path=args.olmo_gate,
                               pin_batch_size=args.pin_batch_size, stub=args.stub)
            log(f"[model] loading {scorer_spec.key} ({scorer_spec.hf_id}) "
               f"for {len(scorer_units)} units at batch_size={bs}")
            loaded = (eg.load_stub_model(scorer_spec) if args.stub
                     else eg.load_exact_model(scorer_spec, hf_token=hf_token))
            log(f"[model] loaded attn={loaded.attn_implementation} "
               f"transformers={loaded.transformers_version} "
               f"chat_template_sha256={loaded.chat_template_sha256}")
            try:
                # A7: iterate the batches built from the frozen manifest. No re-chunking, no
                # length bucketing, no fallback -- composition is fixed by the amendment.
                n_batches = len(scorer_batches)
                i = 0
                for bi, batch in enumerate(scorer_batches, 1):
                    if bs > 1:
                        assert_a7_batch_composition(batch, scorer_spec.key)
                        try:
                            recs = score_batch(loaded, scorer_spec, batch, args.stub)
                        except BatchCallFailed as e:
                            # A7: "never silently fall back from batch 6 to batch 1". The
                            # previous behaviour re-ran the units singly and continued, which
                            # would have produced part of the study under a batch size the
                            # amendment does not define. This is now a hard stop; resume
                            # reruns the identical batch.
                            raise SystemExit(
                                f"HARD STOP (A7): batched call failed for "
                                f"{scorer_spec.key} at batch {bi}/{n_batches} "
                                f"(units {[u['candidate']['source_task_id'] for u in batch]}): "
                                f"{e}\nA7 forbids falling back to batch size 1. Fix the cause "
                                f"and resume; the identical batch will be rerun.") from e
                    else:
                        recs = [score_one(loaded, scorer_spec, u, args.stub, log)
                                for u in batch]
                    # Atomic per-batch commit: every record of this batch is written together.
                    for rec in recs:
                        writer.write(rec)
                        n_done_this_run += 1
                        stats_by_status[rec["parse_status"]] = \
                            stats_by_status.get(rec["parse_status"], 0) + 1
                    # RecordWriter.write already flushes+fsyncs each record, so the
                    # batch is durable on disk as soon as its last record is written.
                    i += len(batch)

                    if bi % 20 == 0 or bi == n_batches:
                        elapsed = time.time() - t0
                        rate = elapsed / max(n_done_this_run, 1)
                        cps = n_done_this_run / elapsed if elapsed > 0 else 0.0
                        eta = rate * (n_total_todo - n_done_this_run)
                        log(f"  [{scorer_spec.key}] batch {bi}/{n_batches} "
                            f"units {i}/{len(scorer_units)} "
                            f"(run total {n_done_this_run}/{n_total_todo}) "
                            f"elapsed={fmt_eta(elapsed)} avg={rate:.2f}s/unit "
                            f"units_per_sec={cps:.3f} "
                            f"eta_remaining={fmt_eta(eta)} batch_size={bs}")
            finally:
                eg.unload(loaded)
            effective_batch_used[scorer_spec.key] = bs

    env = capture_environment()
    with open(out_dir / "environment.json", "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)

    write_manifest(out_dir / "manifest_scoring.json", {
        "records_path": str(records_path),
        "n_candidates": len(candidates), "n_conditions": len(sc.CONDITIONS),
        "n_scorers": len(SCORERS), "n_units_total": total_units,
        "n_done_this_run": n_done_this_run,
        "n_already_done_before_this_run": len(done),
        "generation_params": {"do_sample": False,
                             "max_new_tokens_per_scorer": {sp.key: sp.max_new_tokens
                                                          for sp in SCORERS}},
        "seed": SCORE_SEED, "requested_batch_size": args.batch_size,
        "batching_verdict_used": verdict,
        "effective_batch_size_per_scorer": effective_batch_used,
        "batch_permanent_fallbacks": batch_fallbacks,
        "retry_policy": {"max_attempts_per_unit": MAX_RETRIES_PER_UNIT,
                        "technical_failure_only": True,
                        "parse_failure_never_retried": True,
                        "identical_prompt_and_decoding": True},
        "scorers": [{"key": s.key, "hf_id": s.hf_id, "revision": s.revision,
                    "disable_thinking": s.disable_thinking} for s in SCORERS],
        "conditions": [{"name": c.name, "added_context": c.added_context}
                      for c in sc.CONDITIONS],
        "stats_by_parse_status": stats_by_status,
        "wall_seconds": round(time.time() - t0, 2),
    })
    log(f"\n[done] {n_done_this_run} calls this run -> {records_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
