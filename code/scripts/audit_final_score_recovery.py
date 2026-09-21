#!/usr/bin/env python3
"""Score-recovery audit for the final study's unparsed responses. Read-only against
results/final_behavioral_study/raw_results.jsonl (never modified, never regenerated).
Runs the automatic pattern pass (silent_influence.final_score_recovery.recover_score) over
every parse_ok=False record and writes a single report separating three buckets:
recovered_pattern (accepted, evidence = the matched phrase), recovered_manual (already in
MANUAL_OVERRIDES from a completed prior review), and needs_manual_review (queued for the
blinded two-reader process -- see build_final_adjudication_export.py).

Never an unrestricted bare-number fallback; never a number lifted from the rationale;
never a component/criterion score presented as the verdict -- see
final_score_recovery.py's module docstring for the full rule set, unchanged from the
frozen score_recovery.py mechanism.

    python scripts/audit_final_score_recovery.py
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import output_validity as ov
from silent_influence import final_score_recovery as fsr

RAW_RESULTS = REPO / "results/final_behavioral_study/raw_results.jsonl"
OUT = REPO / "results/final_behavioral_study/score_recovery_pattern_pass.json"


def main() -> int:
    # argparse even though the defaults are almost always right: without it an unknown or
    # mistyped flag would be silently ignored and the script would run against the wrong
    # paths. Defaults resolve from the module globals at call time so tests can still
    # monkeypatch RAW_RESULTS/OUT.
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--records", default=None, help=f"default: {RAW_RESULTS}")
    ap.add_argument("--out", default=None, help=f"default: {OUT}")
    args = ap.parse_args()
    raw_results = Path(args.records) if args.records else RAW_RESULTS
    out_path = Path(args.out) if args.out else OUT

    if not raw_results.exists():
        raise SystemExit(f"{raw_results} does not exist yet -- run the scoring pipeline "
                         f"first (scripts/run_final_scoring.py)")

    records = []
    with open(raw_results, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    # Amendment A5 points 4 and 5: uncapped parser failures still go to the frozen
    # two-reader recovery process; capped-incomplete responses never do, because an
    # explicitly final score cannot be inferred from an unfinished generation -- there
    # is no score in the text to recover. They are counted and reported instead.
    failures = [r for r in records
                if not r["parse_ok"] and ov.eligible_for_human_recovery(r)]
    capped_excluded = [r for r in records if ov.is_capped_incomplete(r)]

    entries = []
    n_pattern = n_manual = n_needs_review = n_unresolved = 0
    for r in failures:
        result = fsr.recover_score(r["unit_id"], r["response"])
        entry = {
            "unit_id": r["unit_id"], "scorer_key": r["scorer_key"], "dataset": r["dataset"],
            "source_task_id": r["source_task_id"], "condition": r["condition"],
            "status": result.status, "recovered_score": result.score,
            "method": result.method, "matched_text": result.matched_text,
            "note": result.note, "response": r["response"],
        }
        entries.append(entry)
        n_pattern += result.status == "recovered_pattern"
        n_manual += result.status == "recovered_manual"
        n_needs_review += result.status == "needs_manual_review"
        n_unresolved += result.status == "unresolved"

    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(raw_results),
        "note": ("raw_results.jsonl was NOT modified. Pattern-recovered scores are "
                "accepted with their matched phrase as evidence; entries with no safe "
                "general pattern are queued for the blinded two-reader manual process, "
                "not accepted here."),
        "n_failures_total": len(failures),
        "n_recovered_pattern": n_pattern, "n_recovered_manual": n_manual,
        "n_needs_manual_review": n_needs_review, "n_unresolved": n_unresolved,
        "n_capped_incomplete_excluded_from_recovery": len(capped_excluded),
        "capped_incomplete_unit_ids": [r["unit_id"] for r in capped_excluded],
        "entries": entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"failures examined      : {len(failures)}")
    print(f"recovered (pattern)    : {n_pattern}")
    print(f"recovered (manual)     : {n_manual}")
    print(f"needs manual review    : {n_needs_review}")
    print(f"unresolved             : {n_unresolved}")
    print(f"[save] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
