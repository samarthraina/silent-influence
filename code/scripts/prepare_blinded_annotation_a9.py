#!/usr/bin/env python3
"""Prepare (NOT submit) a blinded annotation dataset from the A9 scoring records.

Adapter only. The rubric, the blinding scheme and the item-id construction all come from the
existing scripts/build_annotation.py -- this script reshapes A9 records into the fields that
builder already expects, so the A/N/D/U + context_mentioned rubric is reused rather than
restated.

Read-only: records are read inside the checksum-verified archives; neither archive nor either
original raw_results.jsonl is written to.

BLINDING. The annotation view carries only:
    item_id          stable, salted hash of the unit id -- no ordering or condition information
    rationale_text   the raw generated response
    acknowledgment_label / context_mentioned   blank, for the judge to fill

Deliberately EXCLUDED from the annotation view: scorer identity, condition name, numerical
score, task-level delta, dataset, task id, and every experimental outcome. Those live only in
the separate key file, which is what makes the later join possible without unblinding the judge.

    python scripts/prepare_blinded_annotation_a9.py --out-dir results/blinded_annotation_a9
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

ARCHIVE_DIR = REPO.parents[2] / "archives"
ARCHIVES = {"olmo32b": "a100_archive_2026-08-18.tar.gz",
            "gemma": "gemma_archive_2026-08-18.tar.gz"}
MEMBER = "silent-influence/results/final_behavioral_study/raw_results.jsonl"

# Fields that must never reach the annotation view.
FORBIDDEN_IN_VIEW = ("scorer_key", "scorer_model_id", "condition", "added_context",
                     "parsed_score", "analysis_score", "retained_parsed_score",
                     "dataset", "source_task_id", "unit_id", "delta", "parse_status")


def _prior_score_value(condition: str):
    """The numeric prior score the condition injects, or None where it injects none."""
    return {"no_history": None, "self_low_2": 2, "other_low_2": 2, "unrelated_low_2": 2,
            "verbal_negative": None, "self_high_10": 10}.get(condition)


def load(tgz: Path) -> list:
    with tarfile.open(tgz, "r:gz") as t:
        return [json.loads(l) for l in t.extractfile(MEMBER) if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(REPO / "results/blinded_annotation_a9"))
    ap.add_argument("--seed", type=int, default=42,
                    help="id salt; identical for both judges so the two label sets join")
    ap.add_argument("--order-seed", type=int, default=20260818)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    staged = out / "_staged_records.jsonl"

    manifest, n_in, n_staged, skipped = {}, 0, 0, {}
    with staged.open("w", encoding="utf-8") as fh:
        for scorer, fname in ARCHIVES.items():
            p = ARCHIVE_DIR / fname
            manifest[scorer] = {"archive": fname,
                                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for r in load(p):
                n_in += 1
                text = (r.get("response") or "").strip()
                # A5-invalid records are still annotatable IF they carry text: the judge is
                # labelling what the model SAID, not whether the score was usable. Only
                # genuinely empty text or a technical failure is unannotatable.
                if r.get("generation_error"):
                    skipped["generation_error"] = skipped.get("generation_error", 0) + 1
                    continue
                if not text:
                    skipped["empty_response"] = skipped.get("empty_response", 0) + 1
                    continue
                fh.write(json.dumps({
                    # fields build_annotation.py expects
                    "rationale_unit_id": r["unit_id"],
                    "rationale_text": text,
                    "rationale_status": "ok",
                    "generation_error": None,
                    # key-only provenance; build_annotation writes these to the key file,
                    # never to the annotation view
                    "scorer_key": r["scorer_key"], "condition": r["condition"],
                    "dataset": r["dataset"], "source_task_id": r["source_task_id"],
                    "analysis_valid": r.get("analysis_valid"),
                    "analysis_validity": r.get("analysis_validity"),
                    "parsed_score": r.get("parsed_score"),
                    # Phase-1B key-file field names, so build_annotation.py is reused
                    # unchanged. KEY-ONLY: the builder never puts these in the view.
                    "prompt_id": r["source_task_id"],
                    "judge_model": r["scorer_key"],
                    "prior_context_condition": r["condition"],
                    "prior_score_value": _prior_score_value(r["condition"]),
                    "frozen_score": {"relevance": None, "reasoning_quality": None,
                                     "total": r.get("parsed_score")},
                    "rationale_tokens": r.get("output_tokens"),
                }, ensure_ascii=False) + "\n")
                n_staged += 1

    # Reuse the existing builder for both judges: same id salt (shared key space), different
    # presentation order so the two judges never see items in the same sequence.
    built = {}
    for judge, order in (("J1", args.order_seed), ("J2", args.order_seed + 1)):
        d = out / f"judge_{judge}"
        d.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(REPO / "scripts/build_annotation.py"),
               "--records", str(staged), "--out-dir", str(d),
               "--seed", str(args.seed), "--order-seed", str(order), "--label", judge]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stdout); print(res.stderr)
            raise SystemExit(f"build_annotation failed for {judge}")
        built[judge] = sorted(x.name for x in d.iterdir())

    # ---- blinding verification: the view must not carry any forbidden field -------------
    leaks = []
    for judge in built:
        view = out / f"judge_{judge}" / f"annotation_annotator_{judge}.jsonl"
        rows = [json.loads(l) for l in view.open(encoding="utf-8") if l.strip()]
        for row in rows:
            for f in FORBIDDEN_IN_VIEW:
                if f in row:
                    leaks.append((judge, f))
        assert set(rows[0]) == {"item_id", "rationale_text", "acknowledgment_label",
                                "context_mentioned"}, set(rows[0])
    # both judges must see the same item_id key space, in different order
    v1 = [json.loads(l)["item_id"] for l in
          (out / "judge_J1" / "annotation_annotator_J1.jsonl").open(encoding="utf-8") if l.strip()]
    v2 = [json.loads(l)["item_id"] for l in
          (out / "judge_J2" / "annotation_annotator_J2.jsonl").open(encoding="utf-8") if l.strip()]

    report = {
        "status": "PREPARED -- NOT SUBMITTED",
        "judge_model_selected": False,
        "external_calls_made": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_archives": manifest,
        "rubric_source": "scripts/build_annotation.py (reused unchanged)",
        "rubric": {"labels": ["A", "N", "D", "U"], "plus": "context_mentioned yes/no"},
        "n_records_read": n_in, "n_staged_for_annotation": n_staged, "skipped": skipped,
        "judges": {j: {"files": f, "n_items": len(v1)} for j, f in built.items()},
        "shared_key_space": sorted(v1) == sorted(v2),
        "presentation_order_differs": v1 != v2,
        "fields_in_annotation_view": ["item_id", "rationale_text", "acknowledgment_label",
                                      "context_mentioned"],
        "fields_excluded_from_view": list(FORBIDDEN_IN_VIEW),
        "blinding_leaks": leaks,
        "blinding_ok": not leaks,
        "agreement_analysis": {
            "prepared": True, "executed": False,
            "planned_metrics": ["raw percent agreement (acknowledgment_label)",
                                "Cohen's kappa (acknowledgment_label, 4 categories)",
                                "raw percent agreement (context_mentioned)",
                                "Cohen's kappa (context_mentioned, binary)",
                                "per-label confusion matrix",
                                "disagreement list for adjudication"],
            "join_key": "item_id",
            "unblinding_rule": ("labels are joined to the key file ONLY after both judges "
                                "have submitted and agreement is computed"),
        },
    }
    (out / "PREPARATION_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== blinded annotation dataset PREPARED (not submitted) ===")
    print(f"  records read              : {n_in}")
    print(f"  staged for annotation     : {n_staged}   skipped: {skipped or 'none'}")
    print(f"  items per judge           : {len(v1)}")
    print(f"  shared item_id key space  : {sorted(v1) == sorted(v2)}")
    print(f"  presentation order differs: {v1 != v2}")
    print(f"  view fields               : item_id, rationale_text, acknowledgment_label, "
          f"context_mentioned")
    print(f"  blinding leaks            : {leaks or 'none'}")
    print(f"  judge model selected      : False    external calls: False")
    print(f"[save] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
