"""OLMo-32B-only DESCRIPTIVE audit of the frozen complete-case primary pairs.

Descriptive only. Nothing here is a confirmatory estimate, no task is selected or excluded,
no threshold was chosen after looking at the numbers, and the final analysis is untouched --
this script only reads. Rationale text is never opened: the audit uses task ids, dataset,
category and the two parsed scores.

Pairs come from the frozen estimator (analyze_final_study.pivot_scores + contrast_diffs)
restricted to scorer olmo32b, which is the same 218 matched no_history / self_low_2 pairs the
confirmatory analysis uses.

The CI is a paired-task bootstrap: the resampling unit is the task pair, stratified by
dataset, 10,000 replicates, seed 20260818 (the frozen bootstrap design).
"""
import csv
import json
import os
import pathlib
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: F401  (puts code/src and code/scripts on sys.path)
import sys

import numpy as np

# Package layout: <package>/code/analysis/<this file> -> <package>.
# The upstream workspace subtrees map onto results/ and figures/ here.
WS = pathlib.Path(os.environ.get(
    "SI_SUPPLEMENT_ROOT", str(pathlib.Path(__file__).resolve().parents[2])))
REPO = WS.parent / "Code/GitHub/silent-influence"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
import analyze_final_study as A

OUT_T = WS / "results/tables"
OUT_T.mkdir(exist_ok=True)
SCORER = "olmo32b"
THRESHOLDS = [(">0", 0.0, False), (">=0.5", 0.5, True), (">=1.0", 1.0, True),
              (">=1.5", 1.5, True), (">=2.0", 2.0, True), (">=2.5", 2.5, True),
              (">=3.0", 3.0, True), (">=4.0", 4.0, True), (">=5.0", 5.0, True)]
N_BOOT, SEED = 10_000, A.BOOTSTRAP_SEED

records = A.load_records(WS / "results/behavioral/merged_raw_results.jsonl")
pivot = A.pivot_scores(records)
diffs = [d for d in A.contrast_diffs(pivot, *A.PRIMARY, datasets=A.FULL_DATASETS)
         if d[0] == SCORER]

# category comes from the frozen index, not re-derived
_, _, task_category, _ = A.build_index(records)

pairs = []
for scorer, dataset, task_id, delta in diffs:
    cell = pivot[(scorer, dataset, task_id)]
    pairs.append({
        "task_id": task_id, "dataset": dataset,
        "category": task_category.get((dataset, task_id), ""),
        "no_history": cell["no_history"], "self_low_2": cell["self_low_2"],
        "delta": delta,
    })
pairs.sort(key=lambda p: (p["dataset"], p["task_id"]))
delta = np.array([p["delta"] for p in pairs], dtype=float)
assert len(pairs) == 218, len(pairs)

# ---- 1. descriptive distribution -----------------------------------------------------
def describe(a):
    return {"n": int(a.size), "mean": float(a.mean()), "median": float(np.median(a)),
            "sd": float(a.std(ddof=1)), "p25": float(np.percentile(a, 25)),
            "p75": float(np.percentile(a, 75)), "p90": float(np.percentile(a, 90)),
            "p95": float(np.percentile(a, 95)), "min": float(a.min()), "max": float(a.max())}


desc = describe(delta)

# ---- 6. paired-task bootstrap CI for the mean ----------------------------------------
by_ds = {}
for i, p in enumerate(pairs):
    by_ds.setdefault(p["dataset"], []).append(i)
strata = sorted(by_ds)
rng = np.random.default_rng(SEED)
means, thr_reps = [], {lab: [] for lab, _, _ in THRESHOLDS}
for _ in range(N_BOOT):
    idx = []
    for ds in strata:
        pool = by_ds[ds]
        idx.extend(np.asarray(pool)[rng.integers(0, len(pool), size=len(pool))])
    a = delta[np.asarray(idx)]
    means.append(float(a.mean()))
    for lab, t, inc in THRESHOLDS:
        thr_reps[lab].append(float((a >= t).mean() if inc else (a > t).mean()))

ci_mean = (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))

# ---- 2/3. threshold table, overall and by dataset ------------------------------------
rows = []
for lab, t, inc in THRESHOLDS:
    k = int((delta >= t).sum() if inc else (delta > t).sum())
    lo, hi = np.percentile(thr_reps[lab], 2.5), np.percentile(thr_reps[lab], 97.5)
    rows.append(["ALL", lab, len(delta), k, round(100 * k / len(delta), 2),
                 round(100 * lo, 2), round(100 * hi, 2)])
for ds in strata:
    a = delta[np.asarray(by_ds[ds])]
    for lab, t, inc in THRESHOLDS:
        k = int((a >= t).sum() if inc else (a > t).sum())
        rows.append([ds, lab, int(a.size), k, round(100 * k / a.size, 2), "", ""])
with open(OUT_T / "t11_olmo_thresholds.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["dataset", "threshold", "n_pairs_denominator", "n_at_or_above", "percent",
                "ci_low_percent", "ci_high_percent"])
    w.writerows(rows)

# ---- 5. transparent top-20 / bottom-20 -----------------------------------------------
ordered = sorted(pairs, key=lambda p: p["delta"])
tb = ([("bottom_20", p) for p in ordered[:20]] +
      [("top_20", p) for p in ordered[-20:][::-1]])
with open(OUT_T / "t12_olmo_top20_bottom20.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["group", "task_id", "dataset", "category", "no_history_score",
                "self_low_2_score", "delta"])
    for g, p in tb:
        w.writerow([g, p["task_id"], p["dataset"], p["category"],
                    p["no_history"], p["self_low_2"], p["delta"]])

# per-dataset descriptives too
with open(OUT_T / "t13_olmo_descriptives.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["scope", "n", "mean", "sd", "min", "p25", "median", "p75", "p90", "p95", "max"])
    for scope, a in [("ALL", delta)] + [(ds, delta[np.asarray(by_ds[ds])]) for ds in strata]:
        d = describe(a)
        w.writerow([scope, d["n"]] + [round(d[k], 4) for k in
                    ("mean", "sd", "min", "p25", "median", "p75", "p90", "p95", "max")])

json.dump({"analysis": "OLMo-3.1-32B only -- DESCRIPTIVE, not confirmatory",
           "contrast": A.contrast_name(*A.PRIMARY), "measurement_basis": "complete_case",
           "n_pairs": len(pairs),
           "estimator": "frozen pivot_scores + contrast_diffs, restricted to olmo32b",
           "bootstrap": {"n_replicates": N_BOOT, "seed": SEED,
                         "design": "paired-task, dataset-stratified; unit = task pair"},
           "mean_delta": round(desc["mean"], 4),
           "mean_delta_ci95": [round(ci_mean[0], 4), round(ci_mean[1], 4)],
           "max_and_top_tail_are_descriptive_only": True,
           "no_task_selection_performed": True,
           "rationales_not_inspected": True,
           "final_analysis_modified": False},
          open(OUT_T / "t11_t13_provenance.json", "w", encoding="utf-8"), indent=2)

print(f"  n pairs: {len(pairs)}")
print("  " + "  ".join(f"{k}={desc[k]:+.4f}" for k in
                       ("mean", "median", "sd", "p25", "p75", "p90", "p95", "min", "max")))
print(f"  mean delta 95% CI (paired-task bootstrap): [{ci_mean[0]:.4f}, {ci_mean[1]:.4f}]")
print()
for r in rows[:len(THRESHOLDS)]:
    print(f"  ALL      {r[1]:<6} {r[3]:>4}/{r[2]:<4} {r[4]:>6.2f}%  [{r[5]:>5.2f}, {r[6]:>5.2f}]")
print()
for ds in strata:
    sub = [r for r in rows if r[0] == ds]
    print(f"  {ds:<11} n={sub[0][2]:<4} " +
          " ".join(f"{r[1]}={r[4]:.1f}%" for r in sub))
print("  [save] t11_olmo_thresholds.csv  t12_olmo_top20_bottom20.csv  t13_olmo_descriptives.csv")
