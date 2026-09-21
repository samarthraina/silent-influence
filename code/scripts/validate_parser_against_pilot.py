#!/usr/bin/env python3
"""Validate scaled_parsing.py against the pilot's 432 recorded (response, parsed_score,
parse_ok) triples before it is trusted on any new data.

The pilot's own parser no longer exists as a file (Brain/work is read-only reference
evidence, not code we own), so byte-for-byte reproduction of its 432 judgements is the
acceptance bar for the new parser: same records marked ok, same scores, same 7 flagged
failures. Also re-verifies the prompt renderer (scaled_conditions.render_prompt) against
the same 432 records, since both pieces of fidelity matter for treating this as a genuine
scale-up rather than a new protocol.

    python scripts/validate_parser_against_pilot.py
"""
from __future__ import annotations

import os

import json
from pathlib import Path

from _bootstrap import REPO

from silent_influence import scaled_conditions as sc
from silent_influence import scaled_parsing as sp

# Release note: this pilot artifact is not part of the code tree. Point at it with
# the SI_PILOT_RAW environment variable, or place the file at the repository-relative
# default below.
PILOT_RAW = Path(os.environ.get(
    "SI_PILOT_RAW", str(REPO / "data", "pilot", "raw_results.jsonl")))
OUT = REPO / "results" / "scaled_silent_influence" / "pilot_parser_fidelity_report.json"

_CONDITION_NAME_MAP = {"blind": "no_history"}  # pilot's label -> this experiment's label


def main() -> int:
    if not PILOT_RAW.exists():
        raise SystemExit(f"pilot evidence not found: {PILOT_RAW}")

    records = []
    with open(PILOT_RAW, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    parse_mismatches = []
    prompt_mismatches = []
    for d in records:
        r = sp.parse_final_score(d["response"])
        if r.ok != d["parse_ok"] or (r.ok and abs(r.score - d["parsed_score"]) > 1e-9):
            parse_mismatches.append({
                "unit_id": d["unit_id"], "pilot_parse_ok": d["parse_ok"],
                "pilot_parsed_score": d["parsed_score"], "new_status": r.status,
                "new_score": r.score, "response": d["response"],
            })

        cond_name = _CONDITION_NAME_MAP.get(d["condition"], d["condition"])
        cond = sc.resolve(cond_name)
        rendered = sc.render_prompt(d["question"], d["candidate_answer"], cond)
        if rendered != d["prompt"]:
            prompt_mismatches.append({"unit_id": d["unit_id"],
                                      "expected": d["prompt"], "got": rendered})

    report = {
        "pilot_evidence": str(PILOT_RAW),
        "n_pilot_records": len(records),
        "n_parse_mismatches": len(parse_mismatches),
        "n_prompt_mismatches": len(prompt_mismatches),
        "parse_fidelity_ok": len(parse_mismatches) == 0,
        "prompt_fidelity_ok": len(prompt_mismatches) == 0,
        "parse_mismatches": parse_mismatches,
        "prompt_mismatches": prompt_mismatches,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"pilot records checked : {len(records)}")
    print(f"parse mismatches      : {len(parse_mismatches)}")
    print(f"prompt mismatches     : {len(prompt_mismatches)}")
    print(f"report                : {OUT}")
    ok = report["parse_fidelity_ok"] and report["prompt_fidelity_ok"]
    print("RESULT: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
