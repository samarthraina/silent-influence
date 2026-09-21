"""Bar figures for the locked-L24 promoted/suppressed tokens, and all-layer heatmaps.

Token sets come mechanically from analyze_jlens_tokens.py's declared criteria; nothing is
picked by hand here. Sign convention and the subword caveat are printed on every figure.
"""
import csv
import json
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
IN = HERE / "out/jlens_tokens_analysis"
FIG = IN / "figures"
FIG.mkdir(parents=True, exist_ok=True)

INK, MUTED, GRID = "#1a1a1a", "#5c5c5c", "#d8d8d8"
PROMO, SUPP = "#2a78d6", "#eb6834"
CAVEAT = ("BPE tokenizer fragments, not words or concepts (may be word pieces or "
          "leading-space variants)")

plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "figure.dpi": 150,
})
summary = json.loads((IN / "jlens_token_summary.json").read_text(encoding="utf-8"))
heat = json.loads((IN / "heatmap_payload.json").read_text(encoding="utf-8"))


def load_csv(comp, L):
    with (IN / "csv" / f"tokens_{comp}_L{L}.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


for comp, c in summary["comparisons"].items():
    Aname, Bname = c["A"], c["B"]
    rows = load_csv(comp, 24)
    pro = [r for r in rows if r["role"] == "promoted"]
    sup = [r for r in rows if r["role"] == "suppressed"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 5.4))
    for ax, grp, col, ttl in ((ax1, pro, PROMO, f"promoted under {Aname}"),
                              (ax2, sup, SUPP, f"promoted under {Bname}")):
        grp = sorted(grp, key=lambda r: abs(float(r["mean_signed_delta_logprob"])))
        y = np.arange(len(grp))
        m = [float(r["mean_signed_delta_logprob"]) for r in grp]
        lo = [float(r["ci_low"]) for r in grp]
        hi = [float(r["ci_high"]) for r in grp]
        err = [[abs(mm - l) for mm, l in zip(m, lo)], [abs(h - mm) for mm, h in zip(m, hi)]]
        ax.barh(y, m, color=col, height=0.72, edgecolor="white", linewidth=0.6)
        ax.errorbar(m, y, xerr=err, fmt="none", ecolor=INK, elinewidth=1, capsize=2.5)
        labs = [f"{eval(r['token_string_exact'])!r}  {float(r['sign_consistency']):.0%}"
                for r in grp]
        ax.set_yticks(y); ax.set_yticklabels(labs, fontsize=7.5, family="monospace")
        ax.axvline(0, color=INK, lw=1)
        ax.set_xlabel("mean signed delta (log-prob)")
        ax.set_title(ttl, fontsize=9.5, loc="left")
        ax.grid(axis="x", color=GRID, lw=0.6); ax.set_axisbelow(True)

    fig.suptitle(f"Jacobian-Lens signed token deltas at LOCKED L24  ·  {comp}\n"
                 f"positive = MORE PROMOTED under {Aname}   ·   negative = more promoted "
                 f"under {Bname}   ·   72 tasks, 95% task-bootstrap CI, % = sign consistency\n"
                 f"{CAVEAT}", fontsize=9.5, x=0.005, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"bar_L24_{comp}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [save] bar_L24_{comp}.pdf/.png")

    # ---- all-layer heatmap of the mechanically chosen stable L24 tokens ---------------
    h = heat[comp]
    M = np.asarray(h["matrix"])                    # [tokens, layers]
    layers = h["layers"]
    fig, ax = plt.subplots(figsize=(11.5, 6.4))
    vmax = float(np.abs(M).max())
    im = ax.imshow(M, aspect="auto", cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(layers)))
    ax.set_xticklabels(layers, fontsize=7)
    ax.set_yticks(range(len(h["token_strings"])))
    ax.set_yticklabels([repr(s) for s in h["token_strings"]], fontsize=7,
                       family="monospace")
    for L in (23, 24, 25):
        if L in layers:
            ax.axvline(layers.index(L), color=INK, lw=0.9, ls=(0, (2, 2)))
    ax.set_xlabel("our layer index (L1 = output of block 0)   ·   dashed = locked window "
                  "[23,24,25]")
    cb = fig.colorbar(im, ax=ax, pad=0.012)
    cb.set_label(f"mean signed delta (log-prob)\n+ = more promoted under {Aname}",
                 fontsize=8)
    ax.set_title(f"Depth trajectory of the 30 most stable L24 tokens  ·  {comp}\n"
                 f"token set chosen mechanically at LOCKED L24 by (sign consistency, "
                 f"|mean|); no layer selected from these results\n{CAVEAT}",
                 fontsize=9.5, loc="left")
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(FIG / f"heatmap_{comp}.{ext}", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [save] heatmap_{comp}.pdf/.png")
print("done")
