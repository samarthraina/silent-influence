#!/usr/bin/env python3
"""Analysis for the scaled silent-influence experiment: contrasts, task-cluster bootstrap
CIs, task-level effect distribution, parse-failure audit, figures.

Bootstrap methodology (recorded verbatim in bootstrap_config.json):
  10,000 replicates, seed 20260816. Each replicate resamples task IDs WITH replacement,
  independently within each dataset stratum (same number of tasks drawn as that stratum
  has), and every row belonging to a resampled task (every scorer, every condition) is
  carried into the replicate together -- individual scorer/condition cells are never
  resampled independently of their task. Every reported statistic (pooled, model-wise,
  dataset-wise, model x dataset) for every contrast is recomputed from the SAME resampled
  task-set within a replicate, so the whole set of CIs comes from one bootstrap
  distribution over task-clusters, not 100+ independent draws.

Every contrast uses complete matched pairs only: a (scorer, dataset, task) cell counts
toward a contrast only if both of that contrast's conditions parsed successfully for that
cell. N is reported per contrast per scope because it varies (a scorer that fails to parse
more often on one condition than another shrinks its own N, not anyone else's). No score is
ever imputed, and no task is ever removed post hoc based on its own result.

    python scripts/analyze_scaled.py --records results/scaled_silent_influence/raw_results.jsonl --out results/scaled_silent_influence
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

CONTRASTS: List[Tuple[str, str]] = [
    ("no_history", "self_low_2"),          # primary
    ("other_low_2", "self_low_2"),
    ("no_history", "unrelated_low_2"),
    ("no_history", "verbal_negative"),
    ("self_high_10", "self_low_2"),
    ("self_high_10", "no_history"),
    ("unrelated_low_2", "self_low_2"),
]
PRIMARY = CONTRASTS[0]
N_BOOTSTRAP = 10_000
BOOTSTRAP_SEED = 20260816

SCORER_COLOR = {"llama": "#2563EB", "qwen": "#D97706", "gemma": "#16A34A"}
SCORER_LABEL = {"llama": "Llama-3.1-8B-Instruct", "qwen": "Qwen3-8B",
               "gemma": "Gemma-2-9B-IT"}


def contrast_name(a: str, b: str) -> str:
    return f"{a}_minus_{b}"


def load_records(path: Path) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def build_index(records: List[dict]):
    """rows_by_task[(dataset, task_id)] = list of records; task_ids_by_dataset[dataset] =
    sorted unique task ids. Uses slot_task_id, the stable identifier from the frozen
    selection (identical to generated_task_id unless a substitution occurred)."""
    rows_by_task: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    task_ids_by_dataset: Dict[str, List[str]] = defaultdict(set)
    task_category: Dict[Tuple[str, str], str] = {}
    for r in records:
        key = (r["dataset"], r["slot_task_id"])
        rows_by_task[key].append(r)
        task_ids_by_dataset[r["dataset"]].add(r["slot_task_id"])
        task_category[key] = r["category"]
    task_ids_by_dataset = {d: sorted(v) for d, v in task_ids_by_dataset.items()}
    return dict(rows_by_task), task_ids_by_dataset, task_category


def pivot_scores(rows: List[dict]) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """(scorer, dataset, task_id) -> {condition: parsed_score}, parse_ok rows only."""
    pivot: Dict[Tuple[str, str, str], Dict[str, float]] = defaultdict(dict)
    for r in rows:
        if not r["parse_ok"]:
            continue
        key = (r["scorer_key"], r["dataset"], r["slot_task_id"])
        pivot[key][r["condition"]] = r["parsed_score"]
    return pivot


def contrast_diffs(pivot, a: str, b: str) -> List[Tuple[str, str, str, float]]:
    """[(scorer, dataset, task_id, a-b), ...] for cells where both a and b parsed ok."""
    out = []
    for (scorer, dataset, task_id), scores in pivot.items():
        if a in scores and b in scores:
            out.append((scorer, dataset, task_id, scores[a] - scores[b]))
    return out


def agg(diffs: List[Tuple[str, str, str, float]], key_fn) -> Dict:
    buckets: Dict = defaultdict(list)
    for scorer, dataset, task_id, d in diffs:
        buckets[key_fn(scorer, dataset)].append(d)
    return {k: {"mean": float(np.mean(v)), "n": len(v)} for k, v in buckets.items()}


SCOPE_KEYS = {
    "pooled": lambda s, d: None,
    "model": lambda s, d: s,
    "dataset": lambda s, d: d,
    "model_dataset": lambda s, d: (s, d),
}


def compute_point_stats(rows: List[dict]) -> Dict:
    pivot = pivot_scores(rows)
    stats = {}
    for a, b in CONTRASTS:
        cname = contrast_name(a, b)
        diffs = contrast_diffs(pivot, a, b)
        stats[cname] = {scope: agg(diffs, fn) for scope, fn in SCOPE_KEYS.items()}
    return stats


def task_level_primary_effects(pivot, primary_a: str, primary_b: str, task_category):
    """Per-task effect, averaged across scorers that have a complete pair for that task."""
    by_task: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for (scorer, dataset, task_id), scores in pivot.items():
        if primary_a in scores and primary_b in scores:
            by_task[(dataset, task_id)].append(scores[primary_a] - scores[primary_b])
    out = []
    for (dataset, task_id), vals in by_task.items():
        out.append({"dataset": dataset, "task_id": task_id,
                    "category": task_category.get((dataset, task_id)),
                    "mean_effect": float(np.mean(vals)), "n_scorers": len(vals)})
    return sorted(out, key=lambda r: -r["mean_effect"])


def bootstrap(rows_by_task, task_ids_by_dataset, seed=BOOTSTRAP_SEED, n_reps=N_BOOTSTRAP):
    """One resampling draw per replicate, shared across every contrast/scope computed
    from it. Returns replicate_stats[contrast_name][scope][key] -> list of n_reps means."""
    rng = np.random.default_rng(seed)
    datasets = sorted(task_ids_by_dataset)
    replicate_stats = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for _ in range(n_reps):
        resampled_rows = []
        for d in datasets:
            ids = task_ids_by_dataset[d]
            sampled = rng.choice(ids, size=len(ids), replace=True)
            for tid in sampled:
                resampled_rows.extend(rows_by_task[(d, tid)])

        pivot = pivot_scores(resampled_rows)
        for a, b in CONTRASTS:
            cname = contrast_name(a, b)
            diffs = contrast_diffs(pivot, a, b)
            for scope, fn in SCOPE_KEYS.items():
                for key, v in agg(diffs, fn).items():
                    replicate_stats[cname][scope][key].append(v["mean"])

    return replicate_stats


def ci_from_replicates(replicate_stats) -> Dict:
    out = defaultdict(lambda: defaultdict(dict))
    for cname, scopes in replicate_stats.items():
        for scope, keys in scopes.items():
            for key, vals in keys.items():
                arr = np.array(vals)
                out[cname][scope][key] = {
                    "ci_low": float(np.percentile(arr, 2.5)),
                    "ci_high": float(np.percentile(arr, 97.5)),
                    "n_bootstrap_reps": len(arr),
                }
    return out


def scope_key_to_label(scope: str, key) -> Tuple[str, str]:
    """(scorer_label, dataset_label) for CSV rows; 'all' where the scope doesn't split."""
    if scope == "pooled":
        return "all", "all"
    if scope == "model":
        return key, "all"
    if scope == "dataset":
        return "all", key
    if scope == "model_dataset":
        return key[0], key[1]
    raise ValueError(scope)


def write_contrast_summary_csv(path: Path, point_stats: Dict, ci: Dict):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scope", "scorer", "dataset", "contrast", "mean", "ci_low", "ci_high",
                   "n_bootstrap_reps", "n"])
        for cname, scopes in point_stats.items():
            for scope, keys in scopes.items():
                for key, v in keys.items():
                    scorer_label, dataset_label = scope_key_to_label(scope, key)
                    c = ci.get(cname, {}).get(scope, {}).get(key, {})
                    w.writerow([scope, scorer_label, dataset_label, cname,
                               v["mean"], c.get("ci_low"), c.get("ci_high"),
                               c.get("n_bootstrap_reps"), v["n"]])


def write_condition_summary_csv(path: Path, records: List[dict]):
    buckets = defaultdict(list)  # (scope, scorer, dataset, condition) -> [scores]
    for r in records:
        if not r["parse_ok"]:
            continue
        buckets[("pooled", "all", "all", r["condition"])].append(r["parsed_score"])
        buckets[("model", r["scorer_key"], "all", r["condition"])].append(r["parsed_score"])
        buckets[("dataset", "all", r["dataset"], r["condition"])].append(r["parsed_score"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scope", "scorer", "dataset", "condition", "mean", "sd", "n"])
        for (scope, scorer, dataset, cond), vals in sorted(buckets.items()):
            arr = np.array(vals)
            w.writerow([scope, scorer, dataset, cond, float(arr.mean()),
                       float(arr.std(ddof=1)) if len(arr) > 1 else 0.0, len(arr)])


def write_results_csv(path: Path, records: List[dict]):
    if not records:
        return
    cols = ["unit_id", "dataset", "slot_task_id", "generated_task_id", "is_substitution",
           "category", "question", "candidate_answer", "candidate_answer_sha256",
           "generator_model", "generator_revision", "scorer_key", "scorer_model_id",
           "scorer_revision", "condition", "added_context", "parsed_score", "parse_ok",
           "parse_status", "flagged_for_review", "prompt", "response",
           "generation_seconds", "completed_at_utc"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)


def write_parse_failure_audit(csv_path: Path, md_path: Path, records: List[dict]):
    failures = [r for r in records if not r["parse_ok"] or r.get("flagged_for_review")]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["unit_id", "scorer_key", "dataset", "slot_task_id", "condition",
                   "parse_status", "parse_error", "response"])
        for r in failures:
            w.writerow([r["unit_id"], r["scorer_key"], r["dataset"], r["slot_task_id"],
                       r["condition"], r["parse_status"], r.get("parse_error"),
                       r["response"]])
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Parse-failure audit\n\n{len(failures)} of {len(records)} calls "
               f"flagged (parse failed or ambiguous).\n\n")
        for r in failures:
            f.write(f"## {r['unit_id']}\n\n")
            f.write(f"- scorer: {SCORER_LABEL.get(r['scorer_key'], r['scorer_key'])}\n")
            f.write(f"- dataset/task: {r['dataset']}/{r['slot_task_id']} "
                   f"({r['category']})\n")
            f.write(f"- condition: {r['condition']}\n")
            f.write(f"- status: {r['parse_status']}  error: {r.get('parse_error')}\n\n")
            f.write("```\n" + (r["response"] or "<empty>") + "\n```\n\n")


def write_full_responses_txt(path: Path, records: List[dict]):
    with open(path, "w", encoding="utf-8") as f:
        f.write("SCALED SILENT-INFLUENCE EXPERIMENT\n" + "=" * 100 + "\n\n")
        for r in records:
            f.write("\n" + "=" * 100 + "\n")
            f.write(f"UNIT ID: {r['unit_id']}\n")
            f.write(f"SCORER: {SCORER_LABEL.get(r['scorer_key'], r['scorer_key'])}\n")
            f.write(f"DATASET/TASK ID: {r['dataset']}/{r['slot_task_id']}\n")
            f.write(f"CATEGORY: {r['category']}\n")
            f.write(f"CONDITION: {r['condition']}\n")
            f.write(f"PARSED SCORE: {r['parsed_score']}\n")
            f.write(f"PARSE OK: {r['parse_ok']}\n\n")
            f.write("PROMPT\n" + "-" * 100 + "\n" + r["prompt"] + "\n\n")
            f.write("RESPONSE\n" + "-" * 100 + "\n" + (r["response"] or "<empty>") + "\n")


def make_figures(out_dir: Path, records: List[dict], task_level: List[dict]):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    conditions = ["no_history", "self_low_2", "other_low_2", "unrelated_low_2",
                 "verbal_negative", "self_high_10"]

    # Pooled condition means.
    pooled = defaultdict(list)
    for r in records:
        if r["parse_ok"]:
            pooled[r["condition"]].append(r["parsed_score"])
    fig, ax = plt.subplots(figsize=(7, 4))
    means = [np.mean(pooled[c]) if pooled[c] else 0 for c in conditions]
    sems = [np.std(pooled[c], ddof=1) / np.sqrt(len(pooled[c])) if len(pooled[c]) > 1
           else 0 for c in conditions]
    ax.bar(conditions, means, yerr=sems, color="#2563EB", capsize=4)
    ax.set_ylabel("Mean parsed score")
    ax.set_title("Pooled condition means (scaled experiment)")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    fig.savefig(out_dir / "pooled_condition_means.png", dpi=150)
    plt.close(fig)

    # Per-model condition means.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    width = 0.25
    x = np.arange(len(conditions))
    for i, scorer in enumerate(("llama", "qwen", "gemma")):
        by_cond = defaultdict(list)
        for r in records:
            if r["parse_ok"] and r["scorer_key"] == scorer:
                by_cond[r["condition"]].append(r["parsed_score"])
        m = [np.mean(by_cond[c]) if by_cond[c] else 0 for c in conditions]
        ax.bar(x + (i - 1) * width, m, width, label=SCORER_LABEL[scorer],
              color=SCORER_COLOR[scorer])
    ax.set_xticks(x)
    ax.set_xticklabels(conditions, rotation=30, ha="right")
    ax.set_ylabel("Mean parsed score")
    ax.set_title("Model-wise condition means (scaled experiment)")
    ax.legend()
    plt.tight_layout()
    fig.savefig(out_dir / "model_condition_means.png", dpi=150)
    plt.close(fig)

    # Task-level primary-contrast effect distribution.
    fig, ax = plt.subplots(figsize=(8, 4))
    effects = [t["mean_effect"] for t in task_level]
    ax.hist(effects, bins=20, color="#2563EB", edgecolor="white")
    ax.axvline(0, color="black", linewidth=1)
    ax.set_xlabel(f"{contrast_name(*PRIMARY)} (task-level mean across scorers)")
    ax.set_ylabel("Number of tasks")
    ax.set_title("Task-level primary-effect distribution")
    plt.tight_layout()
    fig.savefig(out_dir / "task_level_primary_effects.png", dpi=150)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=str(REPO / "results/scaled_silent_influence/raw_results.jsonl"))
    ap.add_argument("--out", default=str(REPO / "results/scaled_silent_influence"))
    ap.add_argument("--n-bootstrap", type=int, default=N_BOOTSTRAP)
    ap.add_argument("--skip-figures", action="store_true")
    args = ap.parse_args()

    records = load_records(Path(args.records))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows_by_task, task_ids_by_dataset, task_category = build_index(records)
    point_stats = compute_point_stats(records)
    pivot = pivot_scores(records)
    task_level = task_level_primary_effects(pivot, *PRIMARY, task_category)

    replicate_stats = bootstrap(rows_by_task, task_ids_by_dataset,
                                seed=BOOTSTRAP_SEED, n_reps=args.n_bootstrap)
    ci = ci_from_replicates(replicate_stats)

    write_results_csv(out_dir / "results.csv", records)
    write_contrast_summary_csv(out_dir / "contrast_summary.csv", point_stats, ci)
    write_condition_summary_csv(out_dir / "condition_summary.csv", records)
    with open(out_dir / "task_level_effects.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["dataset", "task_id", "category", "mean_effect",
                                          "n_scorers"])
        w.writeheader()
        for row in task_level:
            w.writerow(row)
    write_parse_failure_audit(out_dir / "parse_failure_audit.csv",
                              out_dir / "parse_failure_report.md", records)
    write_full_responses_txt(out_dir / "full_responses.txt", records)

    n_parse_fail = sum(1 for r in records if not r["parse_ok"])
    n_flagged = sum(1 for r in records if r.get("flagged_for_review"))
    effects = np.array([t["mean_effect"] for t in task_level])
    primary_cname = contrast_name(*PRIMARY)
    primary_pooled = point_stats[primary_cname]["pooled"].get(None, {"mean": None, "n": 0})
    primary_ci = ci.get(primary_cname, {}).get("pooled", {}).get(None, {})

    summary = {
        "experiment": "scaled_silent_influence",
        "n_records": len(records),
        "n_tasks": sum(len(v) for v in task_ids_by_dataset.values()),
        "n_scorers": len({r["scorer_key"] for r in records}),
        "n_conditions": len({r["condition"] for r in records}),
        "n_parse_failures": n_parse_fail,
        "n_flagged_for_review": n_flagged,
        "primary_contrast": primary_cname,
        "primary_pooled_mean": primary_pooled["mean"],
        "primary_pooled_n": primary_pooled["n"],
        "primary_ci_low": primary_ci.get("ci_low"),
        "primary_ci_high": primary_ci.get("ci_high"),
        "task_level_n_tasks": len(effects),
        "task_level_fraction_positive": float((effects > 0).mean()) if len(effects) else None,
        "task_level_fraction_ge1": float((effects >= 1).mean()) if len(effects) else None,
        "task_level_fraction_ge2": float((effects >= 2).mean()) if len(effects) else None,
        "no_data_dependent_stopping_or_post_hoc_removal": True,
    }
    with open(out_dir / "analysis_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    bootstrap_config = {
        "n_replicates": args.n_bootstrap, "seed": BOOTSTRAP_SEED,
        "method": "stratified task-cluster bootstrap",
        "clustering": "resampling unit is (dataset, task_id); every scorer x condition "
                      "row for a resampled task is retained together",
        "stratification": "independent resampling within each dataset stratum, drawing "
                          "the same number of tasks as that stratum contains",
        "ci": "2.5th/97.5th percentile of the replicate statistic",
        "shared_draws": "one resampled task-set per replicate feeds every contrast and "
                        "every scope (pooled/model/dataset/model_dataset)",
    }
    with open(out_dir / "bootstrap_config.json", "w", encoding="utf-8") as f:
        json.dump(bootstrap_config, f, ensure_ascii=False, indent=2)

    if not args.skip_figures:
        make_figures(out_dir, records, task_level)

    print(json.dumps(summary, indent=2))
    print(f"\n[save] {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
