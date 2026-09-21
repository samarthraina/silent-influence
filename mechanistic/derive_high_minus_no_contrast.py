"""Derive the self_high_10 - no_history Jacobian-Lens token contrast at the locked layer.

This contrast supports Table 3, row 2 of the main paper. It was not stored directly. It is
recovered deterministically from two retained raw contrasts by exact algebraic composition:

    (self_high_10 - self_low_2) + (self_low_2 - no_history) = self_high_10 - no_history

Every quantity is a difference of log-probabilities at the same position, layer, task, and
vocabulary index, so the identity is exact term by term; self_low_2 cancels. No model is
loaded, no GPU is used, and no value is re-estimated.

Aggregation replicates analyze_jlens_tokens.py exactly:
    mean            = arr.astype(float32).mean(axis=0)        over the 72 tasks
    sign_consistency= fraction of tasks whose delta has the sign of that mean
    promoted        = largest mean signed delta; suppressed = smallest

Inputs are the two raw tensors, which are too large for the research package. They live in
the verified archive named in the provenance record. Point --raw-dir at a directory holding
them, or use the shipped per-task CSV, which independently permits recomputing every mean.

    python mechanistic/derive_high_minus_no_contrast.py --raw-dir <dir> --out-dir <dir>
    python mechanistic/derive_high_minus_no_contrast.py --verify-only   # checks shipped CSVs
"""
import argparse
import csv
import hashlib
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE.parent

A_NAME = "delta_self_high_10_minus_self_low_2.npy"   # A = high - low
B_NAME = "delta_self_low_2_minus_no_history.npy"     # B = low  - no
A_SHA = "af11d58b50ea5855c38cea7badd245a287b89b043ac57426edd3ab7f1d0343d7"
B_SHA = "7cb7918b4fce4a0e799b41bfaeade34cb30094ad4d784be6ca4bbf1a0ad472ab"
SOURCE_ARCHIVE = "mech_llama_full_archive_2026-08-18.tar.gz"

# the four values printed in main-paper Table 3, row 2; positive favours high history
PAPER_TABLE3_ROW2 = {" brief": +4.98, " excellent": +4.00, " perfectly": +3.92,
                     " score": -1.39}
N_TOP = 20

ap = argparse.ArgumentParser()
ap.add_argument("--raw-dir", default=None, help="directory holding the two raw .npy tensors")
ap.add_argument("--out-dir", default=str(PKG / "results/mechanistic/jlens_derived"))
ap.add_argument("--verify-only", action="store_true",
                help="re-check the shipped CSVs without needing the raw tensors")
A = ap.parse_args()
OUT = pathlib.Path(A.out_dir)
PERTASK = OUT / "high_minus_no_history_L24_per_task.csv"
SUMMARY = OUT / "high_minus_no_history_L24_summary.csv"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def assert_paper_values(mean_by_tok, label):
    """Fail loudly on drift from the four values the main paper prints."""
    bad = []
    for tok, want in PAPER_TABLE3_ROW2.items():
        got = mean_by_tok.get(tok)
        if got is None or abs(round(got, 2) - want) > 1e-9:
            bad.append(f"{tok!r}: want {want:+.2f}, got {got if got is None else round(got, 4)}")
    if bad:
        raise AssertionError(f"{label}: main-paper Table 3 row 2 did not reproduce -> " + "; ".join(bad))
    print(f"  [assert] {label}: all four main-paper values reproduce exactly")


# ── verify-only: recompute the means straight from the shipped per-task CSV ────────────
if A.verify_only:
    if not PERTASK.exists():
        sys.exit(f"missing {PERTASK}")
    rows = list(csv.DictReader(PERTASK.open(encoding="utf-8")))
    acc, cnt = {}, {}
    for r in rows:
        t = r["token_string"]
        acc[t] = acc.get(t, 0.0) + float(r["signed_projected_difference"])
        cnt[t] = cnt.get(t, 0) + 1
    means = {t: acc[t] / cnt[t] for t in acc}
    print(f"  recomputed {len(means)} token means from {len(rows)} per-task rows")
    assert_paper_values(means, "shipped per-task CSV")
    sm = {r["token_string"]: float(r["mean_signed_delta_logprob"])
          for r in csv.DictReader(SUMMARY.open(encoding="utf-8"))}
    drift = [t for t in sm if abs(sm[t] - means[t]) > 5e-4]
    if drift:
        raise AssertionError(f"summary disagrees with per-task rows for {drift[:5]}")
    print(f"  [assert] summary CSV agrees with the per-task rows for all {len(sm)} tokens")
    sys.exit(0)

# ── derive from the raw tensors ───────────────────────────────────────────────────────
if not A.raw_dir:
    sys.exit("--raw-dir is required unless --verify-only is given")
RAW = pathlib.Path(A.raw_dir)
META = json.loads((RAW / "jlens_tokens_meta.json").read_text(encoding="utf-8"))
LI = META["our_layers_covered"].index(META["locked_layer"])
TASKS = META["tasks"]

a_sha, b_sha = sha(RAW / A_NAME), sha(RAW / B_NAME)
assert a_sha == A_SHA, f"{A_NAME} hash drift: {a_sha}"
assert b_sha == B_SHA, f"{B_NAME} hash drift: {b_sha}"
print(f"  [assert] both source tensors match their recorded SHA-256")

Aarr = np.load(RAW / A_NAME, mmap_mode="r")[:, LI, :].astype(np.float32)
Barr = np.load(RAW / B_NAME, mmap_mode="r")[:, LI, :].astype(np.float32)
D = Aarr + Barr                                   # exact composition, per task and token
mean_d = D.mean(0)
sign_cons = (np.sign(D) == np.sign(mean_d)).mean(0)

VOC = json.loads((PKG / "results/mechanistic/jlens/vocab_strings_repaired.json")
                 .read_text(encoding="utf-8"))
vocab = [VOC[str(i)] for i in range(len(VOC))] if isinstance(VOC, dict) else VOC

order = np.argsort(mean_d)
sel = list(order[:N_TOP]) + list(order[-N_TOP:][::-1])      # suppressed then promoted
means = {vocab[int(t)]: float(mean_d[int(t)]) for t in sel}
assert_paper_values(means, "derived from raw tensors")

OUT.mkdir(parents=True, exist_ok=True)
with PERTASK.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["task_id", "dataset", "token_id", "token_string",
                "signed_projected_difference", "contrast_orientation", "layer", "position"])
    for ti, tk in enumerate(TASKS):
        for t in sel:
            w.writerow([tk["task_id"], tk["dataset"], int(t), vocab[int(t)],
                        f"{float(D[ti, int(t)]):.6f}", "self_high_10_minus_no_history",
                        META["locked_layer"], META["position"]])

with SUMMARY.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["token_id", "token_string", "mean_signed_delta_logprob", "sign_consistency",
                "n_tasks", "role", "sorting_rule"])
    for t in sel:
        t = int(t)
        w.writerow([t, vocab[t], f"{float(mean_d[t]):.6f}", f"{float(sign_cons[t]):.4f}",
                    D.shape[0], "suppressed" if mean_d[t] < 0 else "promoted",
                    f"mean signed delta; top {N_TOP} each end"])

prov = {
    "derived_contrast": "self_high_10_minus_no_history",
    "why": "supports main-paper Table 3, row 2; not stored directly",
    "formula": "(self_high_10 - self_low_2) + (self_low_2 - no_history)",
    "exactness": "difference of log-probabilities at identical position, layer, task and "
                 "vocabulary index; self_low_2 cancels term by term",
    "orientation": "positive favours self_high_10; negative favours no_history",
    "layer": META["locked_layer"], "position": META["position"],
    "n_tasks": D.shape[0], "vocab_size": int(D.shape[1]),
    "aggregation": "arr.astype(float32).mean(axis=0), matching analyze_jlens_tokens.py",
    "instrument": META["instrument"], "is_logit_lens": META["is_logit_lens"],
    "source_tensors": [
        {"name": A_NAME, "role": "self_high_10 - self_low_2", "sha256": a_sha,
         "shipped": False, "archive": SOURCE_ARCHIVE},
        {"name": B_NAME, "role": "self_low_2 - no_history", "sha256": b_sha,
         "shipped": False, "archive": SOURCE_ARCHIVE}],
    "outputs": [{"name": PERTASK.name, "sha256": sha(PERTASK)},
                {"name": SUMMARY.name, "sha256": sha(SUMMARY)}],
    "paper_table3_row2_reproduced": {k.strip(): v for k, v in PAPER_TABLE3_ROW2.items()},
    "reverify": "python mechanistic/derive_high_minus_no_contrast.py --verify-only",
}
(OUT / "DERIVATION_PROVENANCE.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")
print(f"  wrote {PERTASK.name} ({len(TASKS)*len(sel)} rows), {SUMMARY.name} ({len(sel)} rows), "
      f"DERIVATION_PROVENANCE.json")
