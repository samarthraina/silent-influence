"""Analyze copied-back results (follow-up analyses; not pooled with the original study).

  calibration : rba.analysis (valid outcomes only, full planned
                denominators, complete-case task bootstrap 95%/97.5%, planned-population bounds)
  patching    : rba.mhp.analyze (raw, source-directed, normalized, paired site-minus-L2;
                identity failures excluded pending investigation; |gap| >= 1 sensitivity)
Writes outputs/analysis/*.json. Environment deviation: torch 2.14.1+cu126
(original 2.12.0+cu126); historical comparison is provenance, not reproduction.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

EXT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXT / "src"))
from rba import analysis as AN, inputs as I, mhp as M, units as U  # noqa: E402

RUN = EXT / "results"
OUT = Path(__import__("os").environ.get("SI_ANALYSIS_OUT", str(EXT / "outputs/analysis")))


def calibration():
    planned = [json.loads(l) for l in open(EXT / "artifacts/calibration/run_manifest_v1.jsonl")]
    final = {}
    for m in ("llama", "qwen"):
        d = RUN / "raw/calibration" / m
        if not d.exists():
            continue
        for r in U.load(d).attempts:            # re-validates schema, ids and payload hashes
            if r["status"] in ("accepted", "permanent_failure"):
                if r["unit_id"] in final:
                    raise SystemExit(f"two final attempts for {r['unit_id']}")
                final[r["unit_id"]] = r
    payloads = {k: v["payload"] for k, v in final.items()}
    cells = AN.cells_from_records(planned, payloads)
    tasks = sorted({u["base_task_id"] for u in planned})
    res = {"planned_units": len(planned), "final_units": len(final),
           "status_counts": dict(Counter(c["status"] for c in cells.values())),
           "environment_deviation": "torch 2.14.1+cu126 vs original 2.12.0+cu126; other pins as original",
           "label": "Follow-up analysis; not pooled with original headline"}
    for m in ("llama", "qwen"):
        r = {"primary_interaction": AN.estimate(cells, m, tasks, AN.PRIMARY),
             "cells": AN.cell_table(cells, m, tasks)}
        for k, c in AN.SECONDARY.items():
            r[k] = AN.estimate(cells, m, tasks, c)
        for v in r.values():
            if isinstance(v, dict):
                v.pop("per_task", None)
        res[m] = r
    # provenance comparison: original-rubric follow-up outputs vs historical frozen records
    hist = {}
    want = {u["provenance"]["historical_unit_id"]: u["unit_id"] for u in planned
            if u["rubric_id"] == "original"}
    for rec in I.iter_jsonl("merged_raw"):
        if rec["unit_id"] in want:
            hist[want[rec["unit_id"]]] = rec
    comp = Counter()
    for uid, h in hist.items():
        f = final.get(uid)
        if not f:
            comp["missing_followup"] += 1
            continue
        p = f["payload"]
        comp["n"] += 1
        comp["exact_text_match"] += (p.get("response") == h["response"])
        if p.get("analysis_valid") and h.get("analysis_valid"):
            comp["both_valid"] += 1
            comp["same_score"] += (float(p["analysis_score"]) == float(h["analysis_score"]))
    res["historical_provenance_comparison"] = dict(comp)
    return res


def patching(name):
    from rba import mhp_store as MS
    d = RUN / "raw" / name
    if not d.exists():
        return None
    recs, quarantined = MS.load(d)                 # validates hashes, indices, duplicates
    final = {r["unit_id"]: r["payload"] for r in recs if r["status"] in MS.FINAL}
    model = name.split("_", 1)[1]
    site = M.MODELS[model]["site_layer"]
    scores, toks = {}, {}
    for uid, pl in final.items():
        k = (pl["base_task_id"], pl["key"])
        scores[k] = pl["analysis_score"] if pl.get("analysis_valid") else None
        toks[k] = pl.get("generated_token_ids_sha256")
    tasks = sorted({pl["base_task_id"] for pl in final.values()})
    ident = M.identity_report(toks, tasks)
    bad = sorted({t for t, _ in ident["failures"]})
    validity = Counter(pl.get("analysis_validity") for pl in final.values())
    exposed = ["arena_hard/2da7e53308a547d6"]     # engineering smoke overlap (addendum A1)
    return {"quarantined_tails": quarantined, "units_final": len(final), "tasks": len(tasks), "validity_counts": dict(validity),
            "sensitivity_excluding_smoke_exposed_task": M.analyze(
                scores, tasks, site_layer=site, exclude_tasks=sorted(set(bad) | set(exposed))),
            "identity": ident,
            "primary": M.analyze(scores, tasks, site_layer=site, exclude_tasks=bad),
            "sensitivity_gap_ge_1": M.analyze(scores, tasks, min_gap=1.0, site_layer=site,
                                              exclude_tasks=bad),
            "including_identity_failures_for_reference": M.analyze(scores, tasks, site_layer=site)
            if bad else "no identity failures"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1:] or ["calibration", "study_llama", "study_qwen"]
    for w in which:
        res = calibration() if w == "calibration" else patching(w)
        if res is None:
            print(w, "no results")
            continue
        (OUT / f"{w}.json").write_text(json.dumps(res, indent=2, default=str) + "\n")
        print("wrote", w)


if __name__ == "__main__":
    main()
