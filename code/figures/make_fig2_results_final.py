"""Research Figure 2 — FINAL, derived from Variant 3. Layout/presentation only.

Variants 1-3 are untouched: this is a separate script writing separate files.
No value is recomputed. Every number is read from headline_metrics.json exactly as the
variants read it; the only arithmetic is 100 - silent, which the variants also did.

Sign convention is unchanged: panel_delta = no_history - self_low_2, so a positive value
already means the prior-2/10 condition scored LOWER. The axis label states that directly,
which is why the separate italic direction sentence was removed rather than reworded.

Canvas is a fixed 7.0 x 2.52 in saved WITHOUT bbox_inches="tight", so the emitted figure is
exactly 7.0 in wide -- a tight box grows the canvas past the column. Every axes rectangle is
therefore placed explicitly, and no visible label is below 6.5 pt at that size.

The two definition lines that previously sat under Panel B are removed; they belong in the
LaTeX caption. The no-history control annotation is retained inside Panel B.
"""
import csv
import json
import os
import pathlib
from decimal import Decimal, ROUND_HALF_UP

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

# Package-relative: <package>/code/figures/<this file> -> <package>
ROOT = pathlib.Path(os.environ.get(
    "SI_SUPPLEMENT_ROOT", str(pathlib.Path(__file__).resolve().parents[2])))
IN = ROOT / "results/figure_inputs"
OUT = ROOT / "figures/paper"

H = json.loads((IN / "headline_metrics.json").read_text(encoding="utf-8"))
ROWS = list(csv.DictReader((IN / "delta_distribution.csv").open(encoding="utf-8")))
D = np.array([float(r["panel_delta"]) for r in ROWS])
assert len(D) == 233, len(D)


def pct(v, dp=1):
    """Half-up display rounding: f-strings turn the verified 15.45 into 15.4."""
    return f"{Decimal(str(v)).quantize(Decimal('1').scaleb(-dp), rounding=ROUND_HALF_UP):.{dp}f}"


P, S, T = H["primary_contrast"], H["silence"], H["delta_thresholds_panel_averaged"]
MACRO, CI = P["mean_shift_points"], P["ci95"]
PCT_POS = H["matched_task_result"]["fraction_positive_percent"]
G1, G2 = T["ge_1.0"]["percent"], T["ge_2.0"]["percent"]
SIL_ALL, N_ALL = S["headline_silent_percent"], S["headline_denominator"]
SIL_BIG, N_BIG = S["silent_among_shifts_ge_2_percent"], S["silent_among_shifts_ge_2_denominator"]
FLOOR, N_FLOOR = S["false_positive_floor_no_history_percent"], S["false_positive_floor_denominator"]

NAVY, COBALT, TEAL, CORAL, GOLD = "#14345e", "#1f6fd0", "#12a99a", "#e2603f", "#c9962c"
INK, MUTED, GRID = "#161a1f", "#5f6672", "#e3e6ea"
SMALL = 6.5          # floor for every visible label at the final 7.0 in size

plt.rcParams.update({
    "font.size": 7.2, "font.family": "DejaVu Sans",
    "axes.edgecolor": "#b8bec7", "axes.linewidth": 0.6, "axes.labelcolor": INK,
    "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 6.8, "ytick.labelsize": 6.8,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "pdf.fonttype": 42, "ps.fonttype": 42,
    "svg.fonttype": "none", "figure.facecolor": "white", "axes.facecolor": "white",
})

fig = plt.figure(figsize=(7.0, 2.52))
axA = fig.add_axes([0.068, 0.230, 0.390, 0.600])
axT = fig.add_axes([0.478, 0.230, 0.085, 0.600]); axT.axis("off")
axB = fig.add_axes([0.640, 0.230, 0.330, 0.600])

# ─────────────────────────────────────────────────────────── Panel A
bins = np.arange(-3.0, 4.01, 0.25)
n_, _, patches = axA.hist(D, bins=bins, color=COBALT, edgecolor="white", linewidth=0.6,
                          zorder=3)
for p_, left in zip(patches, bins[:-1]):
    if left < 0:
        p_.set_facecolor(CORAL)
    elif left >= 2:
        p_.set_facecolor(TEAL)
# bounded so it does not strike through the rug or the macro annotation
axA.plot([0, 0], [-2.45, 43.0], color=INK, lw=1.15, zorder=5, solid_capstyle="butt")

# all 233 observations, retained as rug marks
axA.plot(D, np.full(len(D), -1.75), "|", ms=4.2, color=NAVY, alpha=0.55, mew=0.7, zorder=4)
axA.annotate("rug: all 233 tasks", xy=(3.30, -1.75), xytext=(3.95, 26.0), fontsize=SMALL,
             color=MUTED, ha="right",
             arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.5, shrinkA=1, shrinkB=2))

# macro-average: deliberately secondary — small marker, small regular-weight label
axA.plot(CI, [-5.05, -5.05], color=CORAL, lw=1.6, solid_capstyle="butt", zorder=6)
for c in CI:
    axA.plot([c, c], [-5.55, -4.55], color=CORAL, lw=1.0, zorder=6)
axA.plot([MACRO], [-5.05], "o", ms=3.6, color=CORAL, mec="white", mew=0.8, zorder=7)
axA.text(CI[0] - 0.16, -5.05, f"Macro-average: +{MACRO:.2f} [{CI[0]:.2f}, {CI[1]:.2f}]",
         va="center", ha="right", fontsize=SMALL, color=CORAL)

axA.set_ylim(-7.0, 44); axA.set_xlim(-3.0, 4.0)
axA.set_xlabel("Score decrease under prior 2/10 context (points, panel average)",
               fontsize=6.9)
axA.set_ylabel("Tasks", fontsize=7.0)
axA.set_yticks([0, 10, 20, 30, 40])
axA.grid(axis="y", color=GRID, lw=0.5, zorder=1)
axA.set_axisbelow(True)
axA.spines["bottom"].set_bounds(-3.0, 4.0)
axA.spines["left"].set_bounds(0, 40)

axA.text(0.0, 1.150, f"Prior 2/10 context lowers scores on {pct(PCT_POS)}% of matched tasks",
         transform=axA.transAxes, ha="left", va="top", fontsize=7.9, fontweight="bold",
         color=NAVY)
axA.text(0.0, 1.028, "panel-averaged task-level result, n = 233",
         transform=axA.transAxes, ha="left", va="top", fontsize=SMALL, color=MUTED)

# ─────────────────────────────────────────────────────────── threshold summaries
tiles = [(f"{pct(PCT_POS)}%", "> 0 points", NAVY, True),
         (f"{pct(G1)}%", "≥ 1 point", COBALT, False),
         (f"{pct(G2)}%", "≥ 2 points", TEAL, False)]
for i, (big, small, col, lead) in enumerate(tiles):
    y = 0.795 - i * 0.310
    axT.plot([0.03, 0.03], [y - 0.180, y + 0.050], color=col, lw=2.4 if lead else 1.7,
             transform=axT.transAxes, clip_on=False, solid_capstyle="round")
    axT.text(0.16, y - 0.025, big, transform=axT.transAxes, ha="left", va="center",
             fontsize=10.2 if lead else 8.8, fontweight="bold", color=col)
    axT.text(0.16, y - 0.145, small, transform=axT.transAxes, ha="left", va="center",
             fontsize=SMALL, color=MUTED)
axT.text(0.03, 0.962, "of 233 tasks", transform=axT.transAxes, ha="left", va="top",
         fontsize=SMALL, color=MUTED)

# ─────────────────────────────────────────────────────────── Panel B
rows = [(f"Prior-2/10 justifications, concordantly\nannotated  (n = {N_ALL})", SIL_ALL, 1),
        (f"When that scorer dropped ≥2 points  (n = {N_BIG})", SIL_BIG, 0)]
h = 0.36
for label, sil, y in rows:
    ack = round(100 - sil, 2)
    axB.barh(y, sil, height=h, color=TEAL, zorder=3, edgecolor="white", linewidth=0.7)
    axB.barh(y, ack, left=sil, height=h, color=CORAL, zorder=3, edgecolor="white",
             linewidth=0.7)
    axB.text(sil - 1.2, y, f"{pct(sil)}%", ha="right", va="center", color="white",
             fontsize=8.0, fontweight="bold", zorder=4)
    axB.text(101.4, y, f"{pct(ack)}%", ha="left", va="center", color=CORAL, fontsize=6.9,
             fontweight="bold", zorder=4)
    axB.text(0, y + h / 2 + 0.09, label, ha="left", va="bottom", fontsize=SMALL, color=INK,
             linespacing=1.32)

axB.set_xlim(0, 110); axB.set_ylim(-0.62, 2.06)
axB.set_yticks([]); axB.tick_params(axis="y", length=0)
axB.set_xticks([0, 25, 50, 75, 100]); axB.set_xticklabels(["0", "25", "50", "75", "100%"])
axB.spines["left"].set_visible(False)
axB.grid(axis="x", color=GRID, lw=0.5, zorder=0); axB.set_axisbelow(True)
axB.set_xlabel("Share of justifications", fontsize=6.9)

# no-history control: retained inside Panel B
axB.plot([1.4], [-0.42], marker="|", ms=6.5, color=GOLD, mew=1.8, zorder=5, clip_on=False)
axB.text(4.4, -0.42, f"no-history control: {pct(FLOOR, 2)}% mention rate (n = {N_FLOOR})",
         ha="left", va="center", fontsize=SMALL, color=MUTED)

axB.add_patch(Rectangle((0.4, 1.80), 3.0, 0.10, color=TEAL, clip_on=False))
axB.text(4.8, 1.85, "silent", fontsize=SMALL, va="center", color=INK)
axB.add_patch(Rectangle((23.0, 1.80), 3.0, 0.10, color=CORAL, clip_on=False))
axB.text(27.4, 1.85, "prior context mentioned", fontsize=SMALL, va="center", color=INK)

axA.text(-0.135, 1.150, "(a)", transform=axA.transAxes, fontsize=8.4, fontweight="bold",
         va="top")
axB.text(-0.058, 1.150, "(b)", transform=axB.transAxes, fontsize=8.4, fontweight="bold",
         va="top")

for ext, kw in (("pdf", {}), ("svg", {}), ("png", {"dpi": 400})):
    fig.savefig(OUT / f"fig2_results_final.{ext}", facecolor="white", **kw)
plt.close(fig)
print("  [save] fig2_results_final.pdf / .svg / .png  (canvas exactly 7.0 x 2.52 in)")
print(f"  observations in Panel A: {len(D)}")
