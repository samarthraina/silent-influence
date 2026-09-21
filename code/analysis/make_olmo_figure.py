"""OLMo-32B DESCRIPTIVE histogram + ECDF of the 218 matched primary task pairs.

Same frozen deltas as the audit table. Descriptive: the tail and the extremes are shown so
they can be seen, not so they can be quoted as an effect size.
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

OLMO, INK, MUTED, GRID = "#4a3aa7", "#1a1a1a", "#5c5c5c", "#d8d8d8"
THR = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]

diffs = [d for d in A.contrast_diffs(
    A.pivot_scores(A.load_records(WS / "results/behavioral/merged_raw_results.jsonl")),
    *A.PRIMARY, datasets=A.FULL_DATASETS) if d[0] == "olmo32b"]
delta = np.array([d[3] for d in diffs], dtype=float)

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "figure.dpi": 150,
})

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 4.0))

bins = np.arange(np.floor(delta.min() * 2) / 2, np.ceil(delta.max() * 2) / 2 + 0.5, 0.5)
ax1.hist(delta, bins=bins, color=OLMO, edgecolor="white", linewidth=0.8)
ax1.axvline(0, color=INK, lw=1.2)
ax1.axvline(delta.mean(), color="#eb6834", lw=1.6, ls=(0, (4, 2)))
ax1.annotate(f"mean {delta.mean():+.3f}", (delta.mean(), ax1.get_ylim()[1] * 0.95),
             textcoords="offset points", xytext=(6, 0), fontsize=8, color="#eb6834")
ax1.set_xlabel("delta, no_history - self_low_2 (score points)")
ax1.set_ylabel("task pairs")
ax1.set_title(f"Histogram  (n={delta.size} matched pairs)", fontsize=9.5, loc="left")
ax1.grid(axis="y", color=GRID, lw=0.6)
ax1.set_axisbelow(True)

x = np.sort(delta)
xs = np.concatenate([[x[0]], x])
ys = np.concatenate([[0.0], np.arange(1, x.size + 1) / x.size])
ax2.step(xs, ys, where="post", color=OLMO, lw=2)
ax2.axvline(0, color=INK, lw=1.1)
for t in THR:
    ax2.axvline(t, color=GRID, lw=0.7, ls=(0, (2, 3)), zorder=0)
ax2.set_ylim(0, 1)
ax2.set_xlim(delta.min() - 0.6, delta.max() + 0.6)
ax2.set_xlabel("delta, no_history - self_low_2 (score points)")
ax2.set_ylabel("empirical CDF  F(x) = P(delta <= x)")
ax2.set_title("Empirical CDF  (guides at the pre-specified thresholds)",
              fontsize=9.5, loc="left")
ax2.grid(axis="y", color=GRID, lw=0.6)
ax2.set_axisbelow(True)

fig.suptitle("OLMo-3.1-32B - DESCRIPTIVE audit of the 218 matched complete-case primary "
             "pairs\nnot a confirmatory estimate; extremes shown for description only",
             fontsize=10.5, x=0.005, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.91))
for ext in ("pdf", "png"):
    fig.savefig(WS / f"figures/f6_olmo_descriptive.{ext}", bbox_inches="tight",
                facecolor="white")
plt.close(fig)
print("  [save] figures/f6_olmo_descriptive.pdf / .png")
