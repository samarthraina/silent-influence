"""Assemble the read-only figure-input bundle. No model, no GPU, no new inference.

Every value is copied or directly tabulated from an already-verified artifact. Nothing is
rerun, refitted, bootstrapped or modified; the only computation is selection, joining and
counting over completed outputs.
"""
import collections
import csv
import json
import os
import pathlib
import sys

import numpy as np

# Package-relative: <package>/code/figures/<this file> -> <package>
ROOT = pathlib.Path(os.environ.get(
    "SI_SUPPLEMENT_ROOT", str(pathlib.Path(__file__).resolve().parents[2])))
sys.path.insert(0, str(ROOT / "Code/GitHub/silent-influence/src"))
sys.path.insert(0, str(ROOT / "Code/GitHub/silent-influence/scripts"))
import analyze_final_study as A
from silent_influence import scaled_conditions as sc

W = ROOT / "results"
OUT = ROOT / "results/figure_inputs"
OUT.mkdir(parents=True, exist_ok=True)

RES = json.loads((W / "analysis/final_analysis_results.json").read_text(encoding="utf-8"))
CC = RES["complete_case"]
records = A.load_records(W / "merged_raw_results.jsonl")
piv = A.pivot_scores(records)
by_unit = {(r["scorer_key"], r["dataset"], r["source_task_id"], r["condition"]): r
           for r in records}
task_level = list(csv.DictReader(
    (W / "analysis/task_level_effects_full_578.csv").open(encoding="utf-8")))
tl = {(r["dataset"], r["task_id"]): float(r["mean_effect"]) for r in task_level}
eff = np.array([v for v in tl.values()])
sj = list(csv.DictReader((W / "silence_run/_from_archive/silence_joined.csv").open(encoding="utf-8")))
conc = [r for r in sj if r["concordant"] == "True"]
agree = json.loads((W / "silence_run/_from_archive/agreement.json").read_text(encoding="utf-8"))

own_delta = {}
for (s, ds, t), c in piv.items():
    if "no_history" in c and "self_low_2" in c:
        own_delta[(s, ds, t)] = c["no_history"] - c["self_low_2"]

# ---------------------------------------------------------------- 1. headline
sl_items = [r for r in conc if r["condition"] == "self_low_2"]
nh_items = [r for r in conc if r["condition"] == "no_history"]
ack_sl = sum(1 for r in sl_items if r["J1_label"] in ("A", "D"))
big = [r for r in sl_items
       if own_delta.get((r["scorer_key"], r["dataset"], r["source_task_id"]), -99) >= 2]
ack_big = sum(1 for r in big if r["J1_label"] in ("A", "D"))
P = CC["secondary"]


def thr(t_):
    n = int((eff >= t_).sum())
    return {"n": n, "denominator": len(eff), "percent": round(100 * n / len(eff), 2)}


headline = {
    "_basis": "complete-case measurement basis (the adjudicated basis is pending; see caveats)",
    "_source": "final_analysis_workspace/analysis/final_analysis_results.json -> complete_case",
    "primary_contrast": {
        "name": "no_history - self_low_2",
        "direction": "positive means the score is HIGHER with no history, i.e. being told "
                     "it previously scored 2/10 LOWERS the judge's current score",
        "mean_shift_points": round(P["macro_average"], 4),
        "ci95": [round(P["ci_95"]["ci_low"], 4), round(P["ci_95"]["ci_high"], 4)],
        "weighting": "equal dataset x equal scorer, 12 cells at 1/12",
        "n_matched_pairs": 900, "n_pairs_possible": 936,
        "bootstrap": {"n": P["ci_95"]["n_bootstrap_reps"], "seed": 20260818,
                      "design": "task-clustered, dataset-stratified"},
        "status": "confirmatory",
    },
    "counts": {
        "tasks": 234, "datasets": 3,
        "dataset_names": ["mtbench", "arena_hard", "wildbench"],
        "tasks_per_dataset": 78, "scorers": 4,
        "scorer_names": ["llama", "qwen", "gemma", "olmo32b"],
        "conditions": 6, "logical_judgments": 4680,
        "note": "olmo32b ran only the 2 primary conditions (468 records); the other three "
                "ran all 6 (1404 each)",
    },
    "matched_task_result": {
        "fraction_positive_percent": round(100 * float((eff > 0).mean()), 2),
        "n": int((eff > 0).sum()), "denominator": len(eff),
        "denominator_note": "233 of 234 tasks have at least one retained matched pair",
        "statistic": "panel-averaged per-task delta across scorers",
        "status": "confirmatory",
    },
    "delta_thresholds_panel_averaged": {
        "_denominator": len(eff),
        "_statistic": "panel-averaged per-task delta",
        "ge_1.0": thr(1.0), "ge_1.5": thr(1.5), "ge_2.0": thr(2.0),
        "ge_2.5": thr(2.5), "ge_3.0": thr(3.0),
    },
    "silence": {
        "_source": "final_analysis_workspace/silence_run (archived: silence_archive_2026-08-20.tar.gz)",
        "_judges": ["Qwen/Qwen3-8B", "google/gemma-2-9b-it"],
        "_basis": "concordant items only (both judges agreed); discordant excluded",
        "headline_silent_percent": round(100 * (len(sl_items) - ack_sl) / len(sl_items), 2),
        "headline_n_silent": len(sl_items) - ack_sl, "headline_denominator": len(sl_items),
        "headline_definition": "self_low_2 rationales labelled N (no reference to any "
                               "earlier assessment) by both judges",
        "silent_among_shifts_ge_2_percent": round(100 * (len(big) - ack_big) / len(big), 2),
        "silent_among_shifts_ge_2_n": len(big) - ack_big,
        "silent_among_shifts_ge_2_denominator": len(big),
        "silent_among_shifts_ge_2_definition": "restricted to items where THAT scorer's own "
                                               "no_history minus self_low_2 delta was >= 2 "
                                               "points (not the panel average)",
        "false_positive_floor_no_history_percent": round(
            100 * sum(1 for r in nh_items if r["J1_label"] in ("A", "D")) / len(nh_items), 3),
        "false_positive_floor_denominator": len(nh_items),
        "judge_agreement_percent": round(100 * agree["acknowledgment_label"]["percent_agreement"], 2),
        "judge_cohens_kappa": agree["acknowledgment_label"]["cohens_kappa"],
        "kappa_caveat": "raw agreement is high but kappa is depressed by extreme class "
                        "imbalance (1820 of 1866 items are N-N); this is the kappa paradox, "
                        "not disagreement",
        "status": "descriptive",
    },
}
(OUT / "headline_metrics.json").write_text(json.dumps(headline, indent=2), encoding="utf-8")

# ------------------------------------------------------- 2. delta distribution
cat = {(r["dataset"], r["task_id"]): r["category"] for r in task_level}
nsc = {(r["dataset"], r["task_id"]): int(r["n_scorers"]) for r in task_level}
rows = []
for (ds, t), mean_eff in sorted(tl.items()):
    row = {"dataset": ds, "category": cat[(ds, t)], "task_id": t,
           "panel_delta": round(mean_eff, 6), "n_valid_scorers": nsc[(ds, t)]}
    for s in ("llama", "qwen", "gemma", "olmo32b"):
        v = own_delta.get((s, ds, t))
        row[f"delta_{s}"] = round(v, 6) if v is not None else ""
    rows.append(row)
with (OUT / "delta_distribution.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

# ------------------------------------------------------------- 3. method flow
CONDS = {c.name: c for c in sc.CONDITIONS}
import run_final_scoring as RFS
scorers = {s.key: {"hf_id": s.hf_id, "revision": s.revision,
                   "max_new_tokens": s.max_new_tokens} for s in RFS.SCORERS}
method = {
    "generator": {"role": "produced the single frozen answer judged in every condition",
                  "hf_id": "allenai/Olmo-3.1-32B-Instruct",
                  "revision": "ac0587e4a7744a551c059d8cd17ba220bc940dae",
                  "n_answers": 578, "n_used_in_final_study": 234},
    "scorers": scorers,
    "frozen_contextual_sentences": {k: (CONDS[k].added_context if CONDS[k].added_context
                                        else None) for k in
                                    ["no_history", "self_low_2", "other_low_2",
                                     "unrelated_low_2", "verbal_negative", "self_high_10"]},
    "invariant_across_conditions": [
        "the task/question text", "the generated answer being judged (byte-identical)",
        "the scoring rubric and instructions", "the scorer model and pinned revision",
        "decoding: greedy, do_sample=False, seed 42, batch size 1",
        "the token ceiling", "the parser"],
    "what_changes": "exactly one inserted contextual sentence, or its absence",
    "outputs_per_call": ["a numeric score on a 0-10 scale",
                         "a free-text justification (the rationale)"],
    "silence_annotation": {
        "question": "does the rationale explicitly refer to an earlier assessment?",
        "items": 1872, "scope": "primary contrast only (no_history, self_low_2), 4 scorers",
        "judges": 2, "calls": 3744,
        "labels": {"A": "acknowledged", "N": "not mentioned", "D": "denied/rejected",
                   "U": "unclear"},
        "also_recorded": ["context_mentioned yes/no", "verbatim evidence span"],
        "blinding": "judges saw only an opaque item_id and the rationale text",
        "rule": "judge only what is explicitly written; tone, harshness and inferred "
                "motives are not evidence",
        "agreement_computed_before_unblinding": True},
    "mechanistic_pipeline_llama_high_level": [
        "1. readout: Jacobian Lens across layers at the final_input position on 12 "
        "discovery tasks -> peak condition separation selects one layer",
        "2. causal test: bidirectional activation patching at that layer on held-out tasks",
        "3. controls: no-op and same-condition identity, early-layer L2",
        "4. intervention test: steering and ablation along a learned direction",
        "5. vocabulary readout: signed token-level Jacobian-Lens deltas"],
}
(OUT / "method_flow.json").write_text(json.dumps(method, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
print("  headline_metrics.json, delta_distribution.csv, method_flow.json written")
print(f"  delta_distribution rows: {len(rows)}")
