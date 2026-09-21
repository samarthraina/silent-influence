"""Emit the A9 result tables as CSV, reading only the frozen analysis outputs.

Two weightings appear here and are labelled wherever they differ:
  equal-weight  : mean of cell means (the A9 weighting; used for every point estimate)
  pair-weighted : mean over retained pairs (the frozen bootstrap's diagnostic scope, which
                  is the only place scorer- and dataset-scope CIs exist)
Nothing is recomputed from the record set.
"""
import csv
import json
import os
import pathlib

# Package layout: <package>/code/analysis/<this file> -> <package>.
# The upstream workspace subtrees map onto results/ and figures/ here.
WS = pathlib.Path(os.environ.get(
    "SI_SUPPLEMENT_ROOT", str(pathlib.Path(__file__).resolve().parents[2])))
OUT = WS / "results/tables"
OUT.mkdir(exist_ok=True)
D = json.load(open(WS / "results/behavioral/final_analysis_results.json", encoding="utf-8"))
CC = D["complete_case"]
P = CC["secondary"]
PRIMARY_KEY = "no_history_minus_self_low_2"
DS = ["mtbench", "arena_hard", "wildbench"]
SCORERS = ["llama", "qwen", "gemma", "olmo32b"]


def write(name, header, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  [save] tables/{name}  ({len(rows)} rows)")


# T1 headline
write("t1_primary_headline.csv",
      ["estimand", "weighting", "n_cells", "cell_weight", "macro_average",
       "ci_low", "ci_high", "n_bootstrap", "n_empty_cells"],
      [["no_history - self_low_2 (A9 confirmatory)", "equal dataset x equal scorer",
        P["n_cells"], round(P["cell_weight"], 6), round(P["macro_average"], 4),
        round(P["ci_95"]["ci_low"], 4), round(P["ci_95"]["ci_high"], 4),
        P["ci_95"]["n_bootstrap_reps"], P["n_empty_cells"]]])

# T2 by scorer
dci = CC["diagnostics"]["ci_95"][PRIMARY_KEY]
dpt = CC["diagnostics"]["point"][PRIMARY_KEY]
rows = []
for s in SCORERS:
    eq = CC["pooled_summaries"]["scorer_wise"][s]
    pw, c = dpt["scorer"][s], dci["scorer"][s]
    rows.append([s, round(eq["mean"], 4), eq["n_datasets_with_data"],
                 round(pw["mean"], 4), pw["n"], round(c["ci_low"], 4), round(c["ci_high"], 4)])
write("t2_primary_by_scorer.csv",
      ["scorer", "equal_weight_mean", "n_datasets", "pair_weighted_mean", "n_pairs",
       "ci_low_pair_weighted", "ci_high_pair_weighted"], rows)

# T3 by dataset
rows = []
for d in DS:
    eq = CC["pooled_summaries"]["dataset_wise"][d]
    pw, c = dpt["dataset"][d], dci["dataset"][d]
    rows.append([d, round(eq["mean"], 4), eq["n_scorers_with_data"],
                 round(pw["mean"], 4), pw["n"], round(c["ci_low"], 4), round(c["ci_high"], 4)])
write("t3_primary_by_dataset.csv",
      ["dataset", "equal_weight_mean", "n_scorers", "pair_weighted_mean", "n_pairs",
       "ci_low_pair_weighted", "ci_high_pair_weighted"], rows)

# T4 the 12 cells
rows = [[d, s, round(P["cell_means"][f"{d}|{s}"], 4), P["cell_n"][f"{d}|{s}"]]
        for s in SCORERS for d in DS]
write("t4_primary_scorer_x_dataset.csv",
      ["dataset", "scorer", "cell_mean", "n_retained_pairs"], rows)

# T5 task-level fractions
st = CC["task_level_distribution"]["full_578"]["overall"]
write("t5_task_level_fractions.csv",
      ["statistic", "value"],
      [["n_tasks", st["n_tasks"]],
       ["fraction_positive", round(st["fraction_gt_0"], 4)],
       ["fraction_at_least_plus_1", round(st["fraction_ge_1"], 4)],
       ["fraction_at_least_plus_2", round(st["fraction_ge_2"], 4)],
       ["fraction_zero", round(st["fraction_eq_0"], 4)],
       ["fraction_negative", round(st["fraction_lt_0"], 4)],
       ["min", round(st["min"], 4)], ["p25", round(st["p25"], 4)],
       ["median", round(st["median"], 4)], ["p75", round(st["p75"], 4)],
       ["max", round(st["max"], 4)]])

# T6 diagnostics
rows = []
for c, pt in CC["diagnostics"]["point"].items():
    pool = list(pt["pooled"].values())[0]
    cip = list(CC["diagnostics"]["ci_95"][c]["pooled"].values())[0]
    per = {s: pt["scorer"][s]["mean"] for s in pt["scorer"] if s != "olmo32b"}
    rows.append([c, "yes" if c == PRIMARY_KEY else "no", round(pool["mean"], 4), pool["n"],
                 round(cip["ci_low"], 4), round(cip["ci_high"], 4)]
                + [round(per.get(s, float("nan")), 4) for s in ("llama", "qwen", "gemma")])
write("t6_diagnostic_contrasts.csv",
      ["contrast", "is_confirmatory_primary", "pair_weighted_pooled", "n_pairs",
       "ci_low", "ci_high", "llama", "qwen", "gemma"], rows)

# T7 parse / validity audit
a = D["attrition_summary"]
rows = []
for k, v in sorted(a["scorer_condition"].items()):
    s, cond = k.strip("()").replace("'", "").split(", ")
    rows.append([s, cond, v["n_total"], v["n_failed"], round(v["rate"], 4)])
write("t7_validity_by_scorer_condition.csv",
      ["scorer", "condition", "n_total", "n_invalid", "invalid_rate"], rows)

# T8 robustness
r = CC["robustness"]
t = r["R1_trimmed_mean"]["secondary_12_cell"]
l = r["R2_leave_one_task_out"]["secondary_578"]
s1 = CC["S1_three_scorer_sensitivity"]["secondary"]
write("t8_robustness.csv",
      ["check", "value", "ci_low", "ci_high", "note"],
      [["R1 10% trimmed macro (12 cells)", round(t["macro_average"], 4),
        round(t["ci_95"]["ci_low"], 4), round(t["ci_95"]["ci_high"], 4), ""],
       ["R2 leave-one-task-out range", round(l["range_shift"], 5), "", "",
        f"{l['n_recomputations']} recomputations; max shift "
        f"{max(abs(l['min_shift']), abs(l['max_shift'])):.5f}"],
       ["S1 three-scorer (no OLMo), 9 cells", round(s1["macro_average"], 4),
        round(s1["ci_95"]["ci_low"], 4), round(s1["ci_95"]["ci_high"], 4),
        CC["S1_three_scorer_sensitivity"].get("status", "")],
       ["Superseded v2 8-cell estimand", round(CC["primary"]["macro_average"], 4),
        round(CC["primary"]["ci_95"]["ci_low"], 4), round(CC["primary"]["ci_95"]["ci_high"], 4),
        "arena_hard+wildbench only; NOT the A9 confirmatory primary"]])
print("done")
