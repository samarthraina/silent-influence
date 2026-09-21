"""Cumulative effect-size table + ECDF for the complete-case confirmatory primary contrast.

Deltas come from the frozen estimator, not a reimplementation: pivot_scores and
contrast_diffs are imported from scripts/analyze_final_study.py and called on the merged
complete-case record set. Nothing about the contrast, the A5 validity rule or the pairing is
changed here.

Two task-level series, both of the frozen primary contrast no_history - self_low_2:
  overall     per-task mean delta ACROSS scorers -- the frozen task_level_effects series
  per scorer  that scorer's own per-task delta

Confidence intervals use the frozen bootstrap design: task-clustered, dataset-stratified,
10,000 replicates, seed 20260818. The resampling unit is (dataset, task); a resampled task
carries all of its scorer rows. The seven thresholds are the ones specified in the request,
fixed before this script was run and not adjusted afterwards.
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
import analyze_final_study as A  # frozen

RECORDS = WS / "results/behavioral/merged_raw_results.jsonl"
THRESHOLDS = [(">0", 0.0, False), (">=0.5", 0.5, True), (">=1.0", 1.0, True),
              (">=1.5", 1.5, True), (">=2.0", 2.0, True), (">=2.5", 2.5, True),
              (">=3.0", 3.0, True)]
SCORERS = ["llama", "qwen", "gemma", "olmo32b"]
N_BOOT, SEED = 10_000, A.BOOTSTRAP_SEED

records = A.load_records(RECORDS)
pivot = A.pivot_scores(records)
diffs = A.contrast_diffs(pivot, *A.PRIMARY, datasets=A.FULL_DATASETS)

# (dataset, task) -> {scorer: delta}; the resampling unit is the task, so deltas are held
# task-major and a resampled task brings every scorer it has.
by_task = {}
for scorer, dataset, task_id, d in diffs:
    by_task.setdefault((dataset, task_id), {})[scorer] = d
tasks_by_ds = {}
for (ds, tid) in by_task:
    tasks_by_ds.setdefault(ds, []).append((ds, tid))
for ds in tasks_by_ds:
    tasks_by_ds[ds].sort()


def series(task_keys):
    """-> {'overall': [...], scorer: [...]} for one (possibly resampled) task list."""
    out = {"overall": [], **{s: [] for s in SCORERS}}
    for k in task_keys:
        per = by_task[k]
        if per:
            out["overall"].append(float(np.mean(list(per.values()))))
        for s, v in per.items():
            out[s].append(v)
    return out


def frac(vals, thr, inclusive):
    if not vals:
        return float("nan")
    a = np.asarray(vals)
    return float((a >= thr).mean() if inclusive else (a > thr).mean())


all_keys = [k for ds in sorted(tasks_by_ds) for k in tasks_by_ds[ds]]
point = series(all_keys)

# ---- bootstrap: stratified by dataset, resample tasks with replacement ---------------
rng = np.random.default_rng(SEED)
strata = sorted(tasks_by_ds)
reps = {g: {lab: [] for lab, _, _ in THRESHOLDS} for g in ["overall"] + SCORERS}
for _ in range(N_BOOT):
    keys = []
    for ds in strata:
        pool = tasks_by_ds[ds]
        idx = rng.integers(0, len(pool), size=len(pool))
        keys.extend(pool[i] for i in idx)
    s = series(keys)
    for g in reps:
        for lab, thr, inc in THRESHOLDS:
            reps[g][lab].append(frac(s[g], thr, inc))


def ci(vals):
    a = np.asarray(vals, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0:
        return (float("nan"), float("nan"))
    return float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))


# ---- table ---------------------------------------------------------------------------
rows = []
for g in ["overall"] + SCORERS:
    vals = point[g]
    n = len(vals)
    for lab, thr, inc in THRESHOLDS:
        f = frac(vals, thr, inc)
        lo, hi = ci(reps[g][lab])
        rows.append([g, lab, n, int(round(f * n)), round(100 * f, 2),
                     round(100 * lo, 2), round(100 * hi, 2)])

OUT_T = WS / "results/tables/t9_cumulative_effect_sizes.csv"
with open(OUT_T, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["group", "threshold", "n_tasks_denominator", "n_tasks_at_or_above",
                "percent", "ci_low_percent", "ci_high_percent"])
    w.writerows(rows)

# ---- descriptive quantiles (NOT confirmatory) ----------------------------------------
desc = []
for g in ["overall"] + SCORERS:
    a = np.asarray(point[g], dtype=float)
    desc.append([g, len(a), round(float(np.percentile(a, 25)), 4),
                 round(float(np.median(a)), 4), round(float(np.percentile(a, 75)), 4),
                 round(float(np.percentile(a, 90)), 4), round(float(a.max()), 4),
                 round(float(a.min()), 4)])
OUT_D = WS / "results/tables/t10_descriptive_quantiles.csv"
with open(OUT_D, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["group", "n_tasks", "p25", "median", "p75", "p90",
                "max_DESCRIPTIVE", "min_DESCRIPTIVE"])
    w.writerows(desc)

json.dump({"analysis": "complete-case confirmatory primary contrast",
           "contrast": A.contrast_name(*A.PRIMARY),
           "estimator": "frozen: analyze_final_study.pivot_scores + contrast_diffs, unchanged",
           "measurement_basis": "complete_case",
           "thresholds_prespecified": [t[0] for t in THRESHOLDS],
           "thresholds_chosen_after_inspecting_results": False,
           "bootstrap": {"n_replicates": N_BOOT, "seed": SEED,
                         "design": "task-clustered, dataset-stratified; resampling unit "
                                   "(dataset, task); scorer rows travel with the task"},
           "top_tail_and_max_are_descriptive_not_confirmatory": True},
          open(WS / "results/tables/t9_t10_provenance.json", "w", encoding="utf-8"), indent=2)

print(f"  [save] {OUT_T.name}  ({len(rows)} rows)")
print(f"  [save] {OUT_D.name}  ({len(desc)} rows)")
for r in rows:
    print(f"  {r[0]:<8} {r[1]:<6} {r[3]:>4}/{r[2]:<4} {r[4]:>6.2f}%  [{r[5]:>5.2f}, {r[6]:>5.2f}]")
print()
for r in desc:
    print(f"  {r[0]:<8} n={r[1]:<4} p25={r[2]:+.3f} med={r[3]:+.3f} p75={r[4]:+.3f} "
          f"p90={r[5]:+.3f} max={r[6]:+.3f} min={r[7]:+.3f}")

np.save(WS / "_ecdf_series.npy",
        np.array([json.dumps({g: point[g] for g in point})], dtype=object),
        allow_pickle=True)
