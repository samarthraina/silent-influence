#!/usr/bin/env python3
"""Full frozen analysis for the final 578-task behavioral study, exactly per
configs/final_analysis_plan.json (plan v2), configs/final_analysis_plan_v2_1.json
(Amendment A1), configs/final_analysis_plan_v2_2.json (Amendment A2 -- fourth scorer
replaced with allenai/Olmo-3.1-32B-Instruct) and
configs/final_analysis_plan_v2_2_clarification_C1.json (Clarification C1 -- corrects the
S1 sensitivity-analysis rationale). Nothing here is a new statistical decision -- every
estimand, weight, population, contrast, and bootstrap parameter below is copied from
those frozen files, not invented.

S1_three_scorer_sensitivity (added by A2, corrected by C1) is a prespecified,
NON-CONFIRMATORY robustness check restricted to the three non-OLMo scorers (llama, qwen,
gemma). It tests whether the primary conclusion depends materially on including the OLMo
scorer -- see C1_1: an ADDITIVE answer-family affinity cancels in the paired contrast
because the frozen answer is byte-identical across conditions, but a scorer-family-by-
condition INTERACTION would not, and its direction is not established. S1 rides the same
per-replicate bootstrap draws as every other statistic and can NEVER replace, override, or
become the primary analysis.

Runs BOTH measurement bases for every estimand (R3_adjudicated_vs_complete_case):
adjudicated scores (--records-adjudicated, from
results/final_behavioral_study_adjudicated/raw_results_adjudicated.jsonl) are the primary
measurement; the automatic-parser complete-case scores (--records-complete-case, from
results/final_behavioral_study/raw_results.jsonl) are the principal sensitivity variant.
If only one of the two files exists yet, that basis alone is reported and the other is
marked unavailable -- this script never fabricates the missing one.

    python scripts/analyze_final_study.py
    python scripts/analyze_final_study.py --skip-figures --n-bootstrap 200   # fast dev check
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from _bootstrap import REPO

from silent_influence import output_validity as ov

# ---- Frozen design constants (plan v2 + A1 + A2 + C1; do not edit for a "nicer" number) --

SCORERS = ["llama", "qwen", "gemma", "olmo32b"]
HELDOUT_DATASETS = ["arena_hard", "wildbench"]           # primary population: 500 tasks
FULL_DATASETS = ["mtbench", "arena_hard", "wildbench"]    # secondary population: 578 tasks

# S1_three_scorer_sensitivity (Amendment A2, corrected by Clarification C1): explicit,
# hardcoded list of the three non-OLMo scorers -- deliberately NOT "SCORERS minus the OLMo
# one" computed generically, so a future scorer-panel change can never silently redefine
# what S1 means.
S1_SCORERS = ["llama", "qwen", "gemma"]

# Amendment A9. The confirmatory primary contrast no_history - self_low_2 is evaluated across
# ALL FOUR scorers and THREE datasets, each dataset weighted equally and each scorer weighted
# equally -> 12 cells at 1/12. OLMo-3.1-32B contributes ONLY this contrast: it is the
# larger-model primary-effect replication, and it did not run the diagnostic conditions.
# The diagnostic conditions and their contrasts are therefore evaluated on llama/qwen/gemma
# only -- stated explicitly rather than left implicit in a missing-data pattern.
A9_PRIMARY_SCORERS = ["llama", "qwen", "gemma", "olmo32b"]
A9_DIAGNOSTIC_SCORERS = ["llama", "qwen", "gemma"]
A9_PRIMARY_N_CELLS = 12          # 3 datasets x 4 scorers
A9_PRIMARY_CELL_WEIGHT = 1 / A9_PRIMARY_N_CELLS
A9_DIAGNOSTIC_N_CELLS = 9        # 3 datasets x 3 scorers
A9_N_TASKS = 234
A9_DO_NOT_COMBINE_WITH_90_TASK_STUDY = True
S1_N_CELLS_PRIMARY = 6      # 2 datasets x 3 scorers
S1_N_CELLS_SECONDARY = 9    # 3 datasets x 3 scorers
S1_CELL_WEIGHT_PRIMARY = 1 / S1_N_CELLS_PRIMARY
S1_CELL_WEIGHT_SECONDARY = 1 / S1_N_CELLS_SECONDARY

PRIMARY = ("no_history", "self_low_2")
DIAGNOSTIC_CONTRASTS: List[Tuple[str, str]] = [
    ("other_low_2", "self_low_2"),
    ("unrelated_low_2", "self_low_2"),
    ("no_history", "unrelated_low_2"),
    ("no_history", "verbal_negative"),
    ("self_high_10", "self_low_2"),
    ("self_high_10", "no_history"),
    ("no_history", "other_low_2"),
]
ALL_CONTRASTS = [PRIMARY] + DIAGNOSTIC_CONTRASTS

N_CELLS_PRIMARY = 8    # 2 datasets x 4 scorers
N_CELLS_SECONDARY = 12  # 3 datasets x 4 scorers
CELL_WEIGHT_PRIMARY = 1 / N_CELLS_PRIMARY
CELL_WEIGHT_SECONDARY = 1 / N_CELLS_SECONDARY

N_BOOTSTRAP = 10_000
BOOTSTRAP_SEED = 20260818
TRIM_FRACTION = 0.10  # R1, symmetric, applied within each cell

DIAGNOSTIC_SCOPES = ("pooled", "dataset", "scorer")


def contrast_name(a: str, b: str) -> str:
    return f"{a}_minus_{b}"


# ---- Loading ---------------------------------------------------------------------------

def load_records(path: Path) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def build_index(records: List[dict]):
    rows_by_task: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    task_ids_by_dataset: Dict[str, set] = defaultdict(set)
    task_category: Dict[Tuple[str, str], str] = {}
    task_prior_use: Dict[Tuple[str, str], bool] = {}
    for r in records:
        key = (r["dataset"], r["source_task_id"])
        rows_by_task[key].append(r)
        task_ids_by_dataset[r["dataset"]].add(r["source_task_id"])
        task_category[key] = r["category"]
        task_prior_use[key] = bool(r.get("previously_used"))
    task_ids_by_dataset = {d: sorted(v) for d, v in task_ids_by_dataset.items()}
    return dict(rows_by_task), task_ids_by_dataset, task_category, task_prior_use


def pivot_scores(rows: List[dict]) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    pivot: Dict[Tuple[str, str, str], Dict[str, float]] = defaultdict(dict)
    for r in rows:
        if not ov.is_valid(r):
            continue
        key = (r["scorer_key"], r["dataset"], r["source_task_id"])
        pivot[key][r["condition"]] = ov.analysis_score(r)
    return dict(pivot)


def contrast_diffs(pivot, a: str, b: str,
                   datasets: Optional[List[str]] = None) -> List[Tuple[str, str, str, float]]:
    out = []
    ds_set = set(datasets) if datasets is not None else None
    for (scorer, dataset, task_id), scores in pivot.items():
        if ds_set is not None and dataset not in ds_set:
            continue
        if a in scores and b in scores:
            out.append((scorer, dataset, task_id, scores[a] - scores[b]))
    return out


# ---- Cells, macro averages, trimmed mean ------------------------------------------------

def trimmed_mean(values: List[float], frac: float = TRIM_FRACTION) -> float:
    """Symmetric proportion trim, no scipy dependency: drop floor(n*frac) values from
    each end of the sorted array, then mean the remainder. With too few points to trim
    (n <= 2) falls back to the plain mean."""
    arr = np.sort(np.asarray(values, dtype=float))
    n = len(arr)
    if n == 0:
        return float("nan")
    k = int(np.floor(n * frac))
    if 2 * k >= n:
        return float(arr.mean())
    return float(arr[k:n - k].mean())


def cell_values(diffs: List[Tuple[str, str, str, float]]) -> Dict[Tuple[str, str], List[float]]:
    """(dataset, scorer) -> [paired diffs]."""
    buckets: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for scorer, dataset, task_id, d in diffs:
        buckets[(dataset, scorer)].append(d)
    return dict(buckets)


def macro_average(cells: Dict[Tuple[str, str], List[float]], required_cells: List[Tuple[str, str]],
                  estimator="mean") -> dict:
    """Equal-weight mean of per-cell means (or trimmed means) over `required_cells`.
    Empty cells (no complete pairs) are excluded from the average and counted, per
    Amendment A1's closed E5 rule."""
    means = {}
    ns = {}
    for cell in required_cells:
        vals = cells.get(cell, [])
        ns[cell] = len(vals)
        if vals:
            means[cell] = trimmed_mean(vals) if estimator == "trimmed" else float(np.mean(vals))
    n_empty = sum(1 for c in required_cells if ns[c] == 0)
    macro = float(np.mean(list(means.values()))) if means else None
    return {"macro_average": macro, "n_empty_cells": n_empty,
           "cell_means": {f"{c[0]}|{c[1]}": means.get(c) for c in required_cells},
           "cell_n": {f"{c[0]}|{c[1]}": ns[c] for c in required_cells}}


def required_cells(datasets: List[str], scorers: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """`scorers` defaults to the full four-scorer panel; pass S1_SCORERS to restrict the
    macro average to the three non-OLMo scorers (S1_three_scorer_sensitivity)."""
    return [(d, s) for d in datasets for s in (scorers if scorers is not None else SCORERS)]


# ---- Task-level effect distribution -----------------------------------------------------

def task_level_effects(pivot, a: str, b: str, task_category, datasets: List[str]) -> List[dict]:
    ds_set = set(datasets)
    by_task: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for (scorer, dataset, task_id), scores in pivot.items():
        if dataset not in ds_set:
            continue
        if a in scores and b in scores:
            by_task[(dataset, task_id)].append(scores[a] - scores[b])
    out = []
    for (dataset, task_id), vals in by_task.items():
        out.append({"dataset": dataset, "task_id": task_id,
                    "category": task_category.get((dataset, task_id)),
                    "mean_effect": float(np.mean(vals)), "n_scorers": len(vals)})
    return sorted(out, key=lambda r: -r["mean_effect"])


def task_level_distribution_stats(task_level: List[dict]) -> dict:
    effects = np.array([t["mean_effect"] for t in task_level], dtype=float)
    n = len(effects)
    if n == 0:
        return {"n_tasks": 0}
    return {
        "n_tasks": n,
        "fraction_gt_0": float((effects > 0).mean()),
        "fraction_eq_0": float((effects == 0).mean()),
        "fraction_lt_0": float((effects < 0).mean()),
        "fraction_ge_1": float((effects >= 1).mean()),
        "fraction_ge_2": float((effects >= 2).mean()),
        "min": float(effects.min()), "p25": float(np.percentile(effects, 25)),
        "median": float(np.median(effects)), "p75": float(np.percentile(effects, 75)),
        "max": float(effects.max()),
    }


# ---- Pooled summaries ---------------------------------------------------------------------

def pair_weighted_pooled(diffs: List[Tuple[str, str, str, float]]) -> dict:
    vals = [d for *_x, d in diffs]
    return {"mean": float(np.mean(vals)) if vals else None, "n": len(vals)}


def task_weighted_pooled(task_level: List[dict]) -> dict:
    vals = [t["mean_effect"] for t in task_level]
    return {"mean": float(np.mean(vals)) if vals else None, "n": len(vals)}


def dataset_wise(cells: Dict[Tuple[str, str], List[float]], datasets: List[str]) -> dict:
    out = {}
    for d in datasets:
        per_scorer = [float(np.mean(cells[(d, s)])) for s in SCORERS if cells.get((d, s))]
        out[d] = {"mean": float(np.mean(per_scorer)) if per_scorer else None,
                  "n_scorers_with_data": len(per_scorer)}
    return out


def scorer_wise(cells: Dict[Tuple[str, str], List[float]], datasets: List[str]) -> dict:
    out = {}
    for s in SCORERS:
        per_dataset = [float(np.mean(cells[(d, s)])) for d in datasets if cells.get((d, s))]
        out[s] = {"mean": float(np.mean(per_dataset)) if per_dataset else None,
                  "n_datasets_with_data": len(per_dataset)}
    return out


def per_condition_levels(records: List[dict], datasets: List[str]) -> List[dict]:
    ds_set = set(datasets)
    buckets = defaultdict(list)
    for r in records:
        if r["dataset"] not in ds_set or not ov.is_valid(r):
            continue
        buckets[(r["condition"], r["scorer_key"], r["dataset"])].append(
            ov.analysis_score(r))
    out = []
    for (cond, scorer, dataset), vals in sorted(buckets.items()):
        arr = np.array(vals)
        out.append({"condition": cond, "scorer": scorer, "dataset": dataset,
                    "mean": float(arr.mean()), "sd": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
                    "n": len(arr)})
    return out


# ---- Diagnostics ---------------------------------------------------------------------------

DIAG_SCOPE_KEYS = {
    "pooled": lambda s, d: None,
    "dataset": lambda s, d: d,
    "scorer": lambda s, d: s,
}


def diag_agg(diffs, key_fn) -> Dict:
    buckets: Dict = defaultdict(list)
    for scorer, dataset, task_id, d in diffs:
        buckets[key_fn(scorer, dataset)].append(d)
    return {k: {"mean": float(np.mean(v)), "n": len(v)} for k, v in buckets.items()}


def compute_diagnostics(pivot, datasets: List[str]) -> dict:
    out = {}
    for a, b in ALL_CONTRASTS:
        cname = contrast_name(a, b)
        diffs = contrast_diffs(pivot, a, b, datasets=datasets)
        out[cname] = {scope: diag_agg(diffs, fn) for scope, fn in DIAG_SCOPE_KEYS.items()}
    return out


# ---- Bootstrap (task-clustered, dataset-stratified, shared draws) -------------------------

def bootstrap_replicates(rows_by_task, task_ids_by_dataset, task_category, *,
                         seed=BOOTSTRAP_SEED, n_reps=N_BOOTSTRAP):
    """One resampling draw per replicate over ALL THREE dataset strata (mtbench, arena_hard,
    wildbench), shared across every statistic computed from it -- primary excludes mtbench
    rows from its OWN estimand but is still drawn from the same replicate's task-set as
    everything else, per plan v2's bootstrap.shared_draws.

    Returns a dict of raw replicate value lists, keyed by a flat statistic name, plus the
    count of replicates where at least one primary/secondary cell was empty."""
    rng = np.random.default_rng(seed)
    strata = sorted(task_ids_by_dataset)  # mtbench, arena_hard, wildbench (if present)

    out = {
        "primary_macro": [], "secondary_macro": [],
        "primary_macro_trimmed": [], "secondary_macro_trimmed": [],
        "task_weighted_heldout": [], "task_weighted_full": [],
        "pair_weighted_heldout": [], "pair_weighted_full": [],
        "s1_primary_macro": [], "s1_secondary_macro": [],
    }
    for a, b in ALL_CONTRASTS:
        cname = contrast_name(a, b)
        for scope in DIAGNOSTIC_SCOPES:
            out[f"diag__{cname}__{scope}"] = defaultdict(list)

    n_empty_primary_replicates = 0
    n_empty_secondary_replicates = 0

    for _ in range(n_reps):
        resampled_rows = []
        for d in strata:
            ids = task_ids_by_dataset[d]
            if not ids:
                continue
            sampled = rng.choice(ids, size=len(ids), replace=True)
            for tid in sampled:
                resampled_rows.extend(rows_by_task[(d, tid)])

        pivot = pivot_scores(resampled_rows)

        primary_diffs = contrast_diffs(pivot, *PRIMARY, datasets=HELDOUT_DATASETS)
        secondary_diffs = contrast_diffs(pivot, *PRIMARY, datasets=FULL_DATASETS)
        primary_cells = cell_values(primary_diffs)
        secondary_cells = cell_values(secondary_diffs)

        pm = macro_average(primary_cells, required_cells(HELDOUT_DATASETS))
        sm = macro_average(secondary_cells, required_cells(FULL_DATASETS))
        pmt = macro_average(primary_cells, required_cells(HELDOUT_DATASETS), estimator="trimmed")
        smt = macro_average(secondary_cells, required_cells(FULL_DATASETS), estimator="trimmed")
        n_empty_primary_replicates += int(pm["n_empty_cells"] > 0)
        n_empty_secondary_replicates += int(sm["n_empty_cells"] > 0)
        if pm["macro_average"] is not None:
            out["primary_macro"].append(pm["macro_average"])
        if sm["macro_average"] is not None:
            out["secondary_macro"].append(sm["macro_average"])
        if pmt["macro_average"] is not None:
            out["primary_macro_trimmed"].append(pmt["macro_average"])
        if smt["macro_average"] is not None:
            out["secondary_macro_trimmed"].append(smt["macro_average"])

        # S1_three_scorer_sensitivity: SAME resampled primary_cells/secondary_cells dicts
        # from this replicate, restricted to S1_SCORERS -- shared bootstrap draws, no new
        # resampling (Amendment A2 / Clarification C1_1).
        s1_pm = macro_average(primary_cells, required_cells(HELDOUT_DATASETS, S1_SCORERS))
        s1_sm = macro_average(secondary_cells, required_cells(FULL_DATASETS, S1_SCORERS))
        if s1_pm["macro_average"] is not None:
            out["s1_primary_macro"].append(s1_pm["macro_average"])
        if s1_sm["macro_average"] is not None:
            out["s1_secondary_macro"].append(s1_sm["macro_average"])

        tl_heldout = task_level_effects(pivot, *PRIMARY, task_category, HELDOUT_DATASETS)
        tl_full = task_level_effects(pivot, *PRIMARY, task_category, FULL_DATASETS)
        out["task_weighted_heldout"].append(task_weighted_pooled(tl_heldout)["mean"])
        out["task_weighted_full"].append(task_weighted_pooled(tl_full)["mean"])
        out["pair_weighted_heldout"].append(pair_weighted_pooled(primary_diffs)["mean"])
        out["pair_weighted_full"].append(pair_weighted_pooled(secondary_diffs)["mean"])

        for a, b in ALL_CONTRASTS:
            cname = contrast_name(a, b)
            diffs = contrast_diffs(pivot, a, b, datasets=FULL_DATASETS)
            for scope, fn in DIAG_SCOPE_KEYS.items():
                for key, v in diag_agg(diffs, fn).items():
                    out[f"diag__{cname}__{scope}"][key].append(v["mean"])

    return out, n_empty_primary_replicates, n_empty_secondary_replicates


def ci95(values: List[float]) -> dict:
    if not values:
        return {"ci_low": None, "ci_high": None, "n_bootstrap_reps": 0}
    arr = np.array(values)
    return {"ci_low": float(np.percentile(arr, 2.5)), "ci_high": float(np.percentile(arr, 97.5)),
           "n_bootstrap_reps": len(arr)}


# ---- R2 leave-one-task-out -----------------------------------------------------------------

def loto(rows_by_task, task_ids: List[str], dataset_of: Dict[str, str], datasets: List[str]) -> dict:
    """Recompute the macro estimand with each task, in turn, entirely removed. `task_ids`
    is the full flat list across `datasets`; `dataset_of[task_id]` gives its dataset."""
    full_rows = [r for tid in task_ids for r in rows_by_task[(dataset_of[tid], tid)]]
    full_pivot = pivot_scores(full_rows)
    full_diffs = contrast_diffs(full_pivot, *PRIMARY, datasets=datasets)
    baseline = macro_average(cell_values(full_diffs), required_cells(datasets))["macro_average"]

    shifts = []
    for excluded in task_ids:
        rows = [r for tid in task_ids if tid != excluded
               for r in rows_by_task[(dataset_of[tid], tid)]]
        pivot = pivot_scores(rows)
        diffs = contrast_diffs(pivot, *PRIMARY, datasets=datasets)
        m = macro_average(cell_values(diffs), required_cells(datasets))["macro_average"]
        if m is not None and baseline is not None:
            shifts.append({"excluded_task_id": excluded, "dataset": dataset_of[excluded],
                          "macro_average_excl": m, "shift": m - baseline})

    shifts_sorted = sorted(shifts, key=lambda r: -abs(r["shift"]))
    vals = [s["shift"] for s in shifts]
    return {
        "baseline_macro_average": baseline, "n_recomputations": len(shifts),
        "min_shift": min(vals) if vals else None, "max_shift": max(vals) if vals else None,
        "range_shift": (max(vals) - min(vals)) if vals else None,
        "ten_most_influential": shifts_sorted[:10],
    }


# ---- R4 prior-use descriptive (never causal) -----------------------------------------------

def prior_use_descriptive(task_level_full: List[dict], task_prior_use: Dict[Tuple[str, str], bool]) -> dict:
    prev_used = [t["mean_effect"] for t in task_level_full
                if task_prior_use.get((t["dataset"], t["task_id"]))]
    held_out = [t["mean_effect"] for t in task_level_full
               if not task_prior_use.get((t["dataset"], t["task_id"]))]
    return {
        "previously_used": {"n": len(prev_used),
                           "mean_task_level_effect": float(np.mean(prev_used)) if prev_used else None},
        "held_out": {"n": len(held_out),
                    "mean_task_level_effect": float(np.mean(held_out)) if held_out else None},
        "CONFOUNDED_WITH_DATASET": True,
        "confound_statement": ("Previous-use status is completely confounded with "
                               "MT-Bench and cannot receive a causal interpretation. All "
                               "previously-used tasks are MT-Bench; only a handful of "
                               "MT-Bench tasks are naive, so any group difference is "
                               "indistinguishable from a MT-Bench vs other-datasets "
                               "difference."),
        "status": "descriptive_only",
        "forbidden_claim": "no statement of the form 'prior exposure changes the effect' "
                           "may be made from this comparison",
        "design_level_answer": "the primary analysis, restricted to the 500 never-used tasks",
    }


# ---- S1 three-scorer sensitivity (Amendment A2, corrected by Clarification C1) -----------

def fourth_scorer_cell_means(cells: Dict[Tuple[str, str], List[float]],
                             datasets: List[str], fourth_scorer_key: str) -> dict:
    """Reports the OLMo scorer's own per-cell means and N separately, so its individual
    behaviour is visible rather than buried inside the four-scorer macro average
    (S1_three_scorer_sensitivity.reported, plan v2 A2)."""
    out = {}
    for d in datasets:
        vals = cells.get((d, fourth_scorer_key), [])
        out[d] = {"mean": float(np.mean(vals)) if vals else None, "n": len(vals)}
    return out


def s1_three_scorer_sensitivity(primary_cells, secondary_cells, replicate_stats,
                                primary_macro_average: Optional[float],
                                secondary_macro_average: Optional[float],
                                fourth_scorer_key: str = "olmo32b") -> dict:
    """Prespecified, non-confirmatory sensitivity analysis restricted to S1_SCORERS.
    Reuses the SAME cell dicts and bootstrap replicate series computed for the four-scorer
    primary/secondary -- no new data, no new resampling. Never returned under the
    'primary'/'secondary' keys and never consulted by any decision rule; see
    C1_1_S1_rationale_correction for what this analysis does and does not establish."""
    s1_primary = macro_average(primary_cells, required_cells(HELDOUT_DATASETS, S1_SCORERS))
    s1_secondary = macro_average(secondary_cells, required_cells(FULL_DATASETS, S1_SCORERS))
    diff_primary = (s1_primary["macro_average"] - primary_macro_average
                    if s1_primary["macro_average"] is not None
                    and primary_macro_average is not None else None)
    diff_secondary = (s1_secondary["macro_average"] - secondary_macro_average
                      if s1_secondary["macro_average"] is not None
                      and secondary_macro_average is not None else None)
    return {
        "confirmatory": False,
        "status": "robustness check, NOT a correction of a confound (see C1_1)",
        "label": "primary recomputed on the three non-OLMo scorers",
        "scorers": S1_SCORERS,
        "primary": {
            "population": "the same 500 fully held-out arena_hard + wildbench tasks",
            "n_cells": S1_N_CELLS_PRIMARY, "cell_weight": S1_CELL_WEIGHT_PRIMARY,
            **s1_primary, "ci_95": ci95(replicate_stats["s1_primary_macro"]),
            "difference_from_four_scorer_primary": diff_primary,
        },
        "secondary": {
            "population": "all 578 tasks",
            "n_cells": S1_N_CELLS_SECONDARY, "cell_weight": S1_CELL_WEIGHT_SECONDARY,
            **s1_secondary, "ci_95": ci95(replicate_stats["s1_secondary_macro"]),
            "difference_from_four_scorer_secondary": diff_secondary,
        },
        "fourth_scorer_cell_means": {
            "heldout_500": fourth_scorer_cell_means(primary_cells, HELDOUT_DATASETS,
                                                    fourth_scorer_key),
            "full_578": fourth_scorer_cell_means(secondary_cells, FULL_DATASETS,
                                                 fourth_scorer_key),
        },
        "decision_rule": "NONE",
        "explicitly_forbidden": [
            "S1 may never replace, override or become the primary analysis",
            "no rule may switch the primary from the four-scorer 8-cell macro on the "
            "basis of S1 or of any observed data",
            "S1 disagreeing with the primary is reported as a limitation of "
            "interpretation, not as grounds for discarding either estimate",
        ],
        "reporting_note": ("per Clarification C1_1: an additive answer-family affinity "
                           "cancels in the paired contrast because the frozen answer is "
                           "byte-identical across conditions; a scorer-family-by-condition "
                           "interaction would not, and its direction is not established. "
                           "S1 tests whether the primary conclusion depends materially on "
                           "including the OLMo scorer -- it does not establish that no "
                           "such interaction exists, nor any direction or magnitude of "
                           "bias in the four-scorer primary."),
    }


# ---- R5 attrition audit ----------------------------------------------------------------------

def attrition_audit(records: List[dict]) -> Tuple[dict, List[dict]]:
    buckets = defaultdict(lambda: {"n_total": 0, "n_failed": 0})
    for r in records:
        for scope_key in (("scorer", r["scorer_key"]), ("dataset", r["dataset"]),
                          ("condition", r["condition"]),
                          ("scorer_condition", (r["scorer_key"], r["condition"]))):
            b = buckets[scope_key]
            b["n_total"] += 1
            b["n_failed"] += int(not ov.is_valid(r))
    summary = {}
    for (scope, key), v in buckets.items():
        summary.setdefault(scope, {})[str(key)] = {
            "n_total": v["n_total"], "n_failed": v["n_failed"],
            "rate": v["n_failed"] / v["n_total"] if v["n_total"] else None}
    failures = [r for r in records if not ov.is_valid(r)]
    return summary, failures


def write_condition_summary_csv(path: Path, records: List[dict]) -> None:
    buckets = defaultdict(list)  # (scope, scorer, dataset, condition) -> [scores]
    for r in records:
        if not ov.is_valid(r):
            continue
        _s = ov.analysis_score(r)
        buckets[("pooled", "all", "all", r["condition"])].append(_s)
        buckets[("scorer", r["scorer_key"], "all", r["condition"])].append(_s)
        buckets[("dataset", "all", r["dataset"], r["condition"])].append(_s)
        buckets[("scorer_dataset", r["scorer_key"], r["dataset"],
                r["condition"])].append(_s)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scope", "scorer", "dataset", "condition", "mean", "sd", "n"])
        for (scope, scorer, dataset, cond), vals in sorted(buckets.items()):
            arr = np.array(vals)
            w.writerow([scope, scorer, dataset, cond, float(arr.mean()),
                       float(arr.std(ddof=1)) if len(arr) > 1 else 0.0, len(arr)])


def write_contrast_summary_csv(path: Path, diagnostics_point: dict, diagnostics_ci: dict,
                               primary_point: dict, primary_ci: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["contrast", "confirmatory", "scope", "scorer_or_dataset", "mean",
                   "ci_low", "ci_high", "n_bootstrap_reps", "n"])
        w.writerow([contrast_name(*PRIMARY), True, "primary_8_cell_macro", "all",
                   primary_point["macro_average"], primary_ci["ci_low"], primary_ci["ci_high"],
                   primary_ci["n_bootstrap_reps"],
                   sum(v or 0 for v in primary_point["cell_n"].values())])
        for cname, scopes in diagnostics_point.items():
            for scope, keys in scopes.items():
                for key, v in keys.items():
                    c = diagnostics_ci.get(cname, {}).get(scope, {}).get(key, {})
                    w.writerow([cname, False, scope, key if key is not None else "all",
                               v["mean"], c.get("ci_low"), c.get("ci_high"),
                               c.get("n_bootstrap_reps"), v["n"]])


def write_parse_failure_report_md(path: Path, failures: List[dict], n_total: int) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Parse-failure / attrition report (final behavioral study)\n\n")
        f.write(f"{len(failures)} of {n_total} calls flagged (parse failed or ambiguous). "
               f"See score_recovery_pattern_pass.json / final_adjudication.json for the "
               f"recovery and blinded-verification outcome of each.\n\n")
        for r in failures:
            f.write(f"## {r['unit_id']}\n\n")
            f.write(f"- scorer: {r['scorer_key']}\n")
            f.write(f"- dataset/task: {r['dataset']}/{r['source_task_id']} ({r['category']})\n")
            f.write(f"- condition: {r['condition']}\n")
            f.write(f"- status: {r['parse_status']}  error: {r.get('parse_error')}\n\n")
            f.write("```\n" + (r["response"] or "<empty>") + "\n```\n\n")


def write_full_responses_txt(path: Path, records: List[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("FINAL BEHAVIORAL STUDY (578 tasks x 6 conditions x 4 scorers)\n"
               + "=" * 100 + "\n\n")
        for r in records:
            f.write("\n" + "=" * 100 + "\n")
            f.write(f"UNIT ID: {r['unit_id']}\n")
            f.write(f"SCORER: {r['scorer_key']}\n")
            f.write(f"DATASET/TASK ID: {r['dataset']}/{r['source_task_id']}\n")
            f.write(f"CATEGORY: {r['category']}\n")
            f.write(f"CONDITION: {r['condition']}\n")
            f.write(f"PARSED SCORE: {r['parsed_score']}\n")
            f.write(f"PARSE OK: {r['parse_ok']}\n\n")
            f.write("PROMPT\n" + "-" * 100 + "\n" + r.get("prompt", "") + "\n\n")
            f.write("RESPONSE\n" + "-" * 100 + "\n" + (r["response"] or "<empty>") + "\n")


def write_attrition_csv(path: Path, failures: List[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["unit_id", "scorer_key", "dataset", "source_task_id", "condition",
                   "parse_status", "parse_error", "response"])
        for r in failures:
            w.writerow([r["unit_id"], r["scorer_key"], r["dataset"], r["source_task_id"],
                       r["condition"], r["parse_status"], r.get("parse_error"), r["response"]])


# ---- CSV / JSON writers -----------------------------------------------------------------

def write_task_level_csv(path: Path, task_level: List[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["dataset", "task_id", "category", "mean_effect",
                                          "n_scorers"])
        w.writeheader()
        for row in task_level:
            w.writerow(row)


def write_results_csv(path: Path, records: List[dict]) -> None:
    if not records:
        return
    cols = ["unit_id", "dataset", "source_task_id", "category", "question",
           "candidate_answer", "candidate_answer_sha256", "generator_model",
           "generator_revision", "scorer_key", "scorer_model_id", "scorer_revision",
           "condition", "added_context", "parsed_score", "parse_ok", "parse_status",
           "flagged_for_review", "prompt", "response", "batch_size", "generation_seconds",
           "completed_at_utc"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)


# ---- Top-level: one full analysis pass over one measurement basis ------------------------

def analyze_one_basis(records: List[dict], basis_label: str, *,
                      n_bootstrap: int = N_BOOTSTRAP) -> dict:
    rows_by_task, task_ids_by_dataset, task_category, task_prior_use = build_index(records)
    pivot = pivot_scores(records)

    primary_diffs = contrast_diffs(pivot, *PRIMARY, datasets=HELDOUT_DATASETS)
    secondary_diffs = contrast_diffs(pivot, *PRIMARY, datasets=FULL_DATASETS)
    primary_cells = cell_values(primary_diffs)
    secondary_cells = cell_values(secondary_diffs)

    primary_point = macro_average(primary_cells, required_cells(HELDOUT_DATASETS))
    secondary_point = macro_average(secondary_cells, required_cells(FULL_DATASETS))
    primary_trimmed = macro_average(primary_cells, required_cells(HELDOUT_DATASETS), "trimmed")
    secondary_trimmed = macro_average(secondary_cells, required_cells(FULL_DATASETS), "trimmed")

    task_level_heldout = task_level_effects(pivot, *PRIMARY, task_category, HELDOUT_DATASETS)
    task_level_full = task_level_effects(pivot, *PRIMARY, task_category, FULL_DATASETS)

    replicate_stats, n_empty_primary_reps, n_empty_secondary_reps = bootstrap_replicates(
        rows_by_task, task_ids_by_dataset, task_category, n_reps=n_bootstrap)

    diagnostics_point = compute_diagnostics(pivot, FULL_DATASETS)
    diagnostics_ci = {}
    for a, b in ALL_CONTRASTS:
        cname = contrast_name(a, b)
        diagnostics_ci[cname] = {scope: {key: ci95(vals) for key, vals in
                                        replicate_stats[f"diag__{cname}__{scope}"].items()}
                                for scope in DIAGNOSTIC_SCOPES}

    task_ids_heldout = [tid for d in HELDOUT_DATASETS for tid in task_ids_by_dataset.get(d, [])]
    task_ids_full = [tid for d in FULL_DATASETS for tid in task_ids_by_dataset.get(d, [])]
    dataset_of = {tid: d for d, ids in task_ids_by_dataset.items() for tid in ids}

    return {
        "measurement_basis": basis_label,
        "n_records": len(records),
        "primary": {
            "population": "500 fully held-out (arena_hard + wildbench)",
            "contrast": contrast_name(*PRIMARY), "n_cells": N_CELLS_PRIMARY,
            "cell_weight": CELL_WEIGHT_PRIMARY, **primary_point,
            "ci_95": ci95(replicate_stats["primary_macro"]),
            "n_empty_cell_replicates": n_empty_primary_reps,
        },
        "secondary": {
            "population": "all 578 tasks", "contrast": contrast_name(*PRIMARY),
            "n_cells": N_CELLS_SECONDARY, "cell_weight": CELL_WEIGHT_SECONDARY,
            **secondary_point, "ci_95": ci95(replicate_stats["secondary_macro"]),
            "n_empty_cell_replicates": n_empty_secondary_reps,
        },
        "pooled_summaries": {
            "task_weighted": {"heldout_500": task_weighted_pooled(task_level_heldout),
                             "full_578": task_weighted_pooled(task_level_full)},
            "pair_weighted": {"heldout_500": pair_weighted_pooled(primary_diffs),
                             "full_578": pair_weighted_pooled(secondary_diffs)},
            "dataset_wise": dataset_wise(secondary_cells, FULL_DATASETS),
            "scorer_wise": scorer_wise(secondary_cells, FULL_DATASETS),
        },
        "per_condition_levels": {
            "heldout_500": per_condition_levels(records, HELDOUT_DATASETS),
            "full_578": per_condition_levels(records, FULL_DATASETS),
        },
        "task_level_distribution": {
            "heldout_500": {"overall": task_level_distribution_stats(task_level_heldout),
                           "per_dataset": {d: task_level_distribution_stats(
                               [t for t in task_level_heldout if t["dataset"] == d])
                               for d in HELDOUT_DATASETS}},
            "full_578": {"overall": task_level_distribution_stats(task_level_full),
                        "per_dataset": {d: task_level_distribution_stats(
                            [t for t in task_level_full if t["dataset"] == d])
                            for d in FULL_DATASETS}},
        },
        "diagnostics": {"point": diagnostics_point, "ci_95": diagnostics_ci,
                       "note": "non-confirmatory, unadjusted for multiplicity"},
        "S1_three_scorer_sensitivity": s1_three_scorer_sensitivity(
            primary_cells, secondary_cells, replicate_stats,
            primary_point["macro_average"], secondary_point["macro_average"]),
        "robustness": {
            "R1_trimmed_mean": {
                "primary_8_cell": {**primary_trimmed,
                                  "ci_95": ci95(replicate_stats["primary_macro_trimmed"])},
                "secondary_12_cell": {**secondary_trimmed,
                                     "ci_95": ci95(replicate_stats["secondary_macro_trimmed"])},
                "trim_fraction": TRIM_FRACTION,
            },
            "R2_leave_one_task_out": {
                "primary_500": loto(rows_by_task, task_ids_heldout, dataset_of, HELDOUT_DATASETS),
                "secondary_578": loto(rows_by_task, task_ids_full, dataset_of, FULL_DATASETS),
            },
            "R4_prior_use_descriptive": prior_use_descriptive(task_level_full, task_prior_use),
        },
        "_internal": {"task_level_heldout": task_level_heldout, "task_level_full": task_level_full,
                     "records": records},
    }


def make_figures(out_dir: Path, complete_case_result: Optional[dict],
                 adjudicated_result: Optional[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result = adjudicated_result or complete_case_result
    if result is None:
        return
    records = result["_internal"]["records"]

    try:
        import sys as _sys
        _sys.path.insert(0, str(REPO / "paper_assets" / "figures"))
        from figstyle import BLUE, ORANGE, AQUA, VIOLET, MUTED  # validated 4-slot palette
    except Exception:
        BLUE, ORANGE, AQUA, VIOLET, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7", "#8a8985"
    scorer_color = {"llama": BLUE, "qwen": ORANGE, "gemma": AQUA, "olmo32b": VIOLET}

    conditions = ["no_history", "self_low_2", "other_low_2", "unrelated_low_2",
                 "verbal_negative", "self_high_10"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.2
    x = np.arange(len(conditions))
    for i, scorer in enumerate(SCORERS):
        by_cond = defaultdict(list)
        for r in records:
            if ov.is_valid(r) and r["scorer_key"] == scorer:
                by_cond[r["condition"]].append(ov.analysis_score(r))
        m = [np.mean(by_cond[c]) if by_cond[c] else 0 for c in conditions]
        ax.bar(x + (i - 1.5) * width, m, width, label=scorer, color=scorer_color[scorer])
    ax.set_xticks(x)
    ax.set_xticklabels(conditions, rotation=30, ha="right")
    ax.set_ylabel("Mean parsed score")
    ax.set_title("Model-wise condition means (final study, full 578)")
    ax.legend(ncol=4, fontsize=7)
    plt.tight_layout()
    fig.savefig(out_dir / "model_condition_means.png", dpi=150)
    fig.savefig(out_dir / "model_condition_means.pdf")
    plt.close(fig)

    tl = result["_internal"]["task_level_full"]
    fig, ax = plt.subplots(figsize=(8, 4))
    effects = [t["mean_effect"] for t in tl]
    ax.hist(effects, bins=30, color=BLUE, edgecolor="white")
    ax.axvline(0, color="black", linewidth=1)
    ax.set_xlabel(f"{contrast_name(*PRIMARY)} (task-level mean across scorers)")
    ax.set_ylabel("Number of tasks")
    ax.set_title("Task-level primary-effect distribution (full 578)")
    plt.tight_layout()
    fig.savefig(out_dir / "task_level_primary_effects.png", dpi=150)
    fig.savefig(out_dir / "task_level_primary_effects.pdf")
    plt.close(fig)

    if complete_case_result is not None and adjudicated_result is not None:
        fig, ax = plt.subplots(figsize=(5, 4))
        labels = ["complete_case", "adjudicated"]
        means = [complete_case_result["primary"]["macro_average"],
                adjudicated_result["primary"]["macro_average"]]
        cis = [complete_case_result["primary"]["ci_95"], adjudicated_result["primary"]["ci_95"]]
        lo = [m - c["ci_low"] if m is not None and c["ci_low"] is not None else 0
             for m, c in zip(means, cis)]
        hi = [c["ci_high"] - m if m is not None and c["ci_high"] is not None else 0
             for m, c in zip(means, cis)]
        ax.bar(labels, [m or 0 for m in means], yerr=[lo, hi], color=[MUTED, BLUE], capsize=4)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_ylabel(f"{contrast_name(*PRIMARY)} macro average")
        ax.set_title("Primary estimand: measurement-basis sensitivity (R3)")
        plt.tight_layout()
        fig.savefig(out_dir / "measurement_basis_sensitivity.png", dpi=150)
        fig.savefig(out_dir / "measurement_basis_sensitivity.pdf")
        plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records-adjudicated",
                    default=str(REPO / "results/final_behavioral_study_adjudicated"
                                       "/raw_results_adjudicated.jsonl"))
    ap.add_argument("--records-complete-case",
                    default=str(REPO / "results/final_behavioral_study/raw_results.jsonl"))
    ap.add_argument("--out", default=str(REPO / "results/final_behavioral_study"))
    ap.add_argument("--n-bootstrap", type=int, default=N_BOOTSTRAP)
    ap.add_argument("--skip-figures", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    adjudicated_path = Path(args.records_adjudicated)
    complete_case_path = Path(args.records_complete_case)

    results = {}
    if complete_case_path.exists():
        results["complete_case"] = analyze_one_basis(load_records(complete_case_path),
                                                     "complete_case", n_bootstrap=args.n_bootstrap)
    if adjudicated_path.exists():
        results["adjudicated"] = analyze_one_basis(load_records(adjudicated_path), "adjudicated",
                                                   n_bootstrap=args.n_bootstrap)

    if not results:
        raise SystemExit(f"neither {adjudicated_path} nor {complete_case_path} exists yet -- "
                         f"run the collection pipeline first")

    primary_basis_label = "adjudicated" if "adjudicated" in results else "complete_case"
    primary_result = results[primary_basis_label]

    all_records = primary_result["_internal"]["records"]
    write_results_csv(out_dir / "results.csv", all_records)
    write_task_level_csv(out_dir / "task_level_effects_heldout_500.csv",
                        primary_result["_internal"]["task_level_heldout"])
    write_task_level_csv(out_dir / "task_level_effects_full_578.csv",
                        primary_result["_internal"]["task_level_full"])
    write_task_level_csv(out_dir / "task_level_effects.csv",  # frozen deliverable name
                        primary_result["_internal"]["task_level_full"])
    attrition_summary, failures = attrition_audit(all_records)
    write_attrition_csv(out_dir / "parse_failure_audit.csv", failures)
    write_parse_failure_report_md(out_dir / "parse_failure_report.md", failures, len(all_records))
    write_full_responses_txt(out_dir / "full_responses.txt", all_records)
    write_condition_summary_csv(out_dir / "condition_summary.csv", all_records)
    write_contrast_summary_csv(out_dir / "contrast_summary.csv",
                              primary_result["diagnostics"]["point"],
                              primary_result["diagnostics"]["ci_95"],
                              primary_result["primary"], primary_result["primary"]["ci_95"])

    output = {basis: {k: v for k, v in r.items() if k != "_internal"}
             for basis, r in results.items()}

    # Frozen deliverable names (plan v2 .deliverables): one file per population, sourced
    # from the primary (adjudicated-if-available) measurement basis.
    with open(out_dir / "primary_heldout_500_analysis.json", "w", encoding="utf-8") as f:
        json.dump({"measurement_basis": primary_basis_label,
                  "primary": output[primary_basis_label]["primary"],
                  "task_level_distribution_heldout_500":
                      output[primary_basis_label]["task_level_distribution"]["heldout_500"],
                  "robustness": output[primary_basis_label]["robustness"]},
                 f, ensure_ascii=False, indent=2, default=str)
    with open(out_dir / "secondary_full_578_analysis.json", "w", encoding="utf-8") as f:
        json.dump({"measurement_basis": primary_basis_label,
                  "secondary": output[primary_basis_label]["secondary"],
                  "task_level_distribution_full_578":
                      output[primary_basis_label]["task_level_distribution"]["full_578"],
                  "pooled_summaries": output[primary_basis_label]["pooled_summaries"],
                  "diagnostics": output[primary_basis_label]["diagnostics"]},
                 f, ensure_ascii=False, indent=2, default=str)
    output["primary_measurement_basis"] = primary_basis_label
    output["attrition_summary"] = attrition_summary
    # Amendment A5 point 7: missingness by scorer x dataset x condition split by reason, and
    # the retained-pair counts the frozen paired complete-case rule actually depends on.
    # Reported ALONGSIDE the frozen R5 differential-attrition audit above, not instead of it.
    output["a5_missingness_by_cell"] = ov.missingness_report(all_records)
    output["a5_retained_pairs"] = {
        f"{a}_vs_{b}": ov.retained_pairs(all_records, a, b)
        for a, b in [PRIMARY] + DIAGNOSTIC_CONTRASTS
    }
    output["n_attrition_records_flagged"] = len(failures)
    output["design_constants"] = {
        "scorers": SCORERS, "heldout_datasets": HELDOUT_DATASETS,
        "full_datasets": FULL_DATASETS, "primary_contrast": contrast_name(*PRIMARY),
        "all_contrasts": [contrast_name(a, b) for a, b in ALL_CONTRASTS],
        "n_cells_primary": N_CELLS_PRIMARY, "n_cells_secondary": N_CELLS_SECONDARY,
        "bootstrap_n_replicates": args.n_bootstrap, "bootstrap_seed": BOOTSTRAP_SEED,
        "trim_fraction": TRIM_FRACTION,
        "s1_scorers": S1_SCORERS, "s1_n_cells_primary": S1_N_CELLS_PRIMARY,
        "s1_n_cells_secondary": S1_N_CELLS_SECONDARY,
    }
    with open(out_dir / "final_analysis_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    bootstrap_config = {
        "n_replicates": args.n_bootstrap, "seed": BOOTSTRAP_SEED,
        "method": "stratified task-cluster bootstrap, shared draws across every statistic",
        "clustering": "resampling unit is (dataset, source_task_id); every scorer x "
                      "condition row for a resampled task travels together",
        "stratification": "independent resampling within each of mtbench/arena_hard/"
                          "wildbench, drawing the same number of tasks as that stratum "
                          "contains, every replicate, regardless of which estimand is "
                          "being computed from it",
        "ci": "2.5th/97.5th percentile of the replicate statistic",
        "empty_cell_rule": "average over non-empty cells in that replicate; count of "
                           "affected replicates is reported per estimand (E5)",
    }
    with open(out_dir / "bootstrap_config.json", "w", encoding="utf-8") as f:
        json.dump(bootstrap_config, f, ensure_ascii=False, indent=2)

    if not args.skip_figures:
        make_figures(out_dir, results.get("complete_case"), results.get("adjudicated"))

    summary = {
        "primary_measurement_basis": primary_basis_label,
        "primary_macro_average": primary_result["primary"]["macro_average"],
        "primary_ci_95": primary_result["primary"]["ci_95"],
        "primary_n_cells": N_CELLS_PRIMARY,
        "secondary_macro_average": primary_result["secondary"]["macro_average"],
        "secondary_ci_95": primary_result["secondary"]["ci_95"],
        "n_records": primary_result["n_records"],
        "n_attrition_records_flagged": len(failures),
        "bases_available": list(results.keys()),
        "no_data_dependent_stopping_or_post_hoc_removal": True,
    }
    print(json.dumps(summary, indent=2, default=str))
    print(f"\n[save] {out_dir / 'final_analysis_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
