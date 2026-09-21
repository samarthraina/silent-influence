"""Supplementary A9-labelled figures.

The frozen script's own figures are kept exactly as produced. These repeat the same numbers
from the same results JSON under the correct A9 population label (234 tasks), because the
frozen figure titles still carry the superseded v2 "full 578" / "500 held-out" populations.
No estimator is recomputed here: every value is read from final_analysis_results.json or the
CSVs the frozen script wrote.

Palette: dataviz reference categorical slots 1, 2, 3, 7 in published fixed order. The bundled
validator is a node script and node is not installed here, so the pre-validated fixed order is
used unchanged rather than substituting hand-picked colours.
"""
import csv
import json
import os
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Package layout: <package>/code/analysis/<this file> -> <package>.
# The upstream workspace subtrees map onto results/ and figures/ here.
WS = pathlib.Path(os.environ.get(
    "SI_SUPPLEMENT_ROOT", str(pathlib.Path(__file__).resolve().parents[2])))
OUT = WS / "figures/analysis/analysis"
OUT.mkdir(exist_ok=True)
D = json.load(open(WS / "results/behavioral/final_analysis_results.json", encoding="utf-8"))
CC = D["complete_case"]

SLOT = {"llama": "#2a78d6", "qwen": "#eb6834", "gemma": "#1baf7a", "olmo32b": "#4a3aa7"}
INK, MUTED, GRID = "#1a1a1a", "#5c5c5c", "#d8d8d8"
SCORERS = ["llama", "qwen", "gemma", "olmo32b"]
DS = ["mtbench", "arena_hard", "wildbench"]
DSL = {"mtbench": "MT-Bench", "arena_hard": "Arena-Hard", "wildbench": "WildBench"}

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150,
})


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"{name}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [save] {name}.pdf / .png")


# ---- F1: the 12 primary cells --------------------------------------------------------
p = CC["secondary"]
macro, lo, hi = p["macro_average"], p["ci_95"]["ci_low"], p["ci_95"]["ci_high"]
fig, ax = plt.subplots(figsize=(6.8, 4.6))
ax.axvspan(lo, hi, color="#2a78d6", alpha=0.10, lw=0, zorder=0)
ax.axvline(macro, color=INK, lw=1.4, zorder=2)
ax.axvline(0, color=MUTED, lw=1, ls=(0, (3, 3)), zorder=1)

ypos, ylab, y = [], [], 0
band_centre = {}
for s in SCORERS:
    start = y
    for d in DS:
        v, n = p["cell_means"][f"{d}|{s}"], p["cell_n"][f"{d}|{s}"]
        ax.plot([v], [y], "o", ms=7, color=SLOT[s], mec="white", mew=1.2, zorder=3)
        ax.annotate(f"{v:+.2f}", (v, y), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=7.5, color=MUTED)
        ypos.append(y)
        ylab.append(f"{DSL[d]}  (n={n})")
        y += 1
    band_centre[s] = (start + y - 1) / 2
    y += 0.7

ax.set_yticks(ypos)
ax.set_yticklabels(ylab, fontsize=8)
ax.set_ylim(y - 0.4, -0.8)
xmin = min(p["cell_means"].values()) - 0.45
ax.set_xlim(min(xmin, -0.1), max(p["cell_means"].values()) + 0.35)
for s in SCORERS:
    ax.annotate(s, (ax.get_xlim()[0], band_centre[s]), textcoords="offset points",
                xytext=(4, 0), fontsize=9, fontweight="bold", color=SLOT[s],
                va="center", ha="left")
ax.set_xlabel("no_history − self_low_2  (score points)")
ax.set_title("A9 confirmatory primary contrast: 12 cells, equal dataset x equal scorer\n"
             f"macro average {macro:.3f}   95% CI [{lo:.3f}, {hi:.3f}]   ·   234 tasks",
             fontsize=10, loc="left")
ax.grid(axis="x", color=GRID, lw=0.6)
ax.set_axisbelow(True)
save(fig, "f1_primary_12_cells")

# ---- F2: task-level distribution -----------------------------------------------------
rows = list(csv.DictReader(open(WS / "results/behavioral/task_level_effects_full_578.csv",
                                encoding="utf-8")))
eff = np.array([float(r["mean_effect"]) for r in rows])
st = CC["task_level_distribution"]["full_578"]["overall"]
fig, ax = plt.subplots(figsize=(6.8, 3.6))
bins = np.arange(np.floor(eff.min() * 4) / 4, np.ceil(eff.max() * 4) / 4 + 0.25, 0.25)
ax.hist(eff, bins=bins, color="#2a78d6", edgecolor="white", linewidth=0.8)
ax.axvline(0, color=INK, lw=1.2)
ax.set_xlabel("task-level mean effect, no_history − self_low_2  (score points)")
ax.set_ylabel("tasks")
ax.set_title(f"Matched task-level effects   ·   {st['n_tasks']} tasks with at least one "
             f"retained pair", fontsize=10, loc="left")
txt = (f"> 0    {st['fraction_gt_0']:6.1%}\n"
       f">= +1  {st['fraction_ge_1']:6.1%}\n"
       f">= +2  {st['fraction_ge_2']:6.1%}\n"
       f"= 0    {st['fraction_eq_0']:6.1%}\n"
       f"< 0    {st['fraction_lt_0']:6.1%}")
ax.annotate(txt, (0.985, 0.95), xycoords="axes fraction", ha="right", va="top",
            fontsize=8, color=INK, family="monospace",
            bbox=dict(boxstyle="round,pad=0.45", fc="white", ec=GRID, lw=0.8))
ax.grid(axis="y", color=GRID, lw=0.6)
ax.set_axisbelow(True)
save(fig, "f2_task_level_distribution")

# ---- F3: diagnostic contrasts --------------------------------------------------------
pt, ci = CC["diagnostics"]["point"], CC["diagnostics"]["ci_95"]
order = ["self_high_10_minus_self_low_2", "no_history_minus_verbal_negative",
         "no_history_minus_self_low_2", "self_high_10_minus_no_history",
         "no_history_minus_unrelated_low_2", "other_low_2_minus_self_low_2",
         "no_history_minus_other_low_2", "unrelated_low_2_minus_self_low_2"]
PRIMARY_KEY = "no_history_minus_self_low_2"
fig, ax = plt.subplots(figsize=(7.2, 4.0))
ax.axvline(0, color=MUTED, lw=1, ls=(0, (3, 3)))
for i, c in enumerate(order):
    pool = list(pt[c]["pooled"].values())[0]
    cip = list(ci[c]["pooled"].values())[0]
    col = "#4a3aa7" if c == PRIMARY_KEY else "#2a78d6"
    ax.plot([cip["ci_low"], cip["ci_high"]], [i, i], color=col, lw=2.2,
            solid_capstyle="round")
    ax.plot([pool["mean"]], [i], "o", ms=7, color=col, mec="white", mew=1.2, zorder=3)
    ax.annotate(f"{pool['mean']:+.2f}  (n={pool['n']})", (cip["ci_high"], i),
                textcoords="offset points", xytext=(8, 0), va="center",
                fontsize=7.5, color=MUTED)
ax.set_yticks(range(len(order)))
ax.set_yticklabels([c.replace("_minus_", " - ") + ("  (primary)" if c == PRIMARY_KEY else "")
                    for c in order], fontsize=8)
ax.invert_yaxis()
ax.set_xlim(-0.2, 3.3)
ax.set_xlabel("contrast (score points), pair-weighted pooled with 95% CI")
ax.set_title("Diagnostic contrasts   ·   llama / qwen / gemma only\n"
             "non-confirmatory, unadjusted for multiplicity", fontsize=10, loc="left")
ax.grid(axis="x", color=GRID, lw=0.6)
ax.set_axisbelow(True)
save(fig, "f3_diagnostic_contrasts")

# ---- F4: condition means by scorer ---------------------------------------------------
conds = ["no_history", "self_low_2", "other_low_2", "unrelated_low_2",
         "verbal_negative", "self_high_10"]
means = {}
for r in csv.DictReader(open(WS / "results/behavioral/condition_summary.csv", encoding="utf-8")):
    if r["scope"] == "scorer":
        means[(r["scorer"], r["condition"])] = float(r["mean"])
fig, ax = plt.subplots(figsize=(7.2, 3.8))
w = 0.2
for i, s in enumerate(SCORERS):
    xs = [j + (i - 1.5) * w for j, c in enumerate(conds) if (s, c) in means]
    ys = [means[(s, c)] for c in conds if (s, c) in means]
    ax.bar(xs, ys, width=w * 0.9, color=SLOT[s], label=s, edgecolor="white", linewidth=0.8)
ax.set_xticks(range(len(conds)))
ax.set_xticklabels([c.replace("_", "\n") for c in conds], fontsize=8)
ax.set_ylabel("mean parsed score")
ax.set_ylim(0, 10)
ax.legend(frameon=False, ncol=4, fontsize=8, loc="upper left", bbox_to_anchor=(0, 1.03))
ax.set_title("Condition means by scorer   ·   234 tasks   ·   OLMo ran only the two "
             "primary conditions", fontsize=10, loc="left", pad=24)
ax.grid(axis="y", color=GRID, lw=0.6)
ax.set_axisbelow(True)
save(fig, "f4_condition_means")
print("done")
