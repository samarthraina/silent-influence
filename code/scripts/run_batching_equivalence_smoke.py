#!/usr/bin/env python3
"""Frozen batching-equivalence smoke test (Amendment A1 "batching.equivalence_smoke_set").

The task SET is pinned and must not change: 6 tasks (2 arena_hard, 4 wildbench) drawn from
the COMPLETED, frozen 90-task run's answers -- read-only from
results/scaled_silent_influence/frozen_olmo_answers.json, never modified, and verified
outside the 578-task manifest so there is no contamination between the two studies. The 6
tasks span the prompt+answer length range, including two token-capped answers, to exercise
the longest length bucket.

144 units (6 tasks x 6 conditions x 4 scorers) are each scored twice: once at batch size 1
(the existing single-call path, exact_generation.generate_exact) and once through the
batched path (exact_generation.generate_exact_batch, grouped per-scorer by length-bucket
into --batch-size chunks). Equivalence criterion, per Amendment A1: sha256 of the
GENERATED TOKEN-ID SEQUENCE (after trimming each row to its first terminator, so a
batch's padding-after-finish never produces a spurious mismatch -- see
exact_generation.trim_to_first_eos) must be identical between the two paths for every
unit. Decoded text and parsed score are checked as a secondary confirmation only.

For a scorer with ExactModelSpec.requires_memory_preflight=True (Olmo-3.1-32B-Instruct
only, Amendment A2 batching / Clarification C1_3), token-ID equivalence alone is not
sufficient: a MEASURED memory preflight (exact_generation.memory_preflight_ok, comparing
peak GPU memory during the batched run against device capacity) must ALSO pass before
batching is permitted for that scorer, because it leaves only ~13.9 GiB of headroom on an
80 GB card versus ~31.2 GiB for the superseded 24B scorer -- "it didn't crash on the
smoke set" is not itself evidence the intended batch size is safe at scale.

on_any_mismatch_or_failed_memory_preflight: that scorer runs the ENTIRE 578-task study at
batch size 1. This script writes
results/final_behavioral_study/batching_equivalence_verdict.json, which
run_final_scoring.py reads to decide, per scorer, whether batch size > 1 is permitted --
equivalence (and, where required, the memory preflight) is per-model and never inferred
across models.

    python scripts/run_batching_equivalence_smoke.py --stub   # no-GPU plumbing check
    python scripts/run_batching_equivalence_smoke.py           # real GPU check (288 calls)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import exact_generation as eg
from silent_influence import final_preflight_checks as fpc
from silent_influence import final_study_messages as fsm
from silent_influence import scaled_conditions as sc
from silent_influence import scaled_parsing as sp
from silent_influence.records import RecordWriter, load_completed, write_manifest

FROZEN_90TASK_ANSWERS = REPO / "results/scaled_silent_influence/frozen_olmo_answers.json"
SMOKE_SET = [
    {"dataset": "arena_hard", "task_id": "15df2da070ca483d", "chars": 65},
    {"dataset": "arena_hard", "task_id": "449e2408d16d43e9", "chars": 894},
    {"dataset": "wildbench", "task_id": "ee56e822a2a146f2", "chars": 2595},
    {"dataset": "wildbench", "task_id": "8f75b90101a842b4", "chars": 4084},
    {"dataset": "wildbench", "task_id": "cd4a0c09e12146ad", "chars": 7531},
    {"dataset": "wildbench", "task_id": "d62241ec92e64571", "chars": 11328},
]
FINAL_578_MANIFEST_SHA256 = "a001d48b7769311da33cba1a8ef51bb4e9d1a27b2cc0d007bce85adab606037f"

# Amendment A4: per-scorer ceilings (512 for llama/qwen/gemma, 2048 for olmo32b).
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


def load_smoke_answers() -> list:
    """Pull question+answer for the 6 pinned tasks from the completed 90-task run,
    read-only, and confirm none of them collides with a source_task_id in the frozen
    578-task manifest (no contamination between the two studies)."""
    with open(FROZEN_90TASK_ANSWERS, encoding="utf-8") as f:
        answers_90 = json.load(f)["accepted"]
    by_key = {(a["dataset"], a["slot_task_id"]): a for a in answers_90}

    manifest_path = REPO / "data/prompts/final_tasks_v2_english_seed20260817.json"
    with open(manifest_path, encoding="utf-8") as f:
        manifest_578 = json.load(f)
    ids_578 = {(ds, t["source_task_id"]) for ds, dd in manifest_578["datasets"].items()
              for t in dd["selected"]}

    out = []
    for spec in SMOKE_SET:
        key = (spec["dataset"], spec["task_id"])
        assert key not in ids_578, f"{key} is IN the 578-task manifest -- contamination!"
        a = by_key.get(key)
        if a is None:
            raise SystemExit(f"smoke task {key} not found in {FROZEN_90TASK_ANSWERS}")
        combined_chars = len(a["question"]) + len(a["answer"])
        assert combined_chars == spec["chars"], (
            f"{key}: question+answer chars {combined_chars} != pinned {spec['chars']}")
        out.append({"dataset": a["dataset"], "task_id": a["slot_task_id"],
                   "category": a["category"], "question": a["question"],
                   "answer": a["answer"], "hit_token_cap": a["hit_token_cap"]})
    return out


def build_units(tasks: list) -> list:
    units = []
    for t in tasks:
        for cond in sc.CONDITIONS:
            units.append({"task": t, "condition": cond})
    return units


def run_path(loaded, scorer_spec, units: list, batch_size: int, stub: bool) -> dict:
    """Returns unit_id -> per-unit result dict, for one path (batch1 or batched)."""
    out = {}
    if batch_size <= 1:
        gen_fn = eg.generate_exact_stub if stub else eg.generate_exact
        for u in units:
            prompt = sc.render_prompt(u["task"]["question"], u["task"]["answer"],
                                      u["condition"])
            messages = fsm.build_scorer_messages(scorer_spec.key, prompt)
            r = gen_fn(loaded, messages, max_new_tokens=scorer_spec.max_new_tokens,
                       seed=SCORE_SEED)
            out[_uid(scorer_spec.key, u)] = r
        return out

    bucketed = sorted(units, key=lambda u: len(u["task"]["question"]) + len(u["task"]["answer"]))
    gen_fn = eg.generate_exact_batch_stub if stub else eg.generate_exact_batch
    for i in range(0, len(bucketed), batch_size):
        chunk = bucketed[i:i + batch_size]
        prompts = [sc.render_prompt(u["task"]["question"], u["task"]["answer"], u["condition"])
                  for u in chunk]
        messages_list = [fsm.build_scorer_messages(scorer_spec.key, p) for p in prompts]
        results = gen_fn(loaded, messages_list, max_new_tokens=scorer_spec.max_new_tokens,
                         seed=SCORE_SEED)
        for u, r in zip(chunk, results):
            out[_uid(scorer_spec.key, u)] = r
    return out


def _uid(scorer_key: str, u: dict) -> str:
    return f"{scorer_key}__{u['task']['dataset']}__{u['task']['task_id']}__{u['condition'].name}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "results/final_behavioral_study"))
    ap.add_argument("--batch-size", type=int, default=6,
                    help="batch size used for the batched path; not itself pinned by the "
                         "frozen spec, only the task set and the equivalence criterion are")
    ap.add_argument("--stub", action="store_true",
                    help="no-GPU plumbing check: exercises the harness/comparison logic "
                         "with a deterministic stub, never verifies real model behavior")
    args = ap.parse_args()

    # Fail closed BEFORE any work: a --stub run must not write into the protected
    # final-results directory, whose filenames run_final_scoring.py trusts.
    fpc.assert_stub_output_is_not_a_protected_dir(args.out, stub=args.stub, repo_root=REPO)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_smoke_answers()
    units = build_units(tasks)
    assert len(units) == 36, f"expected 36 units (6 tasks x 6 conditions), got {len(units)}"

    per_scorer_results = {}
    hf_token = __import__("os").environ.get("HF_TOKEN")
    for spec in SCORERS:
        loaded = eg.load_stub_model(spec) if args.stub else eg.load_exact_model(
            spec, hf_token=hf_token)
        try:
            batch1 = run_path(loaded, spec, units, batch_size=1, stub=args.stub)
            if spec.requires_memory_preflight and not args.stub:
                import torch
                torch.cuda.reset_peak_memory_stats()
            batched = run_path(loaded, spec, units, batch_size=args.batch_size, stub=args.stub)
            memory_report = None
            if spec.requires_memory_preflight:
                if args.stub:
                    # Cannot measure real GPU memory under --stub; skipped, not
                    # force-failed, matching the residency/use_cache gate pattern
                    # elsewhere in this pipeline. The real run always measures this.
                    memory_report = {"skipped": True, "reason": "--stub", "passed": True}
                else:
                    mem_ok, mem_details = eg.memory_preflight_ok()
                    memory_report = {**mem_details, "passed": mem_ok}
        finally:
            eg.unload(loaded)

        comparisons = []
        for u in units:
            uid = _uid(spec.key, u)
            r1, rb = batch1[uid], batched[uid]
            tok_match = r1["generated_token_ids_sha256"] == rb["generated_token_ids_sha256"]
            text_match = r1["text"] == rb["text"]
            score1 = sp.parse_final_score(r1["text"])
            scoreb = sp.parse_final_score(rb["text"])
            score_match = (score1.score == scoreb.score) and (score1.ok == scoreb.ok)
            comparisons.append({
                "unit_id": uid, "dataset": u["task"]["dataset"],
                "task_id": u["task"]["task_id"], "condition": u["condition"].name,
                "token_ids_match": tok_match, "text_match": text_match,
                "score_match": score_match,
                "batch1_token_sha256": r1["generated_token_ids_sha256"],
                "batched_token_sha256": rb["generated_token_ids_sha256"],
            })

        n_mismatches = sum(1 for c in comparisons if not c["token_ids_match"])
        token_equivalence_passed = n_mismatches == 0
        memory_preflight_passed = memory_report["passed"] if memory_report is not None else True
        # Amendment A2 batching / Clarification C1_3: for a scorer requiring it, BOTH
        # must pass. For the other three scorers memory_preflight_passed defaults to
        # True (unchanged A1 behavior: token equivalence alone governs).
        overall_passed = token_equivalence_passed and memory_preflight_passed
        per_scorer_results[spec.key] = {
            "n_units": len(comparisons), "n_token_mismatches": n_mismatches,
            "n_text_mismatches": sum(1 for c in comparisons if not c["text_match"]),
            "n_score_mismatches": sum(1 for c in comparisons if not c["score_match"]),
            "requires_memory_preflight": spec.requires_memory_preflight,
            "memory_preflight": memory_report,
            "token_equivalence_passed": token_equivalence_passed,
            "memory_preflight_passed": memory_preflight_passed,
            "passed": overall_passed,
            "comparisons": comparisons,
        }
        extra = "" if not spec.requires_memory_preflight else (
            f" | memory preflight: {'PASS' if memory_preflight_passed else 'FAIL'}")
        print(f"[{spec.key}] {len(comparisons) - n_mismatches}/{len(comparisons)} "
             f"token-ID matches{extra} -- "
             f"{'PASS: batching permitted' if overall_passed else 'FAIL: forced to batch size 1 for the whole study'}")

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stub": args.stub, "batch_size_tested": args.batch_size,
        "n_tasks": len(tasks), "n_conditions": len(sc.CONDITIONS), "n_scorers": len(SCORERS),
        "n_units": len(units), "n_calls_total": len(units) * len(SCORERS) * 2,
        "equivalence_criterion": "sha256 of the generated token-ID sequence "
                                 "(trimmed to first EOS) identical between batch-1 and "
                                 "batched paths",
        "per_scorer": per_scorer_results,
    }
    with open(out_dir / "batching_equivalence_smoke_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # `stub` is recorded PER SCORER, not just in the sibling report: run_final_scoring.py
    # reads only this verdict file, and without the flag it could not distinguish a
    # measured verdict from a --stub one that generated no real tokens and touched no GPU.
    verdict = {k: {"passed": v["passed"], "n_units_tested": v["n_units"],
                  "n_mismatches": v["n_token_mismatches"],
                  "token_equivalence_passed": v["token_equivalence_passed"],
                  "memory_preflight_required": v["requires_memory_preflight"],
                  "memory_preflight_passed": v["memory_preflight_passed"],
                  "stub": bool(args.stub)}
              for k, v in per_scorer_results.items()}
    with open(out_dir / "batching_equivalence_verdict.json", "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)

    n_total_calls = len(units) * len(SCORERS) * 2
    assert n_total_calls == 288, f"expected 288 total calls, computed {n_total_calls}"

    print(f"\n[save] {out_dir / 'batching_equivalence_smoke_report.json'}")
    print(f"[save] {out_dir / 'batching_equivalence_verdict.json'}")
    all_passed = all(v["passed"] for v in verdict.values())
    print(f"\nOVERALL: {'ALL SCORERS may batch' if all_passed else 'SOME scorers forced to batch size 1 (see verdict file)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
