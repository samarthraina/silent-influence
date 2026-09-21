"""ECDF of the complete-case task-level primary deltas.

Deltas are recomputed through the frozen estimator (analyze_final_study.pivot_scores +
contrast_diffs) so the figure and the table share one source. Two panels because the max-4
series rule applies per panel: overall is one series, the scorer panel is four.

Palette: dataviz reference categorical slots 1, 2, 3, 7 in published fixed order (the node
validator is unavailable on this machine, so the pre-validated order is used unchanged).
"""
import os
import pathlib
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: F401  (puts code/src and code/scripts on sys.path)
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Package layout: <package>/code/analysis/<this file> -> <package>.
# The upstream workspace subtrees map onto results/ and figures/ here.
WS = pathlib.Path(os.environ.get(
    "SI_SUPPLEMENT_ROOT", str(pathlib.Path(__file__).resolve().parents[2])))
REPO = WS.parent / "Code/GitHub/silent-influence"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
import analyze_final_study as A

SLOT = {"llama": "#2a78d6", "qwen": "#eb6834", "gemma": "#1baf7a", "olmo32b": "#4a3aa7"}
INK, MUTED, GRID = "#1a1a1a", "#5c5c5c", "#d8d8d8"
SCORERS = ["llama", "qwen", "gemma", "olmo32b"]
THR = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

records = A.load_records(WS / "results/behavioral/merged_raw_results.jsonl")
diffs = A.contrast_diffs(A.pivot_scores(records), *A.PRIMARY, datasets=A.FULL_DATASETS)
by_task = {}
for scorer, dataset, task_id, d in diffs:
    by_task.setdefault((dataset, task_id), {})[scorer] = d
overall = np.array([np.mean(list(v.values())) for v in by_task.values()])
per = {s: np.array([v[s] for v in by_task.values() if s in v]) for s in SCORERS}

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "figure.dpi": 150,
})


def ecdf(a):
    x = np.sort(a)
    return np.concatenate([[x[0]], x]), np.concatenate([[0.0], np.arange(1, x.size + 1) / x.size])


fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 4.2), sharey=True)

# Each panel spans its own data range so every ECDF actually reaches 1.0. A shared clipped
# range hid 11 per-scorer points at +-10 and made those curves look complete when they were
# not.
lim1 = (float(overall.min()) - 0.4, float(overall.max()) + 0.4)
allper = np.concatenate(list(per.values()))
lim2 = (float(allper.min()) - 0.6, float(allper.max()) + 0.6)
for ax, lim in ((ax1, lim1), (ax2, lim2)):
    ax.axvline(0, color=INK, lw=1.1, zorder=1)
    for t in THR:
        ax.axvline(t, color=GRID, lw=0.7, ls=(0, (2, 3)), zorder=0)
    ax.set_xlim(*lim)
    ax.set_ylim(0, 1)
    ax.grid(axis="y", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlabel("task-level delta, no_history - self_low_2 (score points)")

x, y = ecdf(overall)
ax1.step(x, y, where="post", color="#2a78d6", lw=2)
ax1.set_ylabel("empirical CDF  F(x) = P(delta <= x)")
ax1.set_title(f"Overall: per-task mean across scorers  (n={overall.size})",
              fontsize=9.5, loc="left")

for s in SCORERS:
    x, y = ecdf(per[s])
    ax2.step(x, y, where="post", color=SLOT[s], lw=1.8, label=f"{s} (n={per[s].size})")
ax2.legend(frameon=False, fontsize=8, loc="upper left")
ax2.set_title("By scorer: that scorer's own per-task delta", fontsize=9.5, loc="left")

fig.suptitle("Complete-case confirmatory primary contrast - empirical CDF of task-level "
             "deltas\ndotted guides at the seven pre-specified thresholds; curve to the "
             "RIGHT = larger effect", fontsize=10.5, x=0.005, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.93))
for ext in ("pdf", "png"):
    fig.savefig(WS / f"figures/f5_ecdf_task_level_deltas.{ext}", bbox_inches="tight",
                facecolor="white")
plt.close(fig)
print("  [save] figures/f5_ecdf_task_level_deltas.pdf / .png")
