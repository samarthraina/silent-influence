#!/usr/bin/env python3
"""Build the adjudicated copy of results/final_behavioral_study/raw_results.jsonl: the
frozen original plus every recovered_pattern / recovered_manual score from
final_adjudication.json. Genuinely unresolved records are left exactly as they were
(parse_ok=False, parsed_score=None).

raw_results.jsonl itself is never touched -- this writes a DERIVED file to a separate
directory (results/final_behavioral_study_adjudicated/), which
scripts/analyze_final_study.py reads for the adjudicated measurement basis (the primary
measurement per plan v2). The adjudication file is hashed and the hash is written into
this script's manifest, per plan v2's "freezing" requirement (adjudication file written,
hashed and frozen before analysis; hash recorded in the results manifest) -- freezing
happens HERE, at the point the adjudicated dataset is fixed for analysis, not earlier.

    python scripts/build_final_adjudicated_records.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import output_validity as ov
from silent_influence.records import write_manifest

RAW_RESULTS = REPO / "results/final_behavioral_study/raw_results.jsonl"
ADJUDICATION = REPO / "results/final_behavioral_study/final_adjudication.json"
OUT_DIR = REPO / "results/final_behavioral_study_adjudicated"
OUT_RECORDS = OUT_DIR / "raw_results_adjudicated.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--records", default=None, help=f"default: {RAW_RESULTS}")
    ap.add_argument("--adjudication", default=None, help=f"default: {ADJUDICATION}")
    ap.add_argument("--out-dir", default=None, help=f"default: {OUT_DIR}")
    args = ap.parse_args()
    raw_results = Path(args.records) if args.records else RAW_RESULTS
    adjudication_path = Path(args.adjudication) if args.adjudication else ADJUDICATION
    out_dir = Path(args.out_dir) if args.out_dir else OUT_DIR
    out_records = (out_dir / "raw_results_adjudicated.jsonl"
                   if args.out_dir else OUT_RECORDS)

    if not raw_results.exists():
        raise SystemExit(f"{raw_results} does not exist yet")
    if not adjudication_path.exists():
        raise SystemExit(f"{adjudication_path} does not exist yet -- run "
                         f"scripts/merge_final_verifier_passes.py first")

    adjudication_sha256 = hashlib.sha256(adjudication_path.read_bytes()).hexdigest()
    with open(adjudication_path, encoding="utf-8") as f:
        adjudication = json.load(f)
    recovered = {e["unit_id"]: e["final_score"] for e in adjudication["entries"]
                if e["final_status"] in ("recovered_pattern", "recovered_manual")}

    out_dir.mkdir(parents=True, exist_ok=True)
    n_patched = 0
    n_lines = 0
    with open(raw_results, encoding="utf-8") as fin, \
         open(out_records, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            n_lines += 1
            r = json.loads(line)
            # A5: a capped-incomplete response can never be promoted to valid, whatever
            # an adjudication file says about it -- it never should have been queued.
            if ov.is_capped_incomplete(r):
                out.append(ov.annotate(r))
                continue
            if r["unit_id"] in recovered:
                r["parsed_score"] = recovered[r["unit_id"]]
                r["parse_ok"] = True
                r["parse_status"] = "recovered_adjudication"
                r = ov.annotate(r)
                n_patched += 1
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")

    write_manifest(out_dir / "manifest_adjudication.json", {
        "source_raw_results": str(raw_results),
        "source_adjudication_file": str(adjudication_path),
        "adjudication_sha256": adjudication_sha256,
        "n_records_total": n_lines, "n_records_patched": n_patched,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })

    print(f"records total       : {n_lines}")
    print(f"patched w/ adjudicated score : {n_patched}")
    print(f"adjudication sha256 : {adjudication_sha256}")
    print(f"[save] {out_records}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
