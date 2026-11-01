"""Export the recorded results used by the project page into docs/assets/data.js.

Read-only over results/. Nothing is re-run; every number on the page comes from a
file listed in SOURCES below. Re-run after any change to those files:

    python tools/build_site_data.py
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
OUT = ROOT / "docs" / "assets" / "data.js"

SOURCES = [
    "results/behavioral/merged_raw_results.jsonl",
    "results/tables/t2_primary_by_scorer.csv",
    "results/tables/t3_primary_by_dataset.csv",
    "results/tables/t4_primary_scorer_x_dataset.csv",
    "results/figure_inputs/headline_metrics.json",
    "results/figure_inputs/delta_distribution.csv",
    "results/figure_inputs/jacobian_tokens.csv",
    "results/figure_inputs/mechanistic_summary.json",
    "results/mechanistic/readout_layer_summary.json",
    "results/silence/silence_summary.json",
]

CONDITIONS = ["no_history", "self_low_2", "other_low_2", "unrelated_low_2",
              "verbal_negative", "self_high_10"]
SIX_CONDITION_SCORERS = ["llama", "qwen", "gemma"]
EXAMPLES = [("mtbench", "101", "llama"), ("arena_hard", "dcac3317be714a64", "qwen")]


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main():
    raw = [json.loads(l) for l in open(R / "behavioral/merged_raw_results.jsonl")]

    # Condition means over the three scorers that ran all six conditions, so every
    # bar averages the same scorer panel.
    acc = defaultdict(list)
    for r in raw:
        if r["analysis_valid"] and r["scorer_key"] in SIX_CONDITION_SCORERS:
            acc[("all", r["condition"])].append(r["analysis_score"])
            acc[(r["scorer_key"], r["condition"])].append(r["analysis_score"])
    cond_means = {
        s: {c: round(sum(acc[(s, c)]) / len(acc[(s, c)]), 3) for c in CONDITIONS}
        for s in ["all"] + SIX_CONDITION_SCORERS
    }
    cond_n = {c: len(acc[("all", c)]) for c in CONDITIONS}

    # Recorded examples: same frozen answer bytes under all six conditions.
    curated = json.load(open(R / "figure_inputs/real_example_candidates.json"))["examples"]
    examples = []
    for ds, tid, scorer in EXAMPLES:
        recs = {r["condition"]: r for r in raw
                if r["dataset"] == ds and r["source_task_id"] == tid and r["scorer_key"] == scorer}
        labels = next((e["conditions"] for e in curated
                       if e["task_id"] == tid and e["scorer"] == scorer), {})
        first = recs["no_history"]
        assert len({r["candidate_answer_sha256"] for r in recs.values()}) == 1
        examples.append({
            "dataset": ds, "task_id": tid, "scorer": scorer, "category": first["category"],
            "question": first["question"], "answer": first["candidate_answer"],
            "answer_sha256": first["candidate_answer_sha256"],
            "conditions": {c: {
                "sentence": recs[c]["added_context"] or None,
                "score": recs[c]["analysis_score"],
                "justification": recs[c]["response"].strip(),
                "mention_label": (labels.get(c) or {}).get("context_mention_label"),
            } for c in CONDITIONS},
        })

    scorers = {r["scorer"]: {"mean": float(r["pair_weighted_mean"]),
                             "ci": [float(r["ci_low_pair_weighted"]), float(r["ci_high_pair_weighted"])],
                             "n": int(r["n_pairs"])}
               for r in read_csv(R / "tables/t2_primary_by_scorer.csv")}
    datasets = {r["dataset"]: {"mean": float(r["pair_weighted_mean"]),
                               "ci": [float(r["ci_low_pair_weighted"]), float(r["ci_high_pair_weighted"])],
                               "n": int(r["n_pairs"])}
                for r in read_csv(R / "tables/t3_primary_by_dataset.csv")}
    cells = [{"dataset": r["dataset"], "scorer": r["scorer"], "mean": float(r["cell_mean"]),
              "n": int(r["n_retained_pairs"])}
             for r in read_csv(R / "tables/t4_primary_scorer_x_dataset.csv")]
    deltas = [float(r["panel_delta"]) for r in read_csv(R / "figure_inputs/delta_distribution.csv")
              if r["panel_delta"]]

    readout = json.load(open(R / "mechanistic/readout_layer_summary.json"))
    layers = [{"layer": b["layer"], "jsd": round(b["jsd_bits_mean"], 5), "sd": round(b["jsd_bits_sd"], 5)}
              for b in readout["by_layer"]]

    tokens = defaultdict(lambda: defaultdict(lambda: {"promoted": [], "suppressed": []}))
    for r in read_csv(R / "figure_inputs/jacobian_tokens.csv"):
        if int(r["rank"]) <= 6:
            tokens[r["contrast_key"]][r["layer"]][r["direction"]].append(
                [r["token_text"], round(float(r["value_mean_delta_logprob"]), 3),
                 round(float(r["consistency_sign_fraction"]), 3)])

    mech = json.load(open(R / "figure_inputs/mechanistic_summary.json"))["llama_positive_case_study"]
    headline = json.load(open(R / "figure_inputs/headline_metrics.json"))
    silence = json.load(open(R / "silence/silence_summary.json"))

    data = {
        "_sources": SOURCES,
        "_basis": headline["_basis"],
        "headline": {"effect": headline["primary_contrast"]["mean_shift_points"],
                     "ci": headline["primary_contrast"]["ci95"],
                     "pairs": headline["primary_contrast"]["n_matched_pairs"],
                     "tasks_positive": headline["matched_task_result"],
                     "thresholds": headline["delta_thresholds_panel_averaged"],
                     "counts": headline["counts"]},
        "conditionMeans": cond_means, "conditionN": cond_n,
        "scorers": scorers, "datasets": datasets, "cells": cells, "deltas": deltas,
        "silence": silence["condition"],
        "layers": layers, "selectedLayer": readout["selected_layer"],
        "eligibleBand": readout["eligible_layers"], "excludedLayers": readout["final_four_layers_excluded"],
        "tokens": tokens,
        "patching": {"p72": mech["patching_72_task_replication"], "p24": mech["patching_24_task"],
                     "L2": {k: v for k, v in mech["early_layer_L2_comparison"].items() if "->" in k},
                     "paired": mech["early_layer_L2_comparison"]["paired_L24_minus_L2"],
                     "steering": {k: mech["steering_null"][k] for k in ("verdict", "steer", "vs_random_direction")}},
        "examples": examples,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("// Generated by tools/build_site_data.py from recorded results. Do not edit.\n"
                   "window.SI_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    print("condition means (3 scorers):", cond_means["all"])


if __name__ == "__main__":
    main()
