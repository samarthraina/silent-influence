"""Research Figure 4 V4: quantitative mechanistic evidence (Llama-3.1-8B).

Colour revision of V3: identical data, layout, wording and geometry, with a brighter
palette. Every hue is a more saturated version of the V3 role colour, so the semantic
mapping is unchanged: gold = layer 24, grey = layer 2 control, coral = low-history
source, blue = no-history source, indigo = the discovery curve.

Layout and wording revision of V2. V1 and V2 are left untouched; this writes separate V3
files. No data is changed or recomputed: the same two verified artifacts are read, and the
same stored values are drawn.

Sources, both asserted before drawing:
  Panel A  mechanistic_llama/out/discovery/readout_layer_summary.json
           31 lens-covered layers, 12 discovery tasks, frozen eligibility band L4..L27,
           selected L24, window [23, 24, 25].
  Panel B  Brain/figure_inputs/mechanistic_summary.json -> llama_positive_case_study
           72-task mechanistically unseen extension set.

Arithmetic is limited to multiplying the stored normalized fraction by 100 for the percent
axis. Displayed labels use half-up rounding to one decimal; the exact printed strings are
asserted against the values required by the specification.

Canvas is a fixed 7.0 x 2.65 in saved WITHOUT bbox_inches="tight" so the emitted width is
exact. All text is live vector text, minimum 6.5 pt.
"""
import json
import os
import pathlib
from decimal import Decimal, ROUND_HALF_UP

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

# Package-relative: <package>/code/figures/<this file> -> <package>
ROOT = pathlib.Path(os.environ.get(
    "SI_SUPPLEMENT_ROOT", str(pathlib.Path(__file__).resolve().parents[2])))
DISC = ROOT / "results/mechanistic/readout_layer_summary.json"
SUMM = ROOT / "results/figure_inputs/mechanistic_summary.json"
OUT = ROOT / "figures/paper"
OUT.mkdir(parents=True, exist_ok=True)

# ── Panel A source ────────────────────────────────────────────────────────────────────
Dj = json.loads(DISC.read_text(encoding="utf-8"))
BY = Dj["by_layer"]
LAYERS = [r["layer"] for r in BY]
JSD = [r["jsd_bits_mean"] for r in BY]
ELO, EHI = Dj["eligible_layers"]
SEL, WIN = Dj["selected_layer"], Dj["window"]
N_DISC = list({r["n_tasks"] for r in BY})[0]

assert len(BY) == 31, len(BY)
assert {r["n_tasks"] for r in BY} == {12}, "Panel A must come from the 12 discovery tasks"
assert SEL == 24 and WIN == [23, 24, 25], (SEL, WIN)
assert max((r for r in BY if ELO <= r["layer"] <= EHI),
           key=lambda r: r["jsd_bits_mean"])["layer"] == 24, "L24 not the eligible max"
JSD24 = next(r for r in BY if r["layer"] == 24)["jsd_bits_mean"]
assert abs(JSD24 - 0.3159) < 0.0005, JSD24
assert Dj["selected_before_any_validation_run"] is True

# ── Panel B source ────────────────────────────────────────────────────────────────────
L = json.loads(SUMM.read_text(encoding="utf-8"))["llama_positive_case_study"]
REP, EAR = L["patching_72_task_replication"], L["early_layer_L2_comparison"]
D1, D2 = "self_low_2->no_history", "no_history->self_low_2"


def pc(d):
    return d["normalized_mean"] * 100, d["ci95"][0] * 100, d["ci95"][1] * 100


V = {("L24", 1): pc(REP[D1]), ("L2", 1): pc(EAR[D1]),
     ("L24", 2): pc(REP[D2]), ("L2", 2): pc(EAR[D2])}
for k, w in ((("L24", 1), (21.97, 5.97, 39.63)), (("L2", 1), (-0.10, -4.82, 4.18)),
             (("L24", 2), (18.89, 8.60, 29.98)), (("L2", 2), (1.93, -9.35, 11.74))):
    assert all(abs(a - b) < 0.005 for a, b in zip(V[k], w)), (k, V[k], w)


def r1(v):
    """Half-up to one decimal: f-strings round half to even and would print -9.3."""
    return f"{Decimal(str(round(v, 6))).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}"


def label(key):
    m, lo, hi = V[key]
    return f"{r1(m)}% [{r1(lo)}, {r1(hi)}]"


# the exact strings the specification requires
assert label(("L24", 1)) == "22.0% [6.0, 39.6]", label(("L24", 1))
assert label(("L2", 1)) == "-0.1% [-4.8, 4.2]", label(("L2", 1))
assert label(("L24", 2)) == "18.9% [8.6, 30.0]", label(("L24", 2))
assert label(("L2", 2)) == "1.9% [-9.4, 11.7]", label(("L2", 2))

# brighter, higher-chroma versions of the same role colours
NAVY, GOLD, GREY, CORAL, BLUE = "#173a86", "#f0a202", "#7b8492", "#f4523b", "#1e7ae6"
CURVE = "#2b55d4"          # discovery curve: vivid indigo, distinct from the gold peak
INK, MUTED, FAINT, WASH = "#141821", "#59616e", "#e3e8ef", "#eef2f7"
SMALL = 6.5

plt.rcParams.update({
    "font.family": "DejaVu Sans", "pdf.fonttype": 42, "ps.fonttype": 42,
    "svg.fonttype": "none", "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": NAVY, "axes.linewidth": 0.6,
    "xtick.color": NAVY, "ytick.color": NAVY, "text.color": INK,
    "xtick.labelsize": SMALL, "ytick.labelsize": SMALL,
    "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
})

FIG_W, FIG_H = 7.0, 2.65
fig = plt.figure(figsize=(FIG_W, FIG_H))
axA = fig.add_axes([0.078, 0.250, 0.285, 0.560])
axB = fig.add_axes([0.575, 0.250, 0.375, 0.560])

# ══════════════════════════════════════ (a) layerwise Jacobian-Lens readout divergence
axA.axvspan(0.4, ELO - 0.5, color=WASH, lw=0, zorder=0)
axA.axvspan(EHI + 0.5, 31.6, color=WASH, lw=0, zorder=0)
axA.axvspan(WIN[0] - 0.5, WIN[-1] + 0.5, color=GOLD, alpha=0.26, lw=0, zorder=1)

axA.plot(LAYERS, JSD, "-", color=CURVE, lw=1.25, zorder=3)
for lay, v in zip(LAYERS, JSD):
    inside = ELO <= lay <= EHI
    axA.plot([lay], [v], "o", ms=2.7, color=CURVE if inside else GREY,
             alpha=1.0 if inside else 0.50, mec="white", mew=0.35, zorder=4)
axA.plot([SEL], [JSD24], "o", ms=6.2, color=GOLD, mec="white", mew=1.1, zorder=6)

axA.annotate(f"Selected layer {SEL}\nJSD = {JSD24:.3f} bits", xy=(SEL, JSD24),
             xytext=(24.0, 0.392), fontsize=SMALL, color=GOLD, fontweight="bold",
             ha="center", va="center", linespacing=1.35,
             arrowprops=dict(arrowstyle="-", color=GOLD, lw=0.6, shrinkA=1, shrinkB=3))

# compact legend replaces the former prose sentence
LEG = [(WASH, GREY, "Excluded by eligibility rule", 0.525),
       ("#fbdf9c", GOLD, "Selected window", 0.487)]
for fc, ec, lab, yy in LEG:
    axA.add_patch(Rectangle((1.3, yy - 0.011), 2.1, 0.022, fc=fc, ec=ec, lw=0.5,
                            zorder=5, clip_on=False))
    axA.text(4.3, yy, lab, fontsize=SMALL, color=MUTED, va="center", ha="left", zorder=5)
axA.text(1.3, 0.449, f"Discovery set: {N_DISC} tasks", fontsize=SMALL, color=MUTED,
         va="center", ha="left")

axA.set_xlim(0.4, 31.6); axA.set_ylim(0, 0.556)
axA.set_xticks([1, 5, 10, 15, 20, 24, 28, 31])
axA.set_yticks([0.0, 0.1, 0.2, 0.3, 0.4])
axA.set_xlabel("Layer", fontsize=SMALL, color=INK)
axA.set_ylabel("Jensen-Shannon divergence (bits)", fontsize=SMALL, color=INK)
axA.grid(axis="y", color=FAINT, lw=0.5, zorder=0)
axA.set_axisbelow(True)
axA.spines["left"].set_bounds(0, 0.4)

# ══════════════════════════════════════ (b) grouped coefficient plot
GROUPS = [(1, 2.55, 1.95, 2.25,
           "Low-history activation inserted\ninto no-history evaluation", CORAL),
          (2, 0.45, -0.15, 0.15,
           "No-history activation inserted\ninto low-history evaluation", BLUE)]
axB.axvline(0, color=NAVY, lw=0.9, zorder=4)
yticks, ylabels = [], []
for grp, y24, y2, ymid, glab, gcol in GROUPS:
    yticks.append(ymid); ylabels.append(glab)
    for key, y, col, ms, lw in ((("L24", grp), y24, GOLD, 4.8, 2.3),
                                (("L2", grp), y2, GREY, 3.2, 1.4)):
        m, lo, hi = V[key]
        axB.plot([lo, hi], [y, y], color=col, lw=lw, solid_capstyle="butt", zorder=5)
        for c in (lo, hi):
            axB.plot([c, c], [y - 0.11, y + 0.11], color=col, lw=lw * 0.55, zorder=5)
        axB.plot([m], [y], "o", ms=ms, color=col, mec="white", mew=0.8, zorder=6)
        axB.text(hi + 2.2, y, label(key), va="center", ha="left", fontsize=SMALL,
                 color=col, fontweight="bold", zorder=6)

axB.set_yticks(yticks)
axB.set_yticklabels(ylabels, fontsize=SMALL, linespacing=1.35)
for tick, (_, _, _, _, _, gcol) in zip(axB.get_yticklabels(), GROUPS):
    tick.set_color(gcol)
axB.tick_params(axis="y", length=0, pad=2)

axB.legend(handles=[Line2D([], [], marker="o", ms=4.4, color=GOLD, lw=2.0,
                           label="Layer 24 patch"),
                    Line2D([], [], marker="o", ms=3.0, color=GREY, lw=1.3,
                           label="Layer 2 control")],
           loc="upper left", bbox_to_anchor=(-0.005, 1.16), ncol=2, frameon=False,
           fontsize=SMALL, handlelength=1.5, handletextpad=0.4, columnspacing=1.1,
           labelcolor=[GOLD, GREY])

axB.text(-13.0, -0.92, "0% means no score movement; positive values\n"
                       "indicate movement toward the source score.",
         fontsize=SMALL, color=MUTED, va="center", ha="left", linespacing=1.35)

axB.set_xlim(-14, 70); axB.set_ylim(-1.42, 3.10)
axB.set_xticks([-10, 0, 10, 20, 30, 40])
axB.set_xlabel("Movement toward the source score (% of the original condition gap)",
               fontsize=SMALL, color=INK)
axB.grid(axis="x", color=FAINT, lw=0.5, zorder=0)
axB.set_axisbelow(True)
axB.spines["bottom"].set_bounds(-14, 45)
axB.spines["left"].set_visible(False)

fig.text(0.078, 0.960, "(a) Layerwise Jacobian-Lens readout divergence", fontsize=7.6,
         fontweight="bold", color=NAVY, ha="left", va="top")
fig.text(0.512, 0.960, "(b) Layer 24 transfers about one-fifth of the score gap",
         fontsize=7.6, fontweight="bold", color=NAVY, ha="left", va="top")

for ext, kw in (("pdf", {}), ("svg", {}), ("png", {"dpi": 400})):
    fig.savefig(OUT / f"fig4_mechanistic_evidence_v4.{ext}", facecolor="white", **kw)
plt.close(fig)
print(f"  [save] fig4_mechanistic_evidence_v4.pdf / .svg / .png  ({FIG_W:.3f} x {FIG_H:.3f} in)")
print(f"  Panel A source: {DISC}")
print(f"    {len(BY)} layers | {N_DISC} discovery tasks | eligible L{ELO}..L{EHI} | "
      f"selected L{SEL} | window {WIN} | JSD24 {JSD24:.6f}")
for k in (("L24", 1), ("L2", 1), ("L24", 2), ("L2", 2)):
    print(f"    {k}: {label(k)}   (stored {V[k][0]:.2f} [{V[k][1]:.2f}, {V[k][2]:.2f}])")
