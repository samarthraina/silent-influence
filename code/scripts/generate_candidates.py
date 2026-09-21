#!/usr/bin/env python3
"""Generate the frozen candidate answers (Model X).

One answer per task, generated once, then treated as immutable experimental input: every
judge under every prior-context condition scores byte-identical text.

    python scripts/generate_candidates.py --config configs/screen_candidates.yaml --dry-run
    python scripts/generate_candidates.py --config configs/screen_candidates.yaml --limit 5
    python scripts/generate_candidates.py --config configs/screen_candidates.yaml

Writes two files:
  <out_dir>/generation_records.jsonl  one line per task, full metadata + raw output
  <candidates_out>.json               the frozen set, in the schema candidates.py reads

Resumable: a task already recorded is skipped. Re-running with nothing left to generate
still rebuilds the frozen set, so exclusions and the truncation gate can be re-applied
without regenerating anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from _bootstrap import REPO, load_merged_config

from silent_influence import backends, candidate_gen
from silent_influence import datasets as dm
from silent_influence.records import RecordWriter, load_records, write_manifest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _generate(todo, backend, spec, params, seed, run_id, gen_cfg, rec_path, identity):
    """Generate and persist one record per task. Records are written as they complete."""
    with RecordWriter(rec_path) as w:
        for i, row in enumerate(todo, 1):
            msgs = candidate_gen.build_answer_messages(row.text)
            raw_out, err, tb = None, None, None
            t1 = time.time()
            try:
                raw_out = backend.generate(msgs[0]["content"], msgs[1]["content"],
                                           params, seed)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                tb = traceback.format_exc(limit=6)
            dur = time.time() - t1

            text = (raw_out or "").strip()
            ntok = backend.last_new_tokens          # true generated length
            hit_cap = bool(backend.last_hit_cap)
            ntok_text = None
            try:
                ntok_text = len(backend.tokenizer.encode(raw_out or "",
                                                         add_special_tokens=False))
            except Exception:
                pass

            w.write({
                "run_id": run_id,
                "timestamp": _now(),
                "dataset": row.dataset,
                "prompt_id": row.prompt_id,
                "subcategory": row.category,
                "question": row.text,
                "candidate_response_id": gen_cfg["candidate_response_id"],
                "evaluated_model": gen_cfg["evaluated_model_label"],
                "generation_messages": msgs,
                "chat_template_kwargs": dict(spec.chat_template_kwargs),
                "generation_params": params.as_dict(),
                "seed": seed,
                "raw_output": raw_out,
                "candidate_text": text,
                "candidate_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "output_tokens": ntok,
                "output_tokens_reencoded": ntok_text,
                "prompt_tokens": backend.last_prompt_tokens,
                "hit_token_cap": hit_cap,
                "generation_error": err,
                "generation_traceback": tb,
                "generation_seconds": round(dur, 3),
                "model_identity": identity,
            })
            flag = " TRUNCATED" if hit_cap else ""
            print(f"  [{i}/{len(todo)}] {row.dataset}/{row.prompt_id} "
                  f"({row.category}) {ntok} tok in {dur:.1f}s{flag}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="generate a nested stratified subset of N tasks (staged "
                         "validation); the sampler is nested, so the subset stays "
                         "balanced and is contained in the full set.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    cfg = load_merged_config(args.config)
    gen_cfg = cfg["candidate_generation"]
    run_id = gen_cfg["name"]
    out_dir = Path(args.out or (REPO / gen_cfg["out_dir"]))
    seed = int(gen_cfg.get("seed", 42))

    known = set(backends.ModelSpec.__dataclass_fields__) - {"extra"}
    raw = dict(cfg["models"][gen_cfg["model"]])
    raw.setdefault("key", gen_cfg["model"])
    spec = backends.ModelSpec(**{k: v for k, v in raw.items() if k in known},
                              extra={k: v for k, v in raw.items() if k not in known})
    params = backends.GenParams(**cfg["generation"])

    # n_prompts applies per dataset, so a multi-dataset screen stays balanced.
    ds_names = gen_cfg.get("datasets") or [gen_cfg["dataset"]]
    rows = []
    for ds_name in ds_names:
        all_rows = dm.load_dataset(ds_name, cfg["datasets"][ds_name], REPO)
        strat = cfg["datasets"][ds_name].get("stratify", True)
        full = dm.sample(all_rows, gen_cfg.get("n_prompts"), seed, stratify=strat)
        picked = full
        if args.limit is not None:
            picked = dm.sample(all_rows, args.limit, seed, stratify=strat)
            assert {r.prompt_id for r in picked} <= {r.prompt_id for r in full}, \
                "staged subset is not contained in the full task set"
        rows.extend(picked)

    print(f"config      : {cfg['_config_path']}")
    print(f"run_id      : {run_id}")
    print(f"model X     : {spec.hf_id}  rev={spec.revision}")
    for d in ds_names:
        sub = [r for r in rows if r.dataset == d]
        print(f"dataset     : {d} | tasks: {len(sub)} "
              f"({', '.join(sorted({r.category or '?' for r in sub}))})")
        print(f"  prompt_ids: {[r.prompt_id for r in sub]}")
    print(f"generation  : {params.as_dict()}")
    print(f"chat kwargs : {spec.chat_template_kwargs}")
    print(f"out         : {out_dir}")

    print("\n--- answer-generation messages ---")
    for m in candidate_gen.build_answer_messages("<TASK>"):
        print(f"  [{m['role']}] {m['content']}")

    if args.dry_run:
        print("\n[dry-run] nothing generated.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "generation_records.jsonl"
    done = set()
    if not args.no_resume:
        done = {(r["dataset"], r["prompt_id"]) for r in load_records(rec_path)
                if r.get("run_id") == run_id}
    todo = [r for r in rows if (r.dataset, r.prompt_id) not in done]
    print(f"\n[plan] {len(rows)} tasks | {len(done)} already generated | "
          f"{len(todo)} to run")

    t0 = time.time()
    if todo:
        backend = backends.build(spec)
        identity = backend.identity()
        try:
            _generate(todo, backend, spec, params, seed, run_id, gen_cfg,
                      rec_path, identity)
        finally:
            backend.close()
    else:
        print("[skip] no new generations needed; rebuilding the frozen set "
              "from existing records.")
        identity = next((r["model_identity"] for r in load_records(rec_path)
                         if r.get("run_id") == run_id and r.get("model_identity")), None)

    # Records for datasets no longer in this config stay on disk as audit evidence but
    # are not frozen: the frozen set contains exactly what the config asks for.
    recs_run = [r for r in load_records(rec_path) if r.get("run_id") == run_id]
    recs_all = [r for r in recs_run if r["dataset"] in set(ds_names)]
    parked = len(recs_run) - len(recs_all)
    if parked:
        print(f"\n[parked] {parked} record(s) from datasets outside this config kept on "
              f"disk but not frozen: "
              f"{sorted({r['dataset'] for r in recs_run} - set(ds_names))}")
    n_ok = sum(1 for r in recs_all if not r.get("generation_error"))
    n_err = sum(1 for r in recs_all if r.get("generation_error"))

    # Explicit, recorded exclusions. The generation record is kept either way; only the
    # frozen set drops the task, and the reason travels with the artifact.
    excl_cfg = gen_cfg.get("exclude_prompts") or []
    excluded = {(e["dataset"], str(e["prompt_id"])): e.get("reason", "")
                for e in excl_cfg}
    recs_eligible = [r for r in recs_all
                     if (r["dataset"], str(r["prompt_id"])) not in excluded]
    if excluded:
        print(f"\n[exclude] {len(excluded)} task(s) removed from the frozen set:")
        for (d, pid), why in excluded.items():
            print(f"    {d}/{pid}: {why}")

    # A capped generation is a defective stimulus. Refuse to freeze the set rather than
    # accept it or quietly special-case the offending item.
    capped = [r for r in recs_eligible if r.get("hit_token_cap")]
    if capped:
        print(f"\n{'!' * 70}")
        print(f"REFUSING TO FREEZE: {len(capped)} candidate(s) hit the "
              f"{params.max_new_tokens}-token cap and are truncated:")
        for r in capped:
            print(f"  {r['dataset']}/{r['prompt_id']} ({r.get('subcategory')}) "
                  f"{r['output_tokens']} tokens, ends: ...{r['candidate_text'][-60:]!r}")
        print("Raise max_new_tokens for the whole set and regenerate, or drop the task.")
        print("Records are kept; no candidates file was written.")
        print(f"{'!' * 70}")
        return 1

    recs_eligible.sort(key=lambda r: (r["dataset"],
                                      int(r["prompt_id"])
                                      if str(r["prompt_id"]).isdigit() else 0,
                                      str(r["prompt_id"])))
    cands = [candidate_gen.candidate_record(
                dataset=r["dataset"], prompt_id=r["prompt_id"],
                candidate_response_id=r["candidate_response_id"],
                evaluated_model=r["evaluated_model"], text=r["candidate_text"])
             | {"text_sha256": r["candidate_text_sha256"],
                "subcategory": r.get("subcategory"),
                "output_tokens": r.get("output_tokens"),
                "hit_token_cap": r.get("hit_token_cap")}
             for r in recs_eligible
             if not r.get("generation_error") and r["candidate_text"]]

    payload = {
        "run_id": run_id,
        "generated_at": _now(),
        "model_x": identity,
        "generation_params": params.as_dict(),
        "chat_template_kwargs": dict(spec.chat_template_kwargs),
        "answer_system_prompt": candidate_gen.ANSWER_SYSTEM_PROMPT,
        "answer_instruction": candidate_gen.ANSWER_INSTRUCTION,
        "datasets": ds_names,
        "seed": seed,
        "n_candidates": len(cands),
        "excluded_prompts": excl_cfg,
        "immutable": True,
        "subset_label": gen_cfg.get("subset_label"),
        "note": "Frozen experimental input. Every judge scores byte-identical text.",
        "candidates": cands,
    }
    cand_path = REPO / gen_cfg["candidates_out"]
    cand_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cand_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    write_manifest(out_dir / f"manifest_{run_id}.json",
                   {"run_id": run_id, "timestamp": _now(),
                    "model_identity": identity, "generation_params": params.as_dict(),
                    "n_ok": n_ok, "n_errors": n_err,
                    "excluded_prompts": excl_cfg,
                    "wall_seconds": round(time.time() - t0, 2),
                    "candidates_path": str(cand_path), "config": cfg})
    print(f"\n[done] {n_ok} ok, {n_err} errors")
    print(f"[save] {rec_path}")
    print(f"[save] {cand_path}  ({len(cands)} frozen candidates)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
