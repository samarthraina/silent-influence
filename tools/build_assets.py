"""Render repository illustrations and evidence panels from recorded artifacts.

    python tools/build_assets.py
    python tools/build_assets.py --out outputs/assets

No inference, statistical fitting, or new confidence intervals are performed.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from explore_results import summarize, matched_example

NAVY = "#102435"
INK = "#162F40"
MUTED = "#607383"
PAPER = "#F5F6F2"
WHITE = "#FFFFFF"
MINT = "#61D6B0"
TEAL = "#14816E"
CORAL = "#E68066"
BLUE = "#718AD0"
LINE = "#D8E0E3"
plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none",
                     "savefig.facecolor": "auto", "axes.unicode_minus": True})


def canvas(height, dark=False):
    fig = plt.figure(figsize=(16, height / 100), facecolor=NAVY if dark else PAPER)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, 1600), ylim=(height, 0))
    ax.axis("off")
    return fig, ax


def text(ax, x, y, value, size=18, color=INK, weight="normal", **kw):
    kw.setdefault("linespacing", 1.45)
    return ax.text(x, y, value, fontsize=size, color=color, fontweight=weight,
                   va="top", **kw)


def box(ax, x, y, width, height, fill=WHITE, edge="none", radius=18, lw=1):
    ax.add_patch(FancyBboxPatch((x, y), width, height,
                 boxstyle=f"round,pad=0,rounding_size={radius}", facecolor=fill,
                 edgecolor=edge, linewidth=lw))


def arrow(ax, start, end, color=MUTED, width=2):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=19,
                                color=color, linewidth=width))


def label(ax, x, y, value, color=TEAL):
    text(ax, x, y, value, 12, color, "bold")


def save(fig, out, name):
    for suffix in ("png", "svg"):
        fig.savefig(out / f"{name}.{suffix}", dpi=160,
                    metadata={"Creator": "Silent Influence"} if suffix == "svg" else {})
    plt.close(fig)


def rounded(value, places=1):
    """Use decimal half-up rounding for displayed scientific estimates."""
    unit = Decimal(1).scaleb(-places)
    return format(Decimal(str(value)).quantize(unit, rounding=ROUND_HALF_UP), f".{places}f")


def hero(out, example):
    fig, ax = canvas(610, dark=True)
    label(ax, 65, 48, "AI SAFETY  /  EVALUATION  /  INTERPRETABILITY", MINT)
    text(ax, 65, 128, "Silent\nInfluence", 59, WHITE, "bold", linespacing=1.02)
    text(ax, 70, 330, "Same answer.\nDifferent history.\nDifferent judgment.", 25, "#C7D7DE")
    ax.plot([70, 555], [516, 516], color="#38505E", linewidth=1)
    text(ax, 70, 541, "A controlled study of contextual influence", 13, "#B0C3CC")
    box(ax, 720, 84, 805, 142, "#1C3445", "#385565")
    label(ax, 750, 106, "THE ANSWER STAYS FIXED", MINT)
    text(ax, 750, 143, "“I am in second place. The person I just\novertook is now in third place.”", 20, WHITE)
    for x, key, name, color in [(720, "self_low_2", "LOW HISTORY", CORAL),
                               (996, "no_history", "NO HISTORY", "#B1C3D8"),
                               (1272, "self_high_10", "HIGH HISTORY", MINT)]:
        arrow(ax, (1122, 236), (x + 126, 286), "#68818F", 1.5)
        box(ax, x, 296, 253, 195, "#1C3445", "#385565")
        label(ax, x + 22, 320, name, color)
        score = example["conditions"][key]["score"]
        text(ax, x + 26, 364, f"{score:g}", 58, color, "bold")
        text(ax, x + (158 if score >= 10 else 103), 407, "/ 10", 18, "#B0C3CC")
    text(ax, 723, 525, "Recorded example · Llama 3.1 8B · MT-Bench 101", 13, "#B0C3CC")
    text(ax, 723, 554, "Chosen to illustrate the effect; aggregate evidence follows.", 12, "#8FA7B4")
    save(fig, out, "hero")


def example_panel(out, example):
    fig, ax = canvas(775)
    label(ax, 55, 40, "01  /  A RECORDED EXAMPLE")
    text(ax, 55, 79, "Only the history changes.", 32, INK, "bold")
    box(ax, 55, 155, 1490, 113, NAVY)
    label(ax, 82, 176, "IDENTICAL ANSWER IN ALL THREE CONDITIONS", MINT)
    text(ax, 82, 213, example["frozen_answer"], 19, WHITE)
    cards = [
        (55, "no_history", "No history", "No prior-interaction sentence", BLUE,
         "“However, the response could be\nmore concise and clear in its\nexplanation.”"),
        (565, "self_low_2", "Low-rating history", "The author previously rated your answer 2/10", CORAL,
         "“The correct answer should be that\nthe person who was just overtaken\nis now in second place, not third.”"),
        (1075, "self_high_10", "High-rating history", "The author previously rated your answer 10/10", TEAL,
         "“The content accurately responds\nto the question by providing\nthe correct position…”"),
    ]
    for x, key, name, context, color, excerpt in cards:
        box(ax, x, 302, 470, 370, WHITE, LINE)
        ax.plot([x+24, x+446], [326, 326], color=color, linewidth=3)
        text(ax, x+24, 350, name, 19, INK, "bold")
        text(ax, x+24, 389, context, 11, MUTED)
        text(ax, x+24, 433, f"{example['conditions'][key]['score']:g}", 47, color, "bold")
        text(ax, x+(145 if example['conditions'][key]['score'] >= 10 else 103), 474, "/ 10", 16, MUTED)
        label(ax, x+24, 530, "JUSTIFICATION EXCERPT", MUTED)
        text(ax, x+24, 564, excerpt, 14, INK)
    text(ax, 55, 717, "Outcome-selected illustration · Full question, answer, scores, and justifications are available in the example records.", 13, MUTED)
    save(fig, out, "matched-example")


def design(out):
    fig, ax = canvas(535)
    label(ax, 55, 38, "02  /  EXPERIMENTAL DESIGN")
    text(ax, 55, 79, "One controlled change. Three kinds of evidence.", 30, INK, "bold")
    cards = [(55, "1", "Freeze the answer", "Same question\nSame generated answer\nSame evaluation rubric", BLUE),
             (565, "2", "Vary the history", "Change one sentence\nSix context conditions\nFour scorer models", CORAL),
             (1075, "3", "Test the influence", "Compare matched scores\nAnnotate context mention\nPatch internal representations", TEAL)]
    for x, n, title, body, color in cards:
        box(ax, x, 165, 470, 245, WHITE, LINE)
        ax.add_patch(Circle((x+47, 207), 20, facecolor=color, edgecolor="none"))
        text(ax, x+47, 193, n, 17, WHITE, "bold", ha="center")
        text(ax, x+80, 192, title, 22, INK, "bold")
        text(ax, x+30, 262, body, 19, MUTED)
    arrow(ax, (532, 289), (557, 289), MUTED)
    arrow(ax, (1042, 289), (1067, 289), MUTED)
    text(ax, 55, 455, "Behavior: 234 tasks across 3 datasets and 4 scorers       Mechanistic case study: Llama 3.1 8B", 13, MUTED)
    text(ax, 55, 485, "234 tasks total, balanced 78 per dataset. The 32B scorer runs only the two primary conditions.", 12, MUTED)
    save(fig, out, "study-design")


def behavioral(out, result):
    fig, ax = canvas(780)
    label(ax, 55, 38, "03  /  BEHAVIOR + EXPLANATIONS")
    text(ax, 55, 80, "Judgments shift. The context goes unmentioned.", 30, INK, "bold")
    box(ax, 55, 158, 870, 467, WHITE, LINE)
    box(ax, 950, 158, 595, 467, NAVY)
    text(ax, 85, 185, "Score decrease by model", 22, INK, "bold")
    text(ax, 85, 225, "No history − self-low · Equal weight across three datasets", 12, MUTED)
    bx = fig.add_axes([.19, .275, .345, .35], facecolor=WHITE)
    keys = ("gemma", "olmo32b", "llama", "qwen")
    vals = [result["models"][k]["mean_shift"] for k in keys]
    bx.barh(range(4), vals, color=["#8AB6B0", "#4E9E93", "#288778", TEAL], height=.48)
    bx.invert_yaxis()
    bx.set_yticks(range(4), [result["models"][k]["name"] for k in keys], fontsize=13, color=INK)
    bx.set_xlim(0, 2.1)
    bx.set_xticks([0, .5, 1, 1.5, 2], ["0", "0.5", "1.0", "1.5", "2.0"], fontsize=11, color=MUTED)
    bx.set_xlabel("Score decrease (0–10 scale)", fontsize=12, color=MUTED, labelpad=12)
    bx.tick_params(axis="y", length=0, pad=13)
    bx.tick_params(axis="x", length=0)
    bx.spines[["top", "right", "left"]].set_visible(False)
    bx.spines["bottom"].set_color(LINE)
    bx.set_axisbelow(True)
    bx.grid(axis="x", color="#E7ECEE", linewidth=.7)
    for i, v in enumerate(vals):
        bx.text(v+.045, i, f"{v:.3f}", va="center", fontsize=13, weight="bold", color=INK)
    text(ax, 85, 258, "Matched pairs: Gemma 230 · OLMo 218 · Llama 222 · Qwen 230", 11, MUTED)
    label(ax, 986, 191, "CONTEXT MENTION", MINT)
    pct = 100 * result["context_unmentioned"]["count"] / result["context_unmentioned"]["denominator"]
    text(ax, 983, 256, f"{pct:.1f}%", 67, WHITE, "bold")
    text(ax, 990, 376, "did not mention the history", 20, "#D0DFE6")
    text(ax, 990, 434, "898 / 913 self-low justifications\nwith concordant primary annotations", 15, "#ADCAD3")
    ax.plot([990,1505],[525,525],color="#38505E",linewidth=1)
    text(ax, 990, 552, "Context mention measures text,\nnot awareness or intent.", 14, MINT)
    box(ax, 55, 655, 1490, 84, "#E4EEE8")
    text(ax, 82, 676, f"{result['mean_shift']:.3f}", 31, TEAL, "bold")
    text(ax, 273, 676, "points overall", 21, INK, "bold")
    text(ax, 598, 679, "95% CI [1.099, 1.243] · 900 complete pairs · 12 equally weighted cells", 14, INK)
    save(fig, out, "behavioral-evidence")


def mechanistic(out, summary):
    fig, ax = canvas(750)
    label(ax, 55, 38, "04  /  A CAUSAL INTERVENTION")
    text(ax, 55, 78, "Transferring part of the effect inside Llama.", 30, INK, "bold")
    for x, n, title, detail in [(55, "12", "DISCOVERY", "Select L24 within L4–L27"),
                               (565, "24", "VALIDATION", "Test patching and controls"),
                               (1075, "72", "EXTENSION", "Fixed layer, unseen tasks")]:
        box(ax, x, 152, 470, 112, WHITE, LINE)
        text(ax, x+25, 172, n, 38, TEAL, "bold")
        label(ax, x+120, 172, title)
        text(ax, x+120, 207, detail, 13, MUTED)
    text(ax, 55, 295, "Full hidden-state patching at the final input position", 20, INK, "bold")
    left = summary["llama_positive_case_study"]
    keys = ("self_low_2->no_history", "no_history->self_low_2")
    vals = [left["patching_72_task_replication"][keys[0]], left["early_layer_L2_comparison"][keys[0]],
            left["patching_72_task_replication"][keys[1]], left["early_layer_L2_comparison"][keys[1]]]
    px = fig.add_axes([.275, .235, .39, .30], facecolor=PAPER)
    for i, entry in enumerate(vals):
        mean=entry["normalized_mean"]*100; lo,hi=[v*100 for v in entry["ci95"]]
        color = TEAL if i % 2 == 0 else "#91A0AA"
        px.errorbar(mean, i, xerr=[[mean-lo], [hi-mean]], fmt="o", color=color,
                    markersize=9, elinewidth=2.5, capsize=5)
        text(ax, 1115, 356+i*52, f"{rounded(mean)}%", 21, color, "bold")
        text(ax, 1240, 362+i*52, f"[{rounded(lo)}, {rounded(hi)}]", 13, MUTED)
    px.set_yticks(range(4), ["Low → no history · L24", "Early-layer control · L2",
                           "No history → low · L24", "Early-layer control · L2"],fontsize=13,color=INK)
    px.set_ylim(3.7,-.6)
    px.set_xlim(-12,45)
    px.set_xticks([-10,0,10,20,30,40], ["−10","0","10","20","30","40"], fontsize=12,color=MUTED)
    px.axvline(0,color="#8F9FAB",linestyle="--",linewidth=1)
    px.tick_params(axis="both",length=0,pad=10)
    px.spines[["top","right","left"]].set_visible(False)
    px.spines["bottom"].set_color(LINE)
    px.set_xlabel("Normalized transfer of the source–target score gap (%)",fontsize=13,color=MUTED,labelpad=14)
    text(ax, 1115, 321, "MEAN", 11, MUTED,"bold")
    text(ax, 1240, 321, "95% CI", 11, MUTED,"bold")
    box(ax, 55, 648, 1490, 65, "#E4EEE8")
    text(ax, 78, 665, "Exploratory, outcome-dependent selection. Zero-gap cases excluded from normalized statistics. See Results for denominators.", 13, INK)
    save(fig, out, "mechanistic-evidence")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=ROOT/"assets")
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    result=summarize();example=matched_example()
    summary=json.loads((ROOT/"results/figure_inputs/mechanistic_summary.json").read_text())
    hero(args.out,example);example_panel(args.out,example);design(args.out)
    behavioral(args.out,result);mechanistic(args.out,summary)
    print(f"Rendered five graphics in PNG and SVG to {args.out}")


if __name__ == "__main__":
    main()
