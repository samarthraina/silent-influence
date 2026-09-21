"""Completed 120-item human validation vs J1, J2, the frozen J1/J2 consensus, and J3.

Local files only. Nothing is rerun and no judge output is modified; every file here is opened
read-only. Matching is strictly by item_id, and each annotated rationale_text is checked
character for character against the blinded item the judges saw, so a row that drifted would
be caught rather than silently compared.

The kappa routine is copied verbatim from merge_silence.py so these numbers are produced the
same way the archived J1/J2 numbers were.

Two format normalizations are applied and recorded; neither changes a label:
  - annotator B's file carries a stray title row above the header, which is skipped
  - context_mentioned is lowercased (B wrote "NO", the rubric and the judges use "no")

Human four-way disagreements are left unresolved. No adjudicated label is invented, and the
disagreeing items are excluded from any statistic that would require one.
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
ap.add_argument("--human-a", required=True)
ap.add_argument("--human-b", required=True)
ap.add_argument("--items", required=True)
ap.add_argument("--j1", required=True)
ap.add_argument("--j2", required=True)
ap.add_argument("--j3", required=True)
ap.add_argument("--out", required=True)
A = ap.parse_args()


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def load_judge(p):
    return {r["item_id"]: r for r in
            (json.loads(l) for l in pathlib.Path(p).open(encoding="utf-8") if l.strip())}


def load_human(p):
    """-> (rows_by_id, notes). Skips a stray title row if one sits above the header."""
    notes = []
    with pathlib.Path(p).open(encoding="utf-8-sig", newline="") as f:
        raw = list(csv.reader(f))
    hdr = 0
    while hdr < len(raw) and "item_id" not in raw[hdr]:
        notes.append(f"skipped non-header row {hdr}: {raw[hdr]!r}")
        hdr += 1
    cols = raw[hdr]
    out = {}
    for r in raw[hdr + 1:]:
        if not any(c.strip() for c in r):
            continue
        d = dict(zip(cols, r))
        d["acknowledgment_label"] = d["acknowledgment_label"].strip().upper()
        d["context_mentioned"] = d["context_mentioned"].strip().lower()
        out[d["item_id"].strip()] = d
    return out, notes


def kappa(a, b, cats):
    idx = {c: k for k, c in enumerate(cats)}
    n = len(a)
    M = np.zeros((len(cats), len(cats)))
    for x, y in zip(a, b):
        M[idx[x], idx[y]] += 1
    po = np.trace(M) / n
    pe = float((M.sum(0) / n) @ (M.sum(1) / n))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan"), po, M


def mat(M, cats):
    return {c: dict(zip(cats, map(int, M[k]))) for k, c in enumerate(cats)}


ha, na = load_human(A.human_a)
hb, nb = load_human(A.human_b)
items = {json.loads(l)["item_id"]: json.loads(l)["rationale_text"]
         for l in pathlib.Path(A.items).open(encoding="utf-8") if l.strip()}
j1, j2, j3 = load_judge(A.j1), load_judge(A.j2), load_judge(A.j3)

R = {"inputs": {
    "human_A": {"path": str(A.human_a), "sha256": sha(A.human_a), "n_rows": len(ha),
                "format_notes": na},
    "human_B": {"path": str(A.human_b), "sha256": sha(A.human_b), "n_rows": len(hb),
                "format_notes": nb},
    "blinded_items_sha256": sha(A.items),
    "J3_sha256": sha(A.j3),
    "normalizations": ["context_mentioned lowercased", "stray title row skipped where present",
                       "no label value was altered"]}}

# ---- structural checks --------------------------------------------------------------
sa, sb = set(ha), set(hb)
R["matching"] = {
    "n_A": len(ha), "n_B": len(hb),
    "A_ids_unique": len(ha) == len(sa), "B_ids_unique": len(hb) == len(sb),
    "same_id_set": sa == sb,
    "in_A_not_B": sorted(sa - sb), "in_B_not_A": sorted(sb - sa),
    "ids_not_in_blinded_input": sorted((sa | sb) - set(items)),
}

# rationale_text must match the blinded item the judges saw
def norm(s):
    return s.replace("\r\n", "\n").replace("\r", "\n").strip()


mismatch = {}
for tag, h in (("A", ha), ("B", hb)):
    bad = [i for i in sorted(h) if i in items and norm(h[i]["rationale_text"]) != norm(items[i])]
    mismatch[tag] = {"n_checked": sum(1 for i in h if i in items), "n_mismatched": len(bad),
                     "mismatched_ids": bad[:10]}
R["rationale_text_verification"] = mismatch
R["rationale_text_verification"]["note"] = (
    "compared after normalizing line endings and stripping outer whitespace only")

both = sorted(sa & sb)
R["label_distribution"] = {
    "human_A": dict(collections.Counter(ha[i]["acknowledgment_label"] for i in both)),
    "human_B": dict(collections.Counter(hb[i]["acknowledgment_label"] for i in both)),
    "human_A_context": dict(collections.Counter(ha[i]["context_mentioned"] for i in both)),
    "human_B_context": dict(collections.Counter(hb[i]["context_mentioned"] for i in both)),
}

# ---- human inter-annotator agreement ------------------------------------------------
al = [ha[i]["acknowledgment_label"] for i in both]
bl = [hb[i]["acknowledgment_label"] for i in both]
ac = [ha[i]["context_mentioned"] for i in both]
bc = [hb[i]["context_mentioned"] for i in both]
kl, pol, Ml = kappa(al, bl, LABELS)
kc, poc, Mc = kappa(ac, bc, ("yes", "no"))
lab_dis = [i for i in both
           if ha[i]["acknowledgment_label"] != hb[i]["acknowledgment_label"]]
ctx_dis = [i for i in both if ha[i]["context_mentioned"] != hb[i]["context_mentioned"]]
R["human_inter_annotator"] = {
    "n_items": len(both),
    "four_way_label": {"percent_agreement": round(pol, 4), "cohens_kappa": round(float(kl), 4),
                       "n_disagreements": len(lab_dis),
                       "confusion_rows_A_cols_B": mat(Ml, LABELS)},
    "binary_context_mentioned": {"percent_agreement": round(poc, 4),
                                 "cohens_kappa": round(float(kc), 4),
                                 "n_disagreements": len(ctx_dis),
                                 "confusion_rows_A_cols_B": mat(Mc, ("yes", "no"))},
    "label_disagreement_items": [
        {"item_id": i, "A": ha[i]["acknowledgment_label"], "B": hb[i]["acknowledgment_label"],
         "A_context": ha[i]["context_mentioned"], "B_context": hb[i]["context_mentioned"],
         "A_evidence": ha[i].get("evidence_span", ""), "B_evidence": hb[i].get("evidence_span", ""),
         "status": "UNRESOLVED, no adjudicated label assigned"} for i in lab_dis],
    "context_disagreement_items": [
        {"item_id": i, "A": ha[i]["context_mentioned"], "B": hb[i]["context_mentioned"]}
        for i in ctx_dis],
}

# ---- human consensus, unadjudicated -------------------------------------------------
hc = {i: ha[i]["acknowledgment_label"] for i in both
      if ha[i]["acknowledgment_label"] == hb[i]["acknowledgment_label"]}
hcc = {i: ha[i]["context_mentioned"] for i in both
       if ha[i]["context_mentioned"] == hb[i]["context_mentioned"]}
R["human_consensus"] = {
    "definition": "both annotators assigned the same value; disagreements are excluded and "
                  "left unresolved rather than adjudicated",
    "n_label_consensus": len(hc), "n_label_excluded": len(both) - len(hc),
    "n_context_consensus": len(hcc), "n_context_excluded": len(both) - len(hcc),
    "label_counts": dict(collections.Counter(hc.values())),
}

# ---- each automated judge vs the humans ---------------------------------------------
JUDGES = {"J1_qwen3_8b": j1, "J2_gemma_2_9b_it": j2, "J3_gptoss_20b": j3}


def vs(judge, ref_lab, ref_ctx, ref_name):
    ids = [i for i in sorted(ref_lab)
           if i in judge and judge[i]["parse_status"] == "ok"]
    jl = [judge[i]["acknowledgment_label"] for i in ids]
    rl = [ref_lab[i] for i in ids]
    kl_, po_, M_ = kappa(rl, jl, LABELS)
    ra = ["A" if v == "A" else "not_A" for v in rl]
    ja = ["A" if v == "A" else "not_A" for v in jl]
    ka_, poa_, Ma_ = kappa(ra, ja, ("A", "not_A"))
    rr = ["ref" if v in ("A", "D") else "no_ref" for v in rl]
    jr = ["ref" if v in ("A", "D") else "no_ref" for v in jl]
    kr_, por_, _ = kappa(rr, jr, ("ref", "no_ref"))
    cids = [i for i in sorted(ref_ctx) if i in judge and judge[i]["parse_status"] == "ok"]
    kc_, poc_, Mc_ = kappa([ref_ctx[i] for i in cids],
                           [judge[i]["context_mentioned"] for i in cids], ("yes", "no"))
    return {"reference": ref_name, "n_compared_label": len(ids),
            "n_unparsed_by_judge": len(ref_lab) - len(ids),
            "four_way_label": {"percent_agreement": round(po_, 4),
                               "cohens_kappa": round(float(kl_), 4),
                               "confusion_rows_human_cols_judge": mat(M_, LABELS)},
            "binary_acknowledgment_A_vs_rest": {"percent_agreement": round(poa_, 4),
                                                "cohens_kappa": round(float(ka_), 4),
                                                "confusion_rows_human_cols_judge":
                                                    mat(Ma_, ("A", "not_A"))},
            "binary_reference_present_A_or_D": {"percent_agreement": round(por_, 4),
                                                "cohens_kappa": round(float(kr_), 4)},
            "binary_context_mentioned": {"n_compared": len(cids),
                                         "percent_agreement": round(poc_, 4),
                                         "cohens_kappa": round(float(kc_), 4),
                                         "confusion_rows_human_cols_judge":
                                             mat(Mc_, ("yes", "no"))}}


R["judges_vs_humans"] = {}
for jn, jd in JUDGES.items():
    R["judges_vs_humans"][jn] = {
        "vs_annotator_A": vs(jd, {i: ha[i]["acknowledgment_label"] for i in both},
                             {i: ha[i]["context_mentioned"] for i in both}, "human annotator A"),
        "vs_annotator_B": vs(jd, {i: hb[i]["acknowledgment_label"] for i in both},
                             {i: hb[i]["context_mentioned"] for i in both}, "human annotator B"),
        "vs_human_consensus": vs(jd, hc, hcc,
                                 "human consensus (unanimous A/B only, disagreements excluded)"),
    }

# ---- frozen J1/J2 consensus vs the humans -------------------------------------------
mc = {i: j1[i]["acknowledgment_label"] for i in set(j1) & set(j2)
      if j1[i]["parse_status"] == "ok" and j2[i]["parse_status"] == "ok"
      and j1[i]["acknowledgment_label"] == j2[i]["acknowledgment_label"]}
mcc = {i: j1[i]["context_mentioned"] for i in set(j1) & set(j2)
       if j1[i]["parse_status"] == "ok" and j2[i]["parse_status"] == "ok"
       and j1[i]["context_mentioned"] == j2[i]["context_mentioned"]}
pseudo = {i: {"acknowledgment_label": v, "context_mentioned": mcc.get(i, "no"),
              "parse_status": "ok"} for i, v in mc.items() if i in mcc}
R["frozen_J1_J2_consensus_vs_humans"] = {
    "consensus_definition": "J1 and J2 assigned the same label (merge_silence.py); the 36 "
                            "discordant items remain excluded and unadjudicated",
    "n_machine_consensus_items_overall": len(mc),
    "vs_annotator_A": vs(pseudo, {i: ha[i]["acknowledgment_label"] for i in both},
                         {i: ha[i]["context_mentioned"] for i in both}, "human annotator A"),
    "vs_annotator_B": vs(pseudo, {i: hb[i]["acknowledgment_label"] for i in both},
                         {i: hb[i]["context_mentioned"] for i in both}, "human annotator B"),
    "vs_human_consensus": vs(pseudo, hc, hcc, "human consensus"),
}

# ---- item-level disagreement listing, humans vs each judge --------------------------
rows = []
for i in both:
    r = {"item_id": i, "human_A": ha[i]["acknowledgment_label"],
         "human_B": hb[i]["acknowledgment_label"],
         "human_consensus": hc.get(i, "UNRESOLVED")}
    for jn, jd in JUDGES.items():
        r[jn] = jd[i]["acknowledgment_label"] if i in jd and jd[i]["parse_status"] == "ok" \
            else "UNPARSED"
    rows.append(r)
R["items_where_any_judge_differs_from_human_consensus"] = [
    r for r in rows if r["human_consensus"] != "UNRESOLVED"
    and any(r[j] not in (r["human_consensus"], "UNPARSED") for j in JUDGES)]

pathlib.Path(A.out).write_text(json.dumps(R, indent=2), encoding="utf-8")
out_csv = pathlib.Path(A.out).with_suffix(".items.csv")
with out_csv.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(json.dumps(R, indent=2))
