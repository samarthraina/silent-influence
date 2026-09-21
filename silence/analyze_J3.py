"""J3 (gpt-oss-20b) integrity + agreement against J1, J2 and their frozen consensus.

Runs only after judge_J3_gptoss_raw.jsonl is complete and frozen. J1, J2, the key and every
other file read here were unavailable to the judge process; the ordering is the point.

The kappa routine is copied verbatim from merge_silence.py so J3 statistics are computed the
same way the archived J1/J2 statistics were.

Consensus follows the frozen definition in merge_silence.py: an item is consensus iff J1 and
J2 assigned the same acknowledgment_label. Discordant items stay excluded, unadjudicated.
"""
import argparse
import collections
import csv
import hashlib
import json
import pathlib

import numpy as np

LABELS = ("A", "N", "D", "U")

ap = argparse.ArgumentParser()
ap.add_argument("--j1", required=True)
ap.add_argument("--j2", required=True)
ap.add_argument("--j3", required=True)
ap.add_argument("--items", required=True)
ap.add_argument("--key", default=None, help="unblinding; condition rates only")
ap.add_argument("--human-dir", default=None)
ap.add_argument("--out", required=True)
A = ap.parse_args()


def load(p):
    return {r["item_id"]: r for r in
            (json.loads(l) for l in pathlib.Path(p).open(encoding="utf-8") if l.strip())}


def kappa(a, b, cats):
    idx = {c: k for k, c in enumerate(cats)}
    n = len(a)
    M = np.zeros((len(cats), len(cats)))
    for x, y in zip(a, b):
        M[idx[x], idx[y]] += 1
    po = np.trace(M) / n
    pe = float((M.sum(0) / n) @ (M.sum(1) / n))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan"), po, M


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


j1, j2, j3 = load(A.j1), load(A.j2), load(A.j3)
expected = [json.loads(l)["item_id"] for l in
            pathlib.Path(A.items).open(encoding="utf-8") if l.strip()]
exp = set(expected)

R = {"inputs": {"J3_file": pathlib.Path(A.j3).name, "J3_sha256": sha(A.j3),
                "items_sha256": sha(A.items)}}

# ---- step 7: integrity --------------------------------------------------------------
n_raw = sum(1 for l in pathlib.Path(A.j3).open(encoding="utf-8") if l.strip())
ok3 = {i for i, r in j3.items() if r["parse_status"] == "ok"}
R["integrity"] = {
    "expected_items": len(exp), "rows_written": n_raw, "unique_ids": len(j3),
    "duplicate_rows": n_raw - len(j3),
    "missing_ids": sorted(exp - set(j3))[:20], "n_missing": len(exp - set(j3)),
    "unexpected_ids": sorted(set(j3) - exp)[:20], "n_unexpected": len(set(j3) - exp),
    "parse_ok": len(ok3), "parse_failures": len(j3) - len(ok3),
    "parse_success_rate": round(len(ok3) / len(j3), 6) if j3 else None,
    "parse_failure_status_counts": dict(collections.Counter(
        r["parse_status"] for r in j3.values() if r["parse_status"] != "ok")),
    "consistency_flags": sum(1 for r in j3.values() if r.get("consistency_flag")),
    "model_revisions_seen": sorted({r["revision"] for r in j3.values()}),
}
nonN = [r for r in j3.values() if r["parse_status"] == "ok"
        and r["acknowledgment_label"] != "N"]
R["integrity"]["non_N_predictions"] = len(nonN)
R["integrity"]["non_N_with_evidence_span"] = sum(1 for r in nonN if r["evidence"].strip())
R["label_distribution"] = {
    "J3": dict(collections.Counter(r["acknowledgment_label"] for r in j3.values()
                                   if r["parse_status"] == "ok")),
    "J1": dict(collections.Counter(r["acknowledgment_label"] for r in j1.values()
                                   if r["parse_status"] == "ok")),
    "J2": dict(collections.Counter(r["acknowledgment_label"] for r in j2.values()
                                   if r["parse_status"] == "ok")),
    "J3_context_mentioned": dict(collections.Counter(
        r["context_mentioned"] for r in j3.values() if r["parse_status"] == "ok")),
}


def pair(x, y, name):
    common = sorted(set(x) & set(y))
    both = [i for i in common
            if x[i]["parse_status"] == "ok" and y[i]["parse_status"] == "ok"]
    xl = [x[i]["acknowledgment_label"] for i in both]
    yl = [y[i]["acknowledgment_label"] for i in both]
    xc = [x[i]["context_mentioned"] for i in both]
    yc = [y[i]["context_mentioned"] for i in both]
    kl, pol, Ml = kappa(xl, yl, LABELS)
    kc, poc, Mc = kappa(xc, yc, ("yes", "no"))
    # binary acknowledgment: A alone, and reference-present {A, D} as the frozen summary uses
    xa = ["A" if v == "A" else "not_A" for v in xl]
    ya = ["A" if v == "A" else "not_A" for v in yl]
    ka, poa, Ma = kappa(xa, ya, ("A", "not_A"))
    xr = ["ref" if v in ("A", "D") else "no_ref" for v in xl]
    yr = ["ref" if v in ("A", "D") else "no_ref" for v in yl]
    kr, por, Mr = kappa(xr, yr, ("ref", "no_ref"))
    return {"pair": name, "n_common": len(common), "n_both_parsed": len(both),
            "four_way_label": {
                "percent_agreement": round(pol, 4),
                "cohens_kappa": round(float(kl), 4),
                "confusion_rows_first_cols_second": {
                    c: dict(zip(LABELS, map(int, Ml[k]))) for k, c in enumerate(LABELS)}},
            "binary_acknowledgment_A_vs_rest": {
                "percent_agreement": round(poa, 4), "cohens_kappa": round(float(ka), 4),
                "confusion": {"A": dict(zip(("A", "not_A"), map(int, Ma[0]))),
                              "not_A": dict(zip(("A", "not_A"), map(int, Ma[1])))}},
            "binary_reference_present_A_or_D": {
                "percent_agreement": round(por, 4), "cohens_kappa": round(float(kr), 4)},
            "binary_context_mentioned": {
                "percent_agreement": round(poc, 4), "cohens_kappa": round(float(kc), 4),
                "confusion": {"yes": dict(zip(("yes", "no"), map(int, Mc[0]))),
                              "no": dict(zip(("yes", "no"), map(int, Mc[1])))}}}


R["pairwise"] = {k: pair(*v) for k, v in {
    "J1_vs_J2": (j1, j2, "J1 (Qwen3-8B) vs J2 (gemma-2-9b-it)"),
    "J3_vs_J1": (j3, j1, "J3 (gpt-oss-20b) vs J1 (Qwen3-8B)"),
    "J3_vs_J2": (j3, j2, "J3 (gpt-oss-20b) vs J2 (gemma-2-9b-it)")}.items()}

# ---- three-judge structure and the frozen consensus ---------------------------------
tri = [i for i in sorted(exp) if all(d.get(i, {}).get("parse_status") == "ok"
                                     for d in (j1, j2, j3))]
lab = {i: (j1[i]["acknowledgment_label"], j2[i]["acknowledgment_label"],
           j3[i]["acknowledgment_label"]) for i in tri}
R["three_judge"] = {
    "n_all_three_parsed": len(tri),
    "unanimous": sum(1 for v in lab.values() if len(set(v)) == 1),
    "two_of_three": sum(1 for v in lab.values() if len(set(v)) == 2),
    "all_three_differ": sum(1 for v in lab.values() if len(set(v)) == 3),
}
n_it = len(tri)
P = []
pj = collections.Counter()
for v in lab.values():
    c = collections.Counter(v)
    pj.update(c)
    P.append((sum(x * x for x in c.values()) - 3) / (3 * 2))
pbar = float(np.mean(P))
pe = sum((pj[c] / (3 * n_it)) ** 2 for c in LABELS)
R["three_judge"]["fleiss_kappa_4cat"] = round((pbar - pe) / (1 - pe), 4)

cons = {i: j1[i]["acknowledgment_label"] for i in sorted(set(j1) & set(j2))
        if j1[i]["parse_status"] == "ok" and j2[i]["parse_status"] == "ok"
        and j1[i]["acknowledgment_label"] == j2[i]["acknowledgment_label"]}
cc = [i for i in cons if i in ok3]
cl = [cons[i] for i in cc]
gl = [j3[i]["acknowledgment_label"] for i in cc]
kk, po, M = kappa(cl, gl, LABELS)
ca = ["A" if v == "A" else "not_A" for v in cl]
ga = ["A" if v == "A" else "not_A" for v in gl]
ka, poa, Ma = kappa(ca, ga, ("A", "not_A"))
R["vs_frozen_J1_J2_consensus"] = {
    "consensus_definition": "J1 and J2 assigned the same acknowledgment_label "
                            "(merge_silence.py); discordant items remain excluded",
    "n_consensus_items": len(cons), "n_also_parsed_by_J3": len(cc),
    "four_way_label": {"percent_agreement": round(po, 4), "cohens_kappa": round(float(kk), 4),
                       "confusion_rows_consensus_cols_J3": {
                           c: dict(zip(LABELS, map(int, M[k]))) for k, c in enumerate(LABELS)}},
    "binary_acknowledgment_A_vs_rest": {"percent_agreement": round(poa, 4),
                                        "cohens_kappa": round(float(ka), 4)},
    "J3_labels_on_the_J1_J2_discordant_items": dict(collections.Counter(
        j3[i]["acknowledgment_label"] for i in sorted(set(j1) & set(j2))
        if i in ok3 and i not in cons and j1[i]["parse_status"] == "ok"
        and j2[i]["parse_status"] == "ok")),
}

# ---- human validation ---------------------------------------------------------------
if A.human_dir:
    hv = {}
    for tag in ("A", "B"):
        p = pathlib.Path(A.human_dir) / f"human_validation_{tag}.csv"
        rows = list(csv.DictReader(p.open(encoding="utf-8-sig"))) if p.exists() else []
        col = next((c for c in (rows[0] if rows else {})
                    if "label" in c.lower() or "acknowledg" in c.lower()), None)
        filled = sum(1 for r in rows if col and str(r.get(col, "")).strip()) if rows else 0
        hv[f"annotator_{tag}"] = {"file": p.name, "exists": p.exists(), "n_rows": len(rows),
                                  "label_column": col, "n_labelled": filled,
                                  "sha256": sha(p) if p.exists() else None}
    hv["comparison_possible"] = all(v["n_labelled"] > 0 for v in hv.values()
                                    if isinstance(v, dict))
    if not hv["comparison_possible"]:
        hv["note"] = ("Not produced. The 120-item human-validation files exist but carry no "
                      "labels, so GPT-OSS vs each annotator and GPT-OSS vs human consensus "
                      "cannot be computed. Both files were read only to count labels and are "
                      "unchanged.")
    R["human_validation"] = hv

# ---- unblinding: condition rates, last ----------------------------------------------
if A.key:
    key = load(A.key)
    R["unblinded_rates"] = {"note": "computed after every agreement statistic above"}
    for scope in ("condition", "scorer_key"):
        d = {}
        for kk_ in sorted({key[i][scope] for i in key}):
            sub = [i for i in ok3 if i in key and key[i][scope] == kk_]
            c = collections.Counter(j3[i]["acknowledgment_label"] for i in sub)
            d[kk_] = {"n": len(sub), "label_counts": dict(c),
                      "acknowledged_A_rate": round(c["A"] / len(sub), 4) if sub else None,
                      "acknowledged_or_denied_rate":
                          round((c["A"] + c["D"]) / len(sub), 4) if sub else None,
                      "context_mentioned_yes_rate": round(
                          sum(1 for i in sub if j3[i]["context_mentioned"] == "yes")
                          / len(sub), 4) if sub else None}
        R["unblinded_rates"][scope] = d

pathlib.Path(A.out).write_text(json.dumps(R, indent=2), encoding="utf-8")
print(json.dumps(R, indent=2))
