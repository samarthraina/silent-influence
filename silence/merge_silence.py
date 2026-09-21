"""Merge the two judges, compute agreement, then unblind. NOT EXECUTED YET.

Unblinding order matters and is enforced here: agreement between the two judges is computed
BEFORE the key is joined, so no agreement statistic can be influenced by knowing which
condition an item came from.
"""
import argparse
import collections
import csv
import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
LABELS = ["A", "N", "D", "U"]
SEED, N_BOOT = 20260818, 10_000

ap = argparse.ArgumentParser()
ap.add_argument("--j1", default=str(HERE / "judge_J1_raw.jsonl"))
ap.add_argument("--j2", default=str(HERE / "judge_J2_raw.jsonl"))
ap.add_argument("--key", default=str(HERE / "silence_key_PRIVATE.jsonl"))
ap.add_argument("--out-dir", default=str(HERE / "results"))
A = ap.parse_args()
OUT = pathlib.Path(A.out_dir); OUT.mkdir(parents=True, exist_ok=True)


def load(p):
    return {r["item_id"]: r for r in
            (json.loads(l) for l in pathlib.Path(p).open(encoding="utf-8") if l.strip())}


j1, j2 = load(A.j1), load(A.j2)
common = sorted(set(j1) & set(j2))
both_ok = [i for i in common
           if j1[i]["parse_status"] == "ok" and j2[i]["parse_status"] == "ok"]


def kappa(a, b, cats):
    idx = {c: k for k, c in enumerate(cats)}
    n = len(a)
    M = np.zeros((len(cats), len(cats)))
    for x, y in zip(a, b):
        M[idx[x], idx[y]] += 1
    po = np.trace(M) / n
    pe = float((M.sum(0) / n) @ (M.sum(1) / n))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan"), po, M


a_lab = [j1[i]["acknowledgment_label"] for i in both_ok]
b_lab = [j2[i]["acknowledgment_label"] for i in both_ok]
a_ctx = [j1[i]["context_mentioned"] for i in both_ok]
b_ctx = [j2[i]["context_mentioned"] for i in both_ok]
k_lab, po_lab, M_lab = kappa(a_lab, b_lab, LABELS)
k_ctx, po_ctx, M_ctx = kappa(a_ctx, b_ctx, ["yes", "no"])

agreement = {
    "computed_before_unblinding": True,
    "n_items_common": len(common), "n_both_parsed": len(both_ok),
    "parse_failures": {"J1": sum(1 for i in common if j1[i]["parse_status"] != "ok"),
                       "J2": sum(1 for i in common if j2[i]["parse_status"] != "ok")},
    "acknowledgment_label": {"percent_agreement": round(po_lab, 4),
                             "cohens_kappa": round(k_lab, 4),
                             "confusion_rows_J1_cols_J2": M_lab.astype(int).tolist(),
                             "labels": LABELS},
    "context_mentioned": {"percent_agreement": round(po_ctx, 4),
                          "cohens_kappa": round(k_ctx, 4),
                          "confusion_rows_J1_cols_J2": M_ctx.astype(int).tolist(),
                          "labels": ["yes", "no"]},
    "consistency_flags": {"J1": sum(1 for i in both_ok if j1[i].get("consistency_flag")),
                          "J2": sum(1 for i in both_ok if j2[i].get("consistency_flag"))},
}
(OUT / "agreement.json").write_text(json.dumps(agreement, indent=2), encoding="utf-8")

disagree = [{"item_id": i, "J1": j1[i]["acknowledgment_label"],
             "J2": j2[i]["acknowledgment_label"],
             "J1_evidence": j1[i]["evidence"], "J2_evidence": j2[i]["evidence"]}
            for i in both_ok
            if j1[i]["acknowledgment_label"] != j2[i]["acknowledgment_label"]]
with (OUT / "disagreements_for_adjudication.csv").open("w", newline="",
                                                       encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["item_id", "J1", "J2", "J1_evidence", "J2_evidence",
                                      "adjudicated_label"])
    w.writeheader()
    for d in disagree:
        w.writerow({**d, "adjudicated_label": ""})

# ---- only now is the key joined ------------------------------------------------------
key = load(A.key)
rows = []
for i in both_ok:
    k = key[i]
    rows.append({"item_id": i, "scorer_key": k["scorer_key"], "condition": k["condition"],
                 "dataset": k["dataset"], "source_task_id": k["source_task_id"],
                 "analysis_valid": k["analysis_valid"],
                 "J1_label": j1[i]["acknowledgment_label"],
                 "J2_label": j2[i]["acknowledgment_label"],
                 "concordant": j1[i]["acknowledgment_label"] == j2[i]["acknowledgment_label"],
                 "J1_context": j1[i]["context_mentioned"],
                 "J2_context": j2[i]["context_mentioned"]})
with (OUT / "silence_joined.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader(); w.writerows(rows)


def boot_ci(vals_by_task):
    rng = np.random.default_rng(SEED)
    keys = sorted(vals_by_task)
    reps = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(keys), size=len(keys))
        pool = [v for i in idx for v in vals_by_task[keys[i]]]
        reps.append(np.mean(pool) if pool else np.nan)
    r = np.asarray(reps, float); r = r[~np.isnan(r)]
    return float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


# concordant-only rate of explicit acknowledgment, per scorer x condition
summary = {}
conc = [r for r in rows if r["concordant"]]
for scope in ("condition", "scorer_key"):
    d = {}
    for kk in sorted({r[scope] for r in conc}):
        sub = [r for r in conc if r[scope] == kk]
        by_task = collections.defaultdict(list)
        for r in sub:
            by_task[r["source_task_id"]].append(
                1.0 if r["J1_label"] in ("A", "D") else 0.0)
        vals = [v for vs in by_task.values() for v in vs]
        lo, hi = boot_ci(by_task)
        d[kk] = {"n": len(sub), "acknowledged_or_denied_rate": round(float(np.mean(vals)), 4),
                 "ci_low": round(lo, 4), "ci_high": round(hi, 4),
                 "label_counts": dict(collections.Counter(r["J1_label"] for r in sub))}
    summary[scope] = d
grid = {}
for r in conc:
    g = grid.setdefault(f"{r['scorer_key']}/{r['condition']}",
                        collections.Counter())
    g[r["J1_label"]] += 1
summary["scorer_x_condition_label_counts"] = {k: dict(v) for k, v in sorted(grid.items())}
summary["n_concordant"] = len(conc)
summary["n_discordant_excluded"] = len(rows) - len(conc)
summary["note"] = ("rates use concordant items only; discordant items are listed in "
                   "disagreements_for_adjudication.csv and are excluded until adjudicated")
(OUT / "silence_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

print(json.dumps({"agreement": agreement["acknowledgment_label"],
                  "context": agreement["context_mentioned"],
                  "n_concordant": len(conc), "n_discordant": len(disagree)},
                 indent=2))
print(f"[save] {OUT}")
