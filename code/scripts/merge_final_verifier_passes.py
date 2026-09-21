#!/usr/bin/env python3
"""Merge the two independent blinded verifier passes into the final adjudication file.

Per Amendment A1 E6 and plan v2 .measurement_and_adjudication.independent_verification:
agreement is required for every manually recovered score; on disagreement the response
remains unresolved -- never split the difference, never prefer one reader. "Agreement"
means both verifiers give the same score (including both giving null/no-score).

Combines with the pattern pass (score_recovery_pattern_pass.json) to produce
final_adjudication.json: the single frozen adjudication file for this study, covering
every response that failed the automatic parser -- pattern-recovered (evidence = matched
phrase), manually-recovered-and-agreed (evidence = both verifiers' quoted phrases), and
unresolved (no agreement, or no score stated by either verifier).

    python scripts/merge_final_verifier_passes.py
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

OUT_DIR = REPO / "results/final_behavioral_study"
PATTERN_PASS = OUT_DIR / "score_recovery_pattern_pass.json"
PRIVATE_MAP = OUT_DIR / "review_id_map_PRIVATE.json"
VERIFIER_1 = OUT_DIR / "verifier_1_pass.json"
VERIFIER_2 = OUT_DIR / "verifier_2_pass.json"
FINAL_OUT = OUT_DIR / "final_adjudication.json"


def _scores_agree(a: dict, b: dict) -> bool:
    sa, sb = a.get("score"), b.get("score")
    if sa is None and sb is None:
        return True
    if sa is None or sb is None:
        return False
    return float(sa) == float(sb)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pattern-pass", default=None, help=f"default: {PATTERN_PASS}")
    ap.add_argument("--private-map", default=None, help=f"default: {PRIVATE_MAP}")
    ap.add_argument("--verifier-1", default=None, help=f"default: {VERIFIER_1}")
    ap.add_argument("--verifier-2", default=None, help=f"default: {VERIFIER_2}")
    ap.add_argument("--out", default=None, help=f"default: {FINAL_OUT}")
    args = ap.parse_args()
    pattern_pass_path = Path(args.pattern_pass) if args.pattern_pass else PATTERN_PASS
    private_map_path = Path(args.private_map) if args.private_map else PRIVATE_MAP
    v1_path = Path(args.verifier_1) if args.verifier_1 else VERIFIER_1
    v2_path = Path(args.verifier_2) if args.verifier_2 else VERIFIER_2
    final_out = Path(args.out) if args.out else FINAL_OUT

    for p in (pattern_pass_path, private_map_path, v1_path, v2_path):
        if not p.exists():
            raise SystemExit(f"{p} does not exist yet -- complete the blinded review "
                             f"workflow first (build_final_adjudication_export.py, then "
                             f"both verifiers fill in their _pass.json from the "
                             f"_TEMPLATE.json files)")

    with open(pattern_pass_path, encoding="utf-8") as f:
        pattern_pass = json.load(f)
    with open(private_map_path, encoding="utf-8") as f:
        review_id_to_unit_id = json.load(f)
    with open(v1_path, encoding="utf-8") as f:
        v1 = json.load(f)
    with open(v2_path, encoding="utf-8") as f:
        v2 = json.load(f)

    entries = []
    n_pattern = n_manual_agreed = n_disagreement = n_missing_pass = 0
    for e in pattern_pass["entries"]:
        if e["status"] == "recovered_pattern":
            entries.append({**e, "final_status": "recovered_pattern",
                           "final_score": e["recovered_score"],
                           "evidence": e["matched_text"]})
            n_pattern += 1
            continue
        if e["status"] != "needs_manual_review":
            entries.append({**e, "final_status": e["status"], "final_score": e["recovered_score"],
                           "evidence": e.get("note")})
            continue

        rid = next((r for r, uid in review_id_to_unit_id.items() if uid == e["unit_id"]), None)
        p1 = v1.get(rid) if rid else None
        p2 = v2.get(rid) if rid else None
        if p1 is None or p2 is None or p1.get("score") is None and p1.get("evidence") is None \
                and p2.get("score") is None and p2.get("evidence") is None:
            entries.append({**e, "final_status": "unresolved", "final_score": None,
                           "evidence": "no completed independent verifier passes on file"})
            n_missing_pass += 1
            continue

        if _scores_agree(p1, p2) and p1.get("score") is not None:
            entries.append({**e, "final_status": "recovered_manual", "final_score": p1["score"],
                           "evidence": f"verifier_1: {p1.get('evidence')!r}; "
                                      f"verifier_2: {p2.get('evidence')!r} (agreed)"})
            n_manual_agreed += 1
        else:
            entries.append({**e, "final_status": "unresolved", "final_score": None,
                           "evidence": f"disagreement -- verifier_1={p1.get('score')} "
                                      f"verifier_2={p2.get('score')}; never split the "
                                      f"difference, never prefer a reader"})
            n_disagreement += 1

    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_entries": len(entries),
        "n_recovered_pattern": n_pattern,
        "n_recovered_manual_agreed": n_manual_agreed,
        "n_disagreement_unresolved": n_disagreement,
        "n_missing_verifier_pass_unresolved": n_missing_pass,
        "entries": entries,
    }
    final_out.parent.mkdir(parents=True, exist_ok=True)
    with open(final_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"pattern-recovered        : {n_pattern}")
    print(f"manual, both agreed      : {n_manual_agreed}")
    print(f"manual, disagreement     : {n_disagreement}")
    print(f"manual, pass missing     : {n_missing_pass}")
    print(f"[save] {final_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
