#!/usr/bin/env python3
"""Score the frozen candidate answers: 3 scorers x 90 tasks x 6 conditions.

Independent, stateless calls (no conversation state carried between conditions or
scorers) -- each unit is a single-message ([user]) generation, no system prompt, exact
wording verified byte-for-byte against the pilot (scripts/validate_parser_against_pilot.py).
Uses silent_influence.exact_generation for the model-input path itself (chat-template call
shape, seeding, decode settings) -- verified against SSI_vs_SI.ipynb's "HELD-OUT MT-BENCH
SILENT CONTEXT EXPERIMENT" cell, not assumed. In particular all four models, Gemma
included, load with attn_implementation="sdpa" here: the existing mechanistic backend's
"eager" override for Gemma's attention softcap is specific to that protocol and does not
apply to this direct scale-up of the pilot.

Sequential model loading: one scorer's weights are loaded, all of that scorer's units are
run, the model is released, then the next scorer loads -- so the whole grid fits on one GPU
at a time. Every call is written to JSONL immediately (append + fsync via RecordWriter);
resuming a killed run skips every unit already present by unit_id and never regenerates it.

    python scripts/run_scaled_scoring.py --dry-run
    python scripts/run_scaled_scoring.py \
        --candidates-file data/candidates/scaled_olmo_answers.json \
        --out results/scaled_silent_influence
    python scripts/run_scaled_scoring.py \
        --candidates-file data/candidates/smoke_olmo_answers.json \
        --out results/scaled_silent_influence_smoke
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import exact_generation as eg
from silent_influence import scaled_conditions as sc
from silent_influence import scaled_parsing as sp
from silent_influence.environment import capture_environment
from silent_influence.logging_utils import make_logger
from silent_influence.records import RecordWriter, load_completed, write_manifest

SCORERS = [
    eg.ExactModelSpec(key="llama", hf_id="meta-llama/Llama-3.1-8B-Instruct",
                      revision="0e9e39f249a16976918f6564b8830bc894c89659"),
    eg.ExactModelSpec(key="qwen", hf_id="Qwen/Qwen3-8B",
                      revision="b968826d9c46dd6066d109eabc6255188de91218",
                      disable_thinking=True),
    eg.ExactModelSpec(key="gemma", hf_id="google/gemma-2-9b-it",
                      revision="11c9b309abf73637e4b6f9a3fa1e92e615547819"),
]
MAX_NEW_TOKENS = 512
SCORE_SEED = 42


def unit_id(scorer_key: str, dataset: str, slot_task_id: str, condition: str) -> str:
    return f"{scorer_key}__{dataset}__{slot_task_id}__{condition}"


def load_candidates(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["accepted"]


def build_units(candidates: list) -> list:
    units = []
    for cand in candidates:
        for cond in sc.CONDITIONS:
            units.append({"candidate": cand, "condition": cond})
    return units


def fmt_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}h{m:02d}m{s:02d}s" if h else f"{m:d}m{s:02d}s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates-file",
                    default=str(REPO / "data/candidates/scaled_olmo_answers.json"))
    ap.add_argument("--out", default=str(REPO / "results/scaled_silent_influence"))
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N remaining units per scorer (dev use)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--stub", action="store_true",
                    help="use the deterministic no-GPU stub to test plumbing "
                         "(resume/idempotency/progress) only; never a source of "
                         "experimental data")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = make_logger(out_dir / "run.log")
    if not args.stub:
        eg.check_transformers_version(log)

    candidates = load_candidates(Path(args.candidates_file))
    units = build_units(candidates)
    n_per_scorer = len(units)
    total_units = n_per_scorer * len(SCORERS)
    log(f"[plan] {len(candidates)} candidates x {len(sc.CONDITIONS)} conditions "
       f"x {len(SCORERS)} scorers = {total_units} calls")

    if args.dry_run:
        u = units[0]
        prompt = sc.render_prompt(u["candidate"]["question"], u["candidate"]["answer"],
                                  u["condition"])
        log(f"[dry-run] example unit_id: {unit_id(SCORERS[0].key, u['candidate']['dataset'], u['candidate']['slot_task_id'], u['condition'].name)}")
        log(f"[dry-run] example prompt:\n{prompt}")
        log("[dry-run] nothing scored.")
        return 0

    records_path = out_dir / "raw_results.jsonl"
    done = load_completed(records_path) if not args.no_resume else set()
    log(f"[resume] {len(done)} units already complete")

    todo_by_scorer = {}
    for scorer_spec in SCORERS:
        scorer_units = [u for u in units
                       if unit_id(scorer_spec.key, u["candidate"]["dataset"],
                                 u["candidate"]["slot_task_id"], u["condition"].name)
                       not in done]
        if args.limit is not None:
            scorer_units = scorer_units[:args.limit]
        todo_by_scorer[scorer_spec.key] = scorer_units
    n_total_todo = sum(len(v) for v in todo_by_scorer.values())

    t0 = time.time()
    n_done_this_run = 0
    stats_by_status = {}
    hf_token = os.environ.get("HF_TOKEN")

    with RecordWriter(records_path) as writer:
        for scorer_spec in SCORERS:
            scorer_units = todo_by_scorer[scorer_spec.key]
            if not scorer_units:
                log(f"[model] {scorer_spec.key}: nothing to do, skipping load")
                continue

            log(f"[model] loading {scorer_spec.key} ({scorer_spec.hf_id}) "
               f"for {len(scorer_units)} units")
            loaded = (eg.load_stub_model(scorer_spec) if args.stub
                     else eg.load_exact_model(scorer_spec, hf_token=hf_token))
            log(f"[model] loaded attn={loaded.attn_implementation} "
               f"transformers={loaded.transformers_version} "
               f"chat_template_sha256={loaded.chat_template_sha256}")
            try:
                for i, u in enumerate(scorer_units, 1):
                    cand, cond = u["candidate"], u["condition"]
                    uid = unit_id(scorer_spec.key, cand["dataset"], cand["slot_task_id"],
                                  cond.name)
                    prompt = sc.render_prompt(cand["question"], cand["answer"], cond)
                    messages = [{"role": "user", "content": prompt}]

                    err = None
                    gen_fn = eg.generate_exact_stub if args.stub else eg.generate_exact
                    try:
                        result = gen_fn(loaded, messages, max_new_tokens=MAX_NEW_TOKENS,
                                        seed=SCORE_SEED)
                        raw = result["text"]
                    except Exception as e:
                        err = f"{type(e).__name__}: {e}"
                        raw = None
                        result = {"generation_seconds": 0.0, "prompt_tokens": None,
                                  "first_input_token_id": None, "last_input_token_id": None}

                    pr = sp.parse_final_score(raw) if err is None else sp.ParseResult(
                        sp.EMPTY_OUTPUT, flagged_for_review=True, error=err)

                    rec = {
                        "unit_id": uid,
                        "dataset": cand["dataset"], "slot_task_id": cand["slot_task_id"],
                        "generated_task_id": cand["generated_task_id"],
                        "is_substitution": cand["is_substitution"],
                        "category": cand["category"], "question": cand["question"],
                        "candidate_answer": cand["answer"],
                        "candidate_answer_sha256": cand["answer_sha256"],
                        "generator_model": cand["generator_model"],
                        "generator_revision": cand["generator_revision"],
                        "scorer_key": scorer_spec.key, "scorer_model_id": scorer_spec.hf_id,
                        "scorer_revision": scorer_spec.revision,
                        "condition": cond.name, "added_context": cond.added_context,
                        "prompt": prompt, "response": raw,
                        "parse_status": pr.status, "parse_tier": pr.tier,
                        "parsed_score": pr.score, "parse_ok": pr.ok,
                        "flagged_for_review": pr.flagged_for_review,
                        "parse_error": pr.error,
                        "generation_error": err,
                        "generation_params": {"do_sample": False,
                                              "max_new_tokens": MAX_NEW_TOKENS,
                                              "pad_token_id": "tokenizer.eos_token_id"},
                        "seed": SCORE_SEED,
                        "prompt_tokens": result.get("prompt_tokens"),
                        "first_input_token_id": result.get("first_input_token_id"),
                        "last_input_token_id": result.get("last_input_token_id"),
                        "attn_implementation": loaded.attn_implementation,
                        "transformers_version": loaded.transformers_version,
                        "generation_seconds": round(result["generation_seconds"], 3),
                        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    }
                    writer.write(rec)
                    n_done_this_run += 1
                    stats_by_status[pr.status] = stats_by_status.get(pr.status, 0) + 1

                    if i % 20 == 0 or i == len(scorer_units):
                        elapsed = time.time() - t0
                        rate = elapsed / n_done_this_run
                        eta = rate * (n_total_todo - n_done_this_run)
                        log(f"  [{scorer_spec.key}] {i}/{len(scorer_units)} "
                           f"(run total {n_done_this_run}/{n_total_todo}) "
                           f"elapsed={fmt_eta(elapsed)} avg={rate:.2f}s/call "
                           f"eta_remaining={fmt_eta(eta)}")
            finally:
                eg.unload(loaded)

    env = capture_environment()
    with open(out_dir / "environment.json", "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)

    write_manifest(out_dir / "manifest_scoring.json", {
        "records_path": str(records_path),
        "n_candidates": len(candidates), "n_conditions": len(sc.CONDITIONS),
        "n_scorers": len(SCORERS), "n_units_total": total_units,
        "n_done_this_run": n_done_this_run,
        "n_already_done_before_this_run": len(done),
        "generation_params": {"do_sample": False, "max_new_tokens": MAX_NEW_TOKENS},
        "seed": SCORE_SEED,
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
