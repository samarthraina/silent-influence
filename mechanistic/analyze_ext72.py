"""Primary + secondary analysis of the 72-task generalization replication.

Primary: all 72 tasks, equally weighted across datasets (mean of the three dataset means, so
each dataset contributes 1/3 regardless of how many of its tasks parsed).

Normalized movement is signed toward the SOURCE endpoint:
    norm = (patched - target_baseline) / (source_baseline - target_baseline)
0 = target unmoved, 1 = fully at the source endpoint. Tasks whose endpoints coincide have no
denominator and are excluded from the normalized statistic only, counted separately.

Paired comparisons (learned vs random, learned vs L2) are computed per task on the same task
set and bootstrapped as a paired difference.

Secondary delta strata are analytical only: computed here, after the manifest was frozen and
hashed, and they played no part in selection.
"""
import collections
import json
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT / "Code/GitHub/silent-influence"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
import analyze_final_study as A

REC = HERE / "out/ext72/ext72_records.jsonl"
MAN = json.loads((HERE / "manifest/mech_ext72_manifest.json").read_text(encoding="utf-8"))
OUT = HERE / "out/ext72"
N_BOOT, SEED = 10_000, 20260818
DATASETS = ["mtbench", "arena_hard", "wildbench"]

rows = [json.loads(l) for l in REC.open(encoding="utf-8") if l.strip()]
by_arm = collections.defaultdict(list)
for r in rows:
    by_arm[r["arm"]].append(r)

# behavioural delta per task, for the analytical strata only
pivot = A.pivot_scores(A.load_records(ROOT / "final_analysis_workspace/merged_raw_results.jsonl"))
delta = {}
for t in MAN["tasks"]:
    c = pivot[("llama", t["dataset"], t["task_id"])]
    delta[(t["dataset"], t["task_id"])] = float(c["no_history"]) - float(c["self_low_2"])


def stratum(d):
    return "high_delta_ge2" if d >= 2 else ("moderate_0_to_2" if d > 0 else "nonresponsive_le0")


def equal_dataset_mean(vals_by_task):
    """Mean of dataset means -> each dataset weighted 1/3."""
    per = collections.defaultdict(list)
    for (ds, tid), v in vals_by_task.items():
        per[ds].append(v)
    means = [np.mean(per[d]) for d in DATASETS if per[d]]
    return float(np.mean(means)) if means else None


def boot_equal_dataset(vals_by_task, seed=SEED):
    per = collections.defaultdict(list)
    for (ds, tid), v in vals_by_task.items():
        per[ds].append(v)
    keys = {d: np.asarray(per[d], float) for d in DATASETS if per[d]}
    if not keys:
        return (None, None)
    rng = np.random.default_rng(seed)
    reps = []
    for _ in range(N_BOOT):
        ms = [keys[d][rng.integers(0, len(keys[d]), size=len(keys[d]))].mean() for d in keys]
        reps.append(np.mean(ms))
    return (float(np.percentile(reps, 2.5)), float(np.percentile(reps, 97.5)))


def movement(recs, toward_key):
    """-> raw{}, norm{}, dirn{} keyed by task; toward_key names the source-endpoint field."""
    raw, norm, dirn, no_denom = {}, {}, {}, 0
    for r in recs:
        if r["score"] is None or r["target_baseline"] is None:
            continue
        k = (r["dataset"], r["task_id"])
        tb, sb = r["target_baseline"], r.get(toward_key)
        if sb is None:
            continue
        mv = r["score"] - tb
        raw[k] = mv
        s = np.sign(sb - tb)
        dirn[k] = 1.0 if (s != 0 and np.sign(mv) == s) else (0.0 if mv == 0 else -1.0)
        if sb != tb:
            norm[k] = mv / (sb - tb)
        else:
            no_denom += 1
    return raw, norm, dirn, no_denom


def summarize(recs, toward_key, label):
    raw, norm, dirn, nd = movement(recs, toward_key)
    if not raw:
        return None
    lo, hi = boot_equal_dataset(raw)
    nlo, nhi = boot_equal_dataset(norm) if norm else (None, None)
    d = np.asarray(list(dirn.values()))
    return {
        "label": label, "n_tasks": len(raw),
        "raw_equal_dataset_mean": equal_dataset_mean(raw), "raw_ci": [lo, hi],
        "normalized_equal_dataset_mean": equal_dataset_mean(norm) if norm else None,
        "normalized_ci": [nlo, nhi], "n_excluded_no_denominator": nd,
        "frac_toward": float((d > 0).mean()), "frac_away": float((d < 0).mean()),
        "frac_unchanged": float((d == 0).mean()),
        "_norm_by_task": {f"{k[0]}/{k[1]}": v for k, v in norm.items()},
    }


report = {
    "stage": "72-TASK GENERALIZATION REPLICATION",
    "provenance": MAN["PROVENANCE"],
    "manifest_sha256_frozen_before_run": True,
    "reused_without_retuning": MAN["reused_without_retuning"],
    "primary_weighting": "all 72 tasks, equal weight per dataset (mean of 3 dataset means)",
    "normalization": "(patched - target_baseline) / (source_baseline - target_baseline)",
    "bootstrap": {"unit": "task, stratified by dataset", "n": N_BOOT, "seed": SEED},
}

n = len(rows)
report["validity"] = {
    "n_calls": n,
    "parse_ok": sum(1 for r in rows if r["parse_status"] == "ok"),
    "parse_ok_rate": round(sum(1 for r in rows if r["parse_status"] == "ok") / n, 4),
    "a5_valid": sum(1 for r in rows if r["a5_valid"]),
    "a5_valid_rate": round(sum(1 for r in rows if r["a5_valid"]) / n, 4),
    "noop_identity": f"{sum(1 for r in by_arm['noop_self_low_2']+by_arm['noop_no_history'] if r['score']==r['target_baseline'])}/{len(by_arm['noop_self_low_2'])+len(by_arm['noop_no_history'])}",
    "same_condition_identity": f"{sum(1 for r in by_arm['same_self_low_2']+by_arm['same_no_history'] if r['score']==r['target_baseline'])}/{len(by_arm['same_self_low_2'])+len(by_arm['same_no_history'])}",
}

# ---- steering / ablation: self_low_2 driven toward the no_history endpoint -------------
arms = {}
for arm in ("steer", "ablate", "steer_early_L2", "steer_random"):
    arms[arm] = summarize(by_arm[arm], "no_history_endpoint", arm)
# specificity: same learned intervention applied where it should do less
arms["steer_on_no_history"] = summarize(by_arm["steer_on_no_history"], "self_low_2_endpoint",
                                       "steer_on_no_history")
arms["steer_on_unrelated"] = summarize(by_arm["steer_on_unrelated"], "no_history_endpoint",
                                       "steer_on_unrelated")
# ---- locked bidirectional patching ----------------------------------------------------
for arm in ("patch_L24_lo2hi", "patch_L24_hi2lo", "patch_L2_lo2hi", "patch_L2_hi2lo"):
    arms[arm] = summarize(by_arm[arm], "source_baseline", arm)
report["arms"] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
                  for k, v in arms.items() if v}

# ---- paired comparisons ---------------------------------------------------------------
def paired(a, b, name):
    A_, B_ = arms.get(a), arms.get(b)
    if not A_ or not B_:
        return None
    ka = A_["_norm_by_task"]; kb = B_["_norm_by_task"]
    common = sorted(set(ka) & set(kb))
    if not common:
        return None
    diff = {tuple(k.split("/", 1)): ka[k] - kb[k] for k in common}
    lo, hi = boot_equal_dataset(diff)
    d = np.asarray([ka[k] - kb[k] for k in common])
    return {"comparison": name, "n_paired_tasks": len(common),
            "mean_difference_normalized": equal_dataset_mean(diff), "ci": [lo, hi],
            "frac_learned_greater": float((d > 0).mean()),
            "exceeds_control": bool(lo is not None and lo > 0)}


report["paired_comparisons"] = {
    "learned_vs_random": paired("steer", "steer_random", "steer - steer_random"),
    "learned_vs_early_L2": paired("steer", "steer_early_L2", "steer - steer_early_L2"),
    "patch_L24_vs_L2_lo2hi": paired("patch_L24_lo2hi", "patch_L2_lo2hi",
                                    "patch L24 - L2 (self_low_2->no_history)"),
    "patch_L24_vs_L2_hi2lo": paired("patch_L24_hi2lo", "patch_L2_hi2lo",
                                    "patch L24 - L2 (no_history->self_low_2)"),
}

# ---- specificity side by side ---------------------------------------------------------
report["specificity"] = {
    "note": "same learned direction, same beta, applied to three conditions. If the shift "
            "under no_history and unrelated_low_2 matches the self_low_2 shift, the "
            "intervention is a nonspecific score-shifter.",
    "raw_shift_from_own_baseline": {
        c: {"equal_dataset_mean": summarize(by_arm[a], "no_history_endpoint", a)["raw_equal_dataset_mean"]
            if summarize(by_arm[a], "no_history_endpoint", a) else None}
        for c, a in (("self_low_2", "steer"), ("no_history", "steer_on_no_history"),
                     ("unrelated_low_2", "steer_on_unrelated"))
    },
}

# ---- SECONDARY: analytical strata (post-freeze, selection-independent) -----------------
sec = {"declared_analytical_only": True, "used_in_selection": False, "strata": {}}
counts = collections.Counter(stratum(d) for d in delta.values())
sec["task_counts"] = dict(sorted(counts.items()))
for st in ("high_delta_ge2", "moderate_0_to_2", "nonresponsive_le0"):
    keep = {k for k, d in delta.items() if stratum(d) == st}
    sec["strata"][st] = {}
    for arm in ("steer", "ablate", "patch_L24_lo2hi", "patch_L24_hi2lo"):
        sub = [r for r in by_arm[arm] if (r["dataset"], r["task_id"]) in keep]
        tk = "source_baseline" if arm.startswith("patch") else "no_history_endpoint"
        s = summarize(sub, tk, f"{st}/{arm}")
        if s:
            sec["strata"][st][arm] = {kk: vv for kk, vv in s.items()
                                      if not kk.startswith("_")}
report["secondary_analytical_strata"] = sec

(OUT / "ext72_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

v = report["validity"]
print(f"  calls {v['n_calls']}  parse {v['parse_ok_rate']:.2%}  A5 {v['a5_valid_rate']:.2%}  "
      f"noop {v['noop_identity']}  same {v['same_condition_identity']}")
print(f"\n  {'arm':<22} {'n':>3} {'raw':>7} {'raw CI':>17} {'norm':>7} {'norm CI':>17} "
      f"{'tow':>5} {'away':>5} {'unch':>5}")
for k, s in report["arms"].items():
    nm = f"{s['normalized_equal_dataset_mean']:+.3f}" if s["normalized_equal_dataset_mean"] is not None else "   -  "
    nc = (f"[{s['normalized_ci'][0]:+.3f},{s['normalized_ci'][1]:+.3f}]"
          if s["normalized_ci"][0] is not None else "        -        ")
    print(f"  {k:<22} {s['n_tasks']:>3} {s['raw_equal_dataset_mean']:>+7.3f} "
          f"[{s['raw_ci'][0]:+.3f},{s['raw_ci'][1]:+.3f}] {nm:>7} {nc:>17} "
          f"{s['frac_toward']:>5.0%} {s['frac_away']:>5.0%} {s['frac_unchanged']:>5.0%}")
print("\n  paired:")
for k, p in report["paired_comparisons"].items():
    if p:
        print(f"    {k:<24} diff {p['mean_difference_normalized']:+.3f} "
              f"[{p['ci'][0]:+.3f},{p['ci'][1]:+.3f}]  learned>ctrl {p['frac_learned_greater']:.0%}  "
              f"exceeds={p['exceeds_control']}")
print(f"\n  strata counts: {sec['task_counts']}")
print(f"  [save] {OUT/'ext72_report.json'}")
