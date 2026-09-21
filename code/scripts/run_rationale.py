#!/usr/bin/env python3
"""Phase 1B — post-decision rationale continuations.

Replays each completed judging exchange verbatim and appends one neutral follow-up turn.
The behavioural score is already committed in the replayed assistant turn, so it cannot
change here; the script verifies that and records any violation rather than hiding it.

    python scripts/run_rationale.py --config configs/rationale_arenahard.yaml --limit 6
    python scripts/run_rationale.py --config configs/rationale_arenahard.yaml
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO, load_merged_config

from silent_influence import backends, parsing, rationale
from silent_influence.records import RecordWriter, load_records, write_manifest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--limit", type=int, default=None,
                    help="sanity-check subset: first N units in deterministic order")
    ap.add_argument("--judge", default=None,
                    help="run only this judge (one process per GPU); the record set is "
                         "identical either way, only the scheduling differs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    cfg = load_merged_config(args.config)
    rc = cfg["rationale"]
    run_id = rc["name"]
    out_dir = REPO / rc["out_dir"]
    params = backends.GenParams(**cfg["generation"])
    conds = rc["conditions"]
    judges = [args.judge] if args.judge else rc["judge_models"]

    src = [json.loads(l) for f in sorted(glob.glob(str(REPO / rc["source_glob"])))
           for l in open(f, encoding="utf-8")]
    units = [r for r in src
             if r["judge_model"] in judges
             and r["prior_context_condition"] in conds
             and r["parse_status"] == "ok"]
    # deterministic order: task, judge, condition
    corder = {c: i for i, c in enumerate(conds)}
    units.sort(key=lambda r: (int(r["prompt_id"]) if str(r["prompt_id"]).isdigit() else 0,
                              str(r["prompt_id"]), r["judge_model"],
                              corder[r["prior_context_condition"]]))
    if args.limit is not None:
        keep = sorted({(int(u["prompt_id"]) if str(u["prompt_id"]).isdigit() else 0,
                        str(u["prompt_id"])) for u in units})[:rc.get("sanity_tasks", 2)]
        keep = {k[1] for k in keep}
        units = [u for u in units if u["prompt_id"] in keep]

    print(f"config    : {cfg['_config_path']}")
    print(f"run_id    : {run_id}")
    print(f"source    : {rc['source_glob']}  ({len(src)} behavioural records)")
    print(f"judges    : {judges}")
    print(f"conditions: {conds}")
    print(f"units     : {len(units)}")
    print(f"generation: {params.as_dict()}")
    print(f"\nfollow-up turn (verbatim):\n  {rationale.FOLLOWUP!r}")
    if args.dry_run:
        print("\n[dry-run] nothing generated.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "rationale_records.jsonl"
    done = set()
    if not args.no_resume:
        done = {r["rationale_unit_id"] for r in load_records(rec_path)
                if r.get("run_id") == run_id}

    by_judge = {}
    for u in units:
        rid = hashlib.sha256(f"{run_id}|{u['unit_id']}".encode()).hexdigest()[:32]
        if rid in done:
            continue
        by_judge.setdefault(u["judge_model"], []).append((rid, u))
    todo = sum(len(v) for v in by_judge.values())
    print(f"\n[plan] {len(units)} units | {len(done)} already done | {todo} to run")
    if not todo:
        print("[done] nothing to do.")
        return 0

    known = set(backends.ModelSpec.__dataclass_fields__) - {"extra"}
    t0 = time.time()
    n_ok = n_changed = n_bad = 0
    with RecordWriter(rec_path) as w:
        for jkey, items in by_judge.items():
            raw = dict(cfg["models"][jkey]); raw.setdefault("key", jkey)
            spec = backends.ModelSpec(**{k: v for k, v in raw.items() if k in known},
                                      extra={k: v for k, v in raw.items()
                                             if k not in known})
            print(f"[model] {jkey} ({spec.hf_id}) for {len(items)} units")
            be = backends.build(spec); ident = be.identity()
            try:
                for i, (rid, u) in enumerate(items, 1):
                    msgs = rationale.build_messages(u)
                    text, err, tb = None, None, None
                    t1 = time.time()
                    try:
                        text = be.generate_messages(msgs, params, u["seed"])
                    except Exception as e:
                        err = f"{type(e).__name__}: {e}"
                        tb = traceback.format_exc(limit=6)
                    dur = time.time() - t1

                    # The score is committed in the replayed turn. If the rationale
                    # nonetheless emits a different score, that is recorded, not hidden.
                    revised = parsing.parse(text or "", wants_justification=False)
                    changed = bool(revised.ok and revised.total is not None
                                   and abs(revised.total - u["total"]) > 1e-9)
                    n_changed += changed
                    rstat, rtext, rdetail = rationale.extract_rationale(
                        text, bool(be.last_hit_cap))
                    n_bad += (rstat != rationale.R_OK)

                    w.write({
                        "rationale_unit_id": rid,
                        "run_id": run_id,
                        "timestamp": _now(),
                        "dataset": u["dataset"],
                        "prompt_id": u["prompt_id"],
                        "candidate_response_id": u["candidate_response_id"],
                        "judge_model": u["judge_model"],
                        "evaluated_model": u["evaluated_model"],
                        "prior_context_condition": u["prior_context_condition"],
                        "prior_score_value": u["prior_score_value"],
                        "rubric_variant": u["rubric_variant"],
                        "output_protocol": u["output_protocol"],
                        "history_template": u["history_template"],
                        "replicate": u["replicate"],
                        "seed": u["seed"],
                        "frozen_score": rationale.frozen_score(u),
                        "followup_text": rationale.FOLLOWUP,
                        "rationale_messages": msgs,
                        "rationale_raw": text,
                        "rationale_status": rstat,
                        "rationale_detail": rdetail,
                        "rationale_text": rtext,
                        "rationale_tokens": be.last_new_tokens,
                        "rationale_hit_cap": be.last_hit_cap,
                        "score_appears_revised": changed,
                        "revised_parse": {"status": revised.status,
                                          "total": revised.total},
                        "generation_error": err,
                        "generation_traceback": tb,
                        "generation_seconds": round(dur, 3),
                        "generation_params": params.as_dict(),
                        "model_identity": ident,
                    })
                    if not err:
                        n_ok += 1
                    flag = ("  SCORE-REVISED" if changed else
                            ("  " + rstat.upper() if rstat != rationale.R_OK else ""))
                    cap = " HIT-CAP" if be.last_hit_cap else ""
                    print(f"  [{i}/{len(items)}] {u['prompt_id']}/"
                          f"{u['prior_context_condition']} "
                          f"{be.last_new_tokens} tok {dur:.1f}s{cap}{flag}", flush=True)
            finally:
                be.close()

    write_manifest(out_dir / f"manifest_{run_id}.json",
                   {"run_id": run_id, "timestamp": _now(),
                    "followup_text": rationale.FOLLOWUP,
                    "generation_params": params.as_dict(),
                    "n_units": len(units), "n_ok": n_ok,
                    "n_score_appears_revised": n_changed,
                    "n_unusable_rationale": n_bad,
                    "wall_seconds": round(time.time() - t0, 2), "config": cfg})
    print(f"\n[done] {n_ok} ok | score-revision flags: {n_changed} | "
          f"{time.time()-t0:.1f}s")
    print(f"[save] {rec_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
