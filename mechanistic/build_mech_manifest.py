"""Freeze the compact Llama mechanistic task manifest.

OUTCOME-DEPENDENT SELECTION, DELIBERATELY. Tasks are chosen using their behavioural effect
sizes, so this manifest supports a mechanistic case study and nothing else: it cannot be
read as an estimate of how large or how common the behavioural effect is. That is recorded
in the manifest itself, not only here.

Criteria, all fixed before the sample was drawn:
  - Llama, A5-valid matched no_history / self_low_2 pairs
  - exclude the compatibility-smoke task
  - exclude floor/ceiling: BOTH endpoint scores must lie in [2, 9]
  - discovery : 12 tasks, 4 per dataset, from remaining tasks with delta >= 2
  - validation: 24 tasks, 8 per dataset, disjoint from discovery, delta >= 1

If any stratum is short the script stops; the criteria are not relaxed to fill it.
"""
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT / "Code/GitHub/silent-influence"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
import analyze_final_study as A

SEED = 20260818
SMOKE_TASK = ("arena_hard", "4c7d8a034c4e40f6")
DATASETS = ["mtbench", "arena_hard", "wildbench"]
SCORE_LO, SCORE_HI = 2.0, 9.0
N_DISC_PER_DS, N_VAL_PER_DS = 4, 8
OUT = HERE / "manifest"
OUT.mkdir(parents=True, exist_ok=True)

records = A.load_records(ROOT / "final_analysis_workspace/merged_raw_results.jsonl")
pivot = A.pivot_scores(records)

pool = []
for (scorer, ds, tid), cell in pivot.items():
    if scorer != "llama" or "no_history" not in cell or "self_low_2" not in cell:
        continue
    nh, sl = float(cell["no_history"]), float(cell["self_low_2"])
    pool.append({"dataset": ds, "task_id": tid, "no_history": nh, "self_low_2": sl,
                 "delta": nh - sl})

n_all = len(pool)
pool = [p for p in pool if (p["dataset"], p["task_id"]) != SMOKE_TASK]
n_no_smoke = len(pool)
pool = [p for p in pool if SCORE_LO <= p["no_history"] <= SCORE_HI
        and SCORE_LO <= p["self_low_2"] <= SCORE_HI]
n_in_band = len(pool)

# Deterministic: sort by task id, then draw with a fixed-seed permutation.
def draw(cands, k, rng):
    cands = sorted(cands, key=lambda p: (p["dataset"], str(p["task_id"])))
    idx = rng.permutation(len(cands))[:k]
    return [cands[i] for i in sorted(idx)]


rng = np.random.default_rng(SEED)
shortfalls, discovery = [], []
for ds in DATASETS:
    c = [p for p in pool if p["dataset"] == ds and p["delta"] >= 2]
    if len(c) < N_DISC_PER_DS:
        shortfalls.append(f"discovery/{ds}: {len(c)} available, need {N_DISC_PER_DS}")
    else:
        discovery += draw(c, N_DISC_PER_DS, rng)

chosen = {(p["dataset"], p["task_id"]) for p in discovery}
validation = []
for ds in DATASETS:
    c = [p for p in pool if p["dataset"] == ds and p["delta"] >= 1
         and (p["dataset"], p["task_id"]) not in chosen]
    if len(c) < N_VAL_PER_DS:
        shortfalls.append(f"validation/{ds}: {len(c)} available, need {N_VAL_PER_DS}")
    else:
        validation += draw(c, N_VAL_PER_DS, rng)

if shortfalls:
    print("STOP -- insufficient stratum, criteria NOT relaxed:")
    for s in shortfalls:
        print("  " + s)
    raise SystemExit(2)

dkeys = {(p["dataset"], p["task_id"]) for p in discovery}
vkeys = {(p["dataset"], p["task_id"]) for p in validation}
assert not (dkeys & vkeys), "discovery and validation overlap"
assert len(discovery) == 12 and len(validation) == 24
assert SMOKE_TASK not in dkeys | vkeys

manifest = {
    "record_id": "llama_mechanistic_case_study_manifest",
    "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "scorer": "llama",
    "contrast": "no_history vs self_low_2",
    "SELECTION_IS_OUTCOME_DEPENDENT": True,
    "intended_use": "mechanistic case study only",
    "not_valid_for": ["any estimate of effect size, prevalence or generality",
                      "any confirmatory behavioural claim"],
    "seed": SEED,
    "criteria": {
        "a5_valid_matched_pairs_only": True,
        "excluded_smoke_task": f"{SMOKE_TASK[0]}/{SMOKE_TASK[1]}",
        "endpoint_score_band_inclusive": [SCORE_LO, SCORE_HI],
        "discovery_min_delta": 2, "validation_min_delta": 1,
        "per_dataset": {"discovery": N_DISC_PER_DS, "validation": N_VAL_PER_DS},
    },
    "funnel": {"llama_matched_pairs": n_all, "after_smoke_exclusion": n_no_smoke,
               "after_endpoint_band": n_in_band},
    "discovery": discovery,
    "validation": validation,
}
path = OUT / "mech_task_manifest.json"
path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
sha = hashlib.sha256(path.read_bytes()).hexdigest()
(OUT / "mech_task_manifest.sha256").write_text(f"{sha}  mech_task_manifest.json\n",
                                               encoding="utf-8")

print(f"  llama matched pairs {n_all} -> minus smoke {n_no_smoke} -> in band [2,9] {n_in_band}")
for name, grp in (("discovery", discovery), ("validation", validation)):
    per = {d: sum(1 for p in grp if p["dataset"] == d) for d in DATASETS}
    dd = [p["delta"] for p in grp]
    print(f"  {name:<10} n={len(grp):<3} per-dataset {per}  delta min {min(dd):+.1f} "
          f"max {max(dd):+.1f} mean {np.mean(dd):+.2f}")
print(f"  disjoint: {not (dkeys & vkeys)}   smoke excluded: {SMOKE_TASK not in dkeys | vkeys}")
print(f"  sha256 {sha}")
print(f"  [save] {path}")
