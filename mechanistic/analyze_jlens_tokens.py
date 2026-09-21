"""Aggregate the Jacobian-Lens signed token deltas. Rankings are mechanical.

DECLARED RANKING CRITERIA (fixed here, applied identically to every comparison and layer):
  promoted  = the 20 tokens with the LARGEST mean signed delta
  suppressed= the 20 tokens with the SMALLEST (most negative) mean signed delta
  stability = fraction of tasks whose delta has the same sign as the mean
  heatmap set = the 30 tokens at the LOCKED L24 ranked by (stability, |mean delta|),
                taken from the union of that layer's promoted and suppressed lists
No token or example is ever picked by hand, and no layer is selected from these results:
L24 and [23,24,25] are inherited frozen.

SIGN CONVENTION, repeated in every output file and column header:
  positive for A_minus_B  =>  token MORE PROMOTED under condition A.

SUBWORD CAVEAT, carried into every CSV and figure: these are BPE tokenizer fragments, not
words or concepts. A fragment may be a word piece, a leading-space variant, or part of a
longer word; it must not be read as a complete semantic unit.
"""
import argparse
import csv
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
N_TOP, N_HEATMAP, N_BOOT, SEED = 20, 30, 10_000, 20260818
REPORT_LAYERS = [2, 12, 23, 24, 25]          # L24 locked; others descriptive
LOCKED = 24
SUBWORD_NOTE = ("BPE tokenizer fragment, not a word or concept; may be a word piece or a "
                "leading-space variant")

ap = argparse.ArgumentParser()
ap.add_argument("--in-dir", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--tokenizer-vocab", required=True,
                help="json mapping token_id -> exact decoded string")
A = ap.parse_args()

IN, OUT = pathlib.Path(A.in_dir), pathlib.Path(A.out_dir)
(OUT / "csv").mkdir(parents=True, exist_ok=True)
(OUT / "figures").mkdir(parents=True, exist_ok=True)
meta = json.loads((IN / "jlens_tokens_meta.json").read_text(encoding="utf-8"))
COVERED = meta["our_layers_covered"]
VOCAB_STR = json.loads(pathlib.Path(A.tokenizer_vocab).read_text(encoding="utf-8"))


def tokstr(i):
    return VOCAB_STR.get(str(i), "<unk>")


def boot_ci(X, cols):
    """X [n_tasks, n_cols_subset]; bootstrap the mean over tasks via a count matrix."""
    n = X.shape[0]
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, n, size=(N_BOOT, n))
    C = np.zeros((N_BOOT, n), dtype=np.float32)
    for b in range(N_BOOT):
        np.add.at(C[b], idx[b], 1.0)
    C /= n
    reps = C @ X.astype(np.float32)                     # [N_BOOT, n_cols]
    return (np.percentile(reps, 2.5, axis=0), np.percentile(reps, 97.5, axis=0))


summary = {"sign_convention": "positive for A_minus_B => token MORE PROMOTED under A",
           "instrument": meta["instrument"], "is_logit_lens": meta["is_logit_lens"],
           "quantity": meta["quantity"], "locked_layer": LOCKED,
           "locked_window": meta["locked_window"], "layer_not_selected_here": True,
           "ranking_criteria": {"promoted": f"largest mean signed delta, top {N_TOP}",
                                "suppressed": f"smallest mean signed delta, top {N_TOP}",
                                "stability": "fraction of tasks with the mean's sign",
                                "heatmap_set": f"{N_HEATMAP} L{LOCKED} tokens by "
                                               "(stability, |mean|), mechanical"},
           "subword_caveat": SUBWORD_NOTE,
           "bootstrap": {"unit": "task", "n": N_BOOT, "seed": SEED},
           "comparisons": {}}
heat_payload = {}

for comp in meta["comparisons"]:
    arr = np.load(IN / f"delta_{comp}.npy")             # [tasks, layers, vocab] fp16
    n_tasks = arr.shape[0]
    A_name, B_name = comp.split("_minus_")
    mean_all = arr.astype(np.float32).mean(0)           # [layers, vocab]
    sign_all = np.zeros_like(mean_all)
    for li in range(arr.shape[1]):
        s = np.sign(mean_all[li])
        sign_all[li] = (np.sign(arr[:, li, :].astype(np.float32)) == s).mean(0)
    np.savez_compressed(OUT / f"aggregate_{comp}.npz", mean=mean_all,
                        sign_consistency=sign_all, layers=np.array(COVERED))

    comp_out = {"A": A_name, "B": B_name,
                "positive_means": f"more promoted under {A_name}",
                "negative_means": f"more promoted under {B_name}", "layers": {}}

    for L in REPORT_LAYERS:
        if L not in COVERED:
            continue
        li = COVERED.index(L)
        m = mean_all[li]
        order = np.argsort(m)
        sup, pro = order[:N_TOP], order[::-1][:N_TOP]
        sel = np.concatenate([pro, sup])
        lo, hi = boot_ci(arr[:, li, sel].astype(np.float32), sel)

        rows = []
        for k, tid in enumerate(sel):
            rows.append({
                "comparison": comp, "layer_ours": L,
                "role": "promoted" if k < N_TOP else "suppressed",
                "rank": (k % N_TOP) + 1, "token_id": int(tid),
                "token_string_exact": repr(tokstr(int(tid))),
                "mean_signed_delta_logprob": float(m[tid]),
                "ci_low": float(lo[k]), "ci_high": float(hi[k]),
                "sign_consistency": float(sign_all[li, tid]),
                "positive_means_more_promoted_under": A_name,
                "subword_caveat": SUBWORD_NOTE,
            })
        p = OUT / "csv" / f"tokens_{comp}_L{L}.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        comp_out["layers"][f"L{L}"] = {
            "locked" if L == LOCKED else "descriptive": True,
            "csv": p.name,
            "top_promoted": [{"token": repr(tokstr(int(t))), "id": int(t),
                              "mean": float(m[t]),
                              "sign_consistency": float(sign_all[li, t])}
                             for t in pro[:10]],
            "top_suppressed": [{"token": repr(tokstr(int(t))), "id": int(t),
                                "mean": float(m[t]),
                                "sign_consistency": float(sign_all[li, t])}
                               for t in sup[:10]],
        }

    # heatmap set: mechanical, from the LOCKED layer only
    li24 = COVERED.index(LOCKED)
    m24, s24 = mean_all[li24], sign_all[li24]
    order = np.argsort(m24)
    cand = np.concatenate([order[::-1][:N_TOP], order[:N_TOP]])
    rank = sorted(cand, key=lambda t: (-s24[t], -abs(m24[t])))[:N_HEATMAP]
    heat_payload[comp] = {
        "token_ids": [int(t) for t in rank],
        "token_strings": [tokstr(int(t)) for t in rank],
        "matrix": mean_all[:, rank].T.tolist(),          # [tokens, layers]
        "layers": COVERED, "A": A_name, "B": B_name,
    }
    comp_out["heatmap_tokens"] = [{"id": int(t), "token": repr(tokstr(int(t))),
                                   "L24_mean": float(m24[t]),
                                   "L24_sign_consistency": float(s24[t])} for t in rank]
    summary["comparisons"][comp] = comp_out
    del arr

(OUT / "jlens_token_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
(OUT / "heatmap_payload.json").write_text(json.dumps(heat_payload), encoding="utf-8")

for comp, c in summary["comparisons"].items():
    print(f"\n=== {comp}   (+ = more promoted under {c['A']}) ===")
    L24 = c["layers"].get("L24", {})
    print("  L24 promoted :", ", ".join(f"{d['token']}({d['mean']:+.2f},{d['sign_consistency']:.0%})"
                                        for d in L24.get("top_promoted", [])[:6]))
    print("  L24 suppressed:", ", ".join(f"{d['token']}({d['mean']:+.2f},{d['sign_consistency']:.0%})"
                                         for d in L24.get("top_suppressed", [])[:6]))
print(f"\n  [save] {OUT}")
