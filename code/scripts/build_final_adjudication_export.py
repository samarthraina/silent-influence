#!/usr/bin/env python3
"""Build the blinded manual-review export for the two independent verifiers (Amendment A1
E6: "verifier_1"/"verifier_2" -- identities recorded only in
Code/research_notes/final_analysis_plan_amendment_A1.md, outside the pushable repo, for
anonymity during review; this script and the repo config never name them).

Reads score_recovery_pattern_pass.json (from audit_final_score_recovery.py) and takes only
the entries with status "needs_manual_review" -- responses no safe general pattern could
resolve. For each, assigns an opaque review_id and writes it into TWO files:

  - review_queue_blinded.json: review_id -> response TEXT ONLY. This is what a verifier
    reads. It deliberately omits unit_id, scorer_key, dataset, condition, and any other
    field that could reveal the experimental condition or let a reader infer an
    aggregate -- per plan v2's blinded_review.forbidden_during_adjudication.
  - review_id_map_PRIVATE.json: review_id -> unit_id. Kept out of the blinded file so a
    verifier's read is never anchored to which condition or scorer produced the text.
    NOT for the verifiers; used only by merge_final_verifier_passes.py after both blinded
    passes are complete.

Each verifier fills in their own copy (verifier_1_pass.json / verifier_2_pass.json:
review_id -> {"score": <float or null>, "evidence": "<quoted phrase>"}) independently,
without seeing the other's values or this script's internals -- then
merge_final_verifier_passes.py combines them, requiring agreement.

    python scripts/build_final_adjudication_export.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

PATTERN_PASS = REPO / "results/final_behavioral_study/score_recovery_pattern_pass.json"
OUT_DIR = REPO / "results/final_behavioral_study"


def review_id_for(unit_id: str) -> str:
    return "rev_" + hashlib.sha256(unit_id.encode()).hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pattern-pass", default=None, help=f"default: {PATTERN_PASS}")
    ap.add_argument("--out-dir", default=None, help=f"default: {OUT_DIR}")
    args = ap.parse_args()
    pattern_pass_path = Path(args.pattern_pass) if args.pattern_pass else PATTERN_PASS
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR

    if not pattern_pass_path.exists():
        raise SystemExit(f"{pattern_pass_path} does not exist yet -- run "
                         f"scripts/audit_final_score_recovery.py first")
    with open(pattern_pass_path, encoding="utf-8") as f:
        pattern_pass = json.load(f)

    queue = [e for e in pattern_pass["entries"] if e["status"] == "needs_manual_review"]

    blinded = {}
    private_map = {}
    for e in queue:
        rid = review_id_for(e["unit_id"])
        blinded[rid] = {"response": e["response"]}
        private_map[rid] = e["unit_id"]

    out_dir.mkdir(parents=True, exist_ok=True)
    blinded_path = out_dir / "review_queue_blinded.json"
    with open(blinded_path, "w", encoding="utf-8") as f:
        json.dump({"created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "n_items": len(blinded),
                  "instructions": ("For each review_id, read the response text only. If "
                                   "it states an explicit final score (a score-meaning "
                                   "label or verdict verb, adjacent to an explicit /10 or "
                                   "'out of 10'), record that score and the exact quoted "
                                   "phrase that justifies it. If no explicit score is "
                                   "stated, record score=null. Do not guess, do not use "
                                   "component/criterion scores, do not use an unlabeled "
                                   "bare number."),
                  "items": blinded}, f, ensure_ascii=False, indent=2)

    private_path = out_dir / "review_id_map_PRIVATE.json"
    with open(private_path, "w", encoding="utf-8") as f:
        json.dump(private_map, f, ensure_ascii=False, indent=2)

    for who in ("verifier_1", "verifier_2"):
        template_path = out_dir / f"{who}_pass_TEMPLATE.json"
        with open(template_path, "w", encoding="utf-8") as f:
            json.dump({rid: {"score": None, "evidence": None} for rid in blinded},
                     f, ensure_ascii=False, indent=2)

    print(f"n_items queued for blinded manual review: {len(blinded)}")
    print(f"[save] {blinded_path}  (give this to both verifiers)")
    print(f"[save] {private_path}  (KEEP PRIVATE; used only by merge_final_verifier_passes.py)")
    print(f"[save] {out_dir / 'verifier_1_pass_TEMPLATE.json'}")
    print(f"[save] {out_dir / 'verifier_2_pass_TEMPLATE.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
