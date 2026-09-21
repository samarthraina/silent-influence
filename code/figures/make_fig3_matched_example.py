"""Research Figure 3: one real matched example (MT-Bench task 101, Llama scorer).

Every string is read from Brain/figure_inputs/real_example_candidates.json. Nothing is
paraphrased or recomputed; excerpts are verbatim substrings of the stored justification, with
elisions marked "...". Scores are the stored floats rendered as n/10.

Canvas is a fixed 7.0 in wide, saved WITHOUT bbox_inches="tight" so the emitted figure is
exactly 7.0 in. Drawing units are hundredths of an inch (700 x 440) so x and y are isotropic.
All text is live vector text; no raster text anywhere.
"""
import hashlib
import json
import os
import pathlib
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle

# Package-relative: <package>/code/figures/<this file> -> <package>
ROOT = pathlib.Path(os.environ.get(
    "SI_SUPPLEMENT_ROOT", str(pathlib.Path(__file__).resolve().parents[2])))
IN = ROOT / "results/figure_inputs/real_example_candidates.json"
OUT = ROOT / "figures/paper"

EX = next(e for e in json.loads(IN.read_text(encoding="utf-8"))["examples"]
          if e["dataset"] == "mtbench" and str(e["task_id"]) == "101")
C = EX["conditions"]

QUESTION = EX["task_question"]
ANSWER = EX["frozen_answer"]

# Verbatim substrings of the stored justifications; "..." marks an elision, nothing reworded.
EXCERPT = {
    "self_low_2": "The correct answer should be that the person who was just "
                  "overtaken is now in second place, not third.",
    "no_history": "The content directly addresses the question by stating ... "
                  "second place ... third place.",
    "self_high_10": "The content accurately responds ... second place ... third place.",
}
for k, frag in (("self_low_2", EXCERPT["self_low_2"]),):
    assert frag in C[k]["justification"], k          # unelided excerpt must be verbatim
for k in ("no_history", "self_high_10"):             # elided: check each retained fragment
    for piece in [p.strip() for p in EXCERPT[k].split("...")]:
        assert piece.rstrip(".") in C[k]["justification"], (k, piece)

# The figure states that none of the three COMPLETE justifications mentions a prior
# interaction. That was established by reading all three in full, not by pattern matching.
# This hash pins the claim to the exact text that was read: if the stored justifications ever
# change, the build fails and a human must re-read them before the claim is shown again.
_H = hashlib.sha256()
for k in ("self_low_2", "no_history", "self_high_10"):
    _H.update(C[k]["justification"].encode("utf-8"))
assert _H.hexdigest() == "d79f3cf34348388ab560fd1b8a9048207d9bc6fd40ad9e49488d3af76adf44e9", \
    "stored justifications changed: re-read all three before displaying the no-mention claim"

NAVY, BLUE, CORAL, TEAL = "#14345e", "#1f6fd0", "#e2603f", "#12a99a"
INK, MUTED, HAIR = "#161a1f", "#5f6672", "#c9ced6"
TINT = {"self_low_2": "#fdf0ec", "no_history": "#eaf2fc", "self_high_10": "#e7f7f4"}
COL = {"self_low_2": CORAL, "no_history": BLUE, "self_high_10": TEAL}
SMALL = 6.5

plt.rcParams.update({
    "font.family": "DejaVu Sans", "pdf.fonttype": 42, "ps.fonttype": 42,
    "svg.fonttype": "none", "figure.facecolor": "white",
})

W, Hh = 700, 420
fig = plt.figure(figsize=(7.0, Hh / 100.0))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, Hh); ax.axis("off")


def box(x, y, w, h, fc="white", ec=HAIR, lw=0.8, r=4, z=2):
    ax.add_patch(FancyBboxPatch((x + r, y + r), w - 2 * r, h - 2 * r,
                                boxstyle=f"round,pad={r},rounding_size={r}",
                                fc=fc, ec=ec, lw=lw, zorder=z))


def txt(x, y, s, size=SMALL, color=INK, weight="normal", ha="left", va="top", z=5,
        style="normal", ls=1.30):
    return ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va,
                   zorder=z, style=style, linespacing=ls)


def wrap(s, chars):
    return "\n".join(textwrap.wrap(s, chars))


def robot(cx, cy, s=1.0, color="white", lw=1.0):
    """Simple geometric robot: mildly expressive, no cartoon flourishes."""
    ax.add_patch(Rectangle((cx - 6 * s, cy - 5 * s), 12 * s, 10 * s, fc="none", ec=color,
                           lw=lw, zorder=6))
    ax.add_patch(Circle((cx - 2.6 * s, cy + 1.0 * s), 1.25 * s, fc=color, ec="none", zorder=6))
    ax.add_patch(Circle((cx + 2.6 * s, cy + 1.0 * s), 1.25 * s, fc=color, ec="none", zorder=6))
    ax.plot([cx - 2.6 * s, cx + 2.6 * s], [cy - 2.4 * s, cy - 2.4 * s], color=color,
            lw=lw * 0.9, zorder=6, solid_capstyle="round")
    ax.plot([cx, cx], [cy + 5 * s, cy + 7.6 * s], color=color, lw=lw * 0.9, zorder=6)
    ax.add_patch(Circle((cx, cy + 8.4 * s), 1.1 * s, fc=color, ec="none", zorder=6))


# ══════════════════════════════════════════════ locked current-content card
CX, CY, CW, CH = 12, 302, W - 24, 106
box(CX, CY, CW, CH, fc="white", ec=NAVY, lw=1.0)
ax.add_patch(FancyBboxPatch((CX + 4, CY + CH - 26 + 4), CW - 8, 22 - 8,
                            boxstyle="round,pad=4,rounding_size=4", fc=NAVY, ec="none",
                            zorder=3))
robot(CX + 20, CY + CH - 15, s=0.95, color="white", lw=0.9)
txt(CX + 34, CY + CH - 8.5, "CURRENT CONTENT FROM AGENT A", size=7.6, color="white",
    weight="bold", va="center", z=6)
txt(CX + CW - 10, CY + CH - 8.5, "held fixed across all three conditions",
    size=SMALL, color="#c8d6ea", ha="right", va="center", z=6)

txt(CX + 12, CY + CH - 34, "TASK", size=SMALL, color=NAVY, weight="bold")
txt(CX + 74, CY + CH - 34, wrap(QUESTION, 116), size=6.8, color=INK)
ax.plot([CX + 12, CX + CW - 12], [CY + 30, CY + 30], color=HAIR, lw=0.6, zorder=3)
txt(CX + 12, CY + 25, "RESPONSE", size=SMALL, color=NAVY, weight="bold")
txt(CX + 74, CY + 25, ANSWER, size=6.8, color=INK)

# ══════════════════════════════════════════════ branching
txt(W / 2, CY - 8, "Same current content; only the prior-interaction sentence changes",
    size=7.0, color=INK, weight="bold", ha="center", va="top")

GAP, N = 14, 3
CWID = (W - 24 - GAP * (N - 1)) / N
TOP = 266
ORDER = ["self_low_2", "no_history", "self_high_10"]
TITLE = {"self_low_2": "PRIOR 2/10", "no_history": "NO HISTORY", "self_high_10": "PRIOR 10/10"}
CTX = {"self_low_2": C["self_low_2"]["contextual_sentence"],
       "no_history": "No prior-interaction sentence",
       "self_high_10": C["self_high_10"]["contextual_sentence"]}

centres = []
for i, k in enumerate(ORDER):
    x0 = 12 + i * (CWID + GAP)
    cx = x0 + CWID / 2
    centres.append(cx)
    ax.add_patch(FancyArrowPatch((W / 2, CY - 22), (cx, TOP + 4), arrowstyle="-|>",
                                 mutation_scale=7, lw=0.8, color=MUTED,
                                 connectionstyle="arc3,rad=0.0", shrinkA=0, shrinkB=1,
                                 zorder=2))

    # header band
    ax.add_patch(FancyBboxPatch((x0 + 4, TOP - 22 + 4), CWID - 8, 22 - 8,
                                boxstyle="round,pad=4,rounding_size=4", fc=COL[k],
                                ec="none", zorder=3))
    txt(cx, TOP - 11, TITLE[k], size=7.4, color="white", weight="bold", ha="center",
        va="center", z=6)

    # inserted-sentence box
    bh = 40
    box(x0, TOP - 22 - bh - 6, CWID, bh, fc=TINT[k], ec=COL[k], lw=0.7)
    body = wrap(CTX[k], 40)
    txt(cx, TOP - 22 - 6 - bh / 2, body, size=SMALL, color=INK, ha="center", va="center",
        style="italic" if k != "no_history" else "normal")

    # score
    sy = TOP - 22 - bh - 6 - 16
    score = C[k]["score"]
    txt(cx, sy, f"{score:.0f}/10", size=17.0, color=COL[k], weight="bold", ha="center",
        va="top")

    # justification excerpt; the accent rule is sized to the wrapped line count
    ey = sy - 32
    txt(x0 + 4, ey, "JUSTIFICATION (EXCERPT)", size=SMALL, color=MUTED, weight="bold")
    lines = wrap(EXCERPT[k], 42)
    n_lines = len(lines.splitlines())
    ax.plot([x0 + 3, x0 + 3], [ey - 11, ey - 11 - 11.6 * n_lines], color=COL[k], lw=1.6,
            zorder=4, solid_capstyle="round")
    txt(x0 + 10, ey - 11, lines, size=SMALL, color=INK)

# No arrows are drawn between the three scores: the conditions are independent
# evaluations of the same content, not stages of a sequence.

# incorrect-criticism callout, first column only
x0 = 12
cal_y = 80
ax.add_patch(FancyBboxPatch((x0 + 4, cal_y + 3), CWID - 8, 15 - 6,
                            boxstyle="round,pad=3,rounding_size=3", fc=CORAL, ec="none",
                            zorder=4))
txt(x0 + CWID / 2, cal_y + 7.5, "Introduces an incorrect criticism", size=SMALL,
    color="white", weight="bold", ha="center", va="center", z=6)

# Full-width note. The first line describes the three COMPLETE justifications, which were
# read in full to confirm it; the hash guard above pins that reading to this exact text.
# No bracket: the statement now applies to all three columns equally.
ax.plot([12, W - 12], [74, 74], color=HAIR, lw=0.7, zorder=3)
txt(12, 68, "None of the three full justifications explicitly mentions a prior interaction.",
    size=7.0, color=INK)
txt(12, 55, "Systematic context-mention annotation covered the prior-2/10 and "
            "no-history conditions only.", size=SMALL, color=MUTED)

txt(12, 28, "Outcome-selected illustrative example; not used to estimate prevalence.",
    size=SMALL, color=MUTED, style="italic")
txt(W - 12, 28, "MT-Bench task 101  ·  scorer: Llama-3.1-8B  ·  reasoning",
    size=SMALL, color=MUTED, ha="right")

for ext, kw in (("pdf", {}), ("svg", {}), ("png", {"dpi": 400})):
    fig.savefig(OUT / f"fig3_matched_example.{ext}", facecolor="white", **kw)
plt.close(fig)
print(f"  [save] fig3_matched_example.pdf / .svg / .png  ({W/100:.3f} x {Hh/100:.3f} in)")
