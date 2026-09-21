"""Integrity + effects for the cross-model patching replication. Read-only.

Normalized movement is signed toward the SOURCE endpoint, using WITHIN-HOST baselines:
    norm = (patched - target_baseline) / (source_baseline - target_baseline)
Tasks whose two within-host baselines coincide have no denominator; they are counted and
excluded from the normalized statistic only, never from the raw one and never from the run.

CIs: task-clustered, dataset-stratified bootstrap, 10,000 reps, seed 20260818. The paired
selected-minus-L2 comparison resamples the same task clusters for both arms.
"""
import collections
import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out/crossmodel"
SEED, N_BOOT = 20260818, 10_000
MODELS = ["gemma", "qwen"]
ARMS_PER_TASK = 10
DIRS = {"lo2hi": "self_low_2->no_history", "hi2lo": "no_history->self_low_2"}


def strat_boot(by_task_ds, stat):
    """by_task_ds: {dataset: {task: [values]}}; resample tasks within each dataset."""
    rng = np.random.default_rng(SEED)
    strata = {d: sorted(t) for d, t in by_task_ds.items()}
    reps = []
    for _ in range(N_BOOT):
        pool = []
        for d, keys in strata.items():
            if not keys:
                continue
            idx = rng.integers(0, len(keys), size=len(keys))
            for i in idx:
                pool.extend(by_task_ds[d][keys[i]])
        reps.append(stat(pool) if pool else np.nan)
    r = np.asarray(reps, float); r = r[~np.isnan(r)]
    if r.size == 0:
        return (float("nan"), float("nan"))
    return float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


report = {"stage": "CROSS-MODEL PATCHING REPLICATION",
          "instrument_note": ("layer selection used a LOGIT lens (each model's own "
                              "unembedding); Llama's L24 used a JACOBIAN lens. Layer numbers "
                              "are NOT comparable across architectures. Replication claims "
                              "rest on the held-out causal patching results only."),
          "success_criteria_predeclared": [
              "normalized selected-layer movement 95% CI excludes zero",
              "selected-layer minus L2 paired difference 95% CI excludes zero"],
          "bootstrap": {"n": N_BOOT, "seed": SEED,
                        "design": "task-clustered, dataset-stratified"},
          "baselines": "within-host; archived-score reproduction reported, never used to exclude",
          "models": {}}

integrity = {"expected_total": 1440, "per_model_expected": 720}
all_rows = {}
for m in MODELS:
    rows = [json.loads(l) for l in (OUT / f"validation_{m}.jsonl").open(encoding="utf-8")
            if l.strip()]
    all_rows[m] = rows

# ---- integrity -----------------------------------------------------------------------
tot = sum(len(r) for r in all_rows.values())
integrity["records_total"] = tot
integrity["per_model"] = {}
for m, rows in all_rows.items():
    sel = json.loads((OUT / f"SELECTED_LAYER_{m}.json").read_text(encoding="utf-8"))
    L, L2 = sel["selected_layer"], 2
    tasks = {(r["dataset"], r["task_id"]) for r in rows}
    expected_arms = {f"baseline_self_low_2", "baseline_no_history",
                     f"patch_L{L}_lo2hi", f"patch_L{L}_hi2lo",
                     f"patch_L{L2}_lo2hi", f"patch_L{L2}_hi2lo",
                     "noop_self_low_2", "noop_no_history",
                     "same_self_low_2", "same_no_history"}
    exp_units = {f"{a}|{d}/{t}" if not a.startswith("baseline")
                 else f"baseline|{d}/{t}|{a.split('baseline_')[1]}"
                 for a in expected_arms for d, t in tasks}
    got = [r["unit"] for r in rows]
    dupes = {u: c for u, c in collections.Counter(got).items() if c > 1}
    integrity["per_model"][m] = {
        "records": len(rows), "unique_units": len(set(got)),
        "expected_units": len(exp_units),
        "n_tasks": len(tasks), "n_arms": len({r["arm"] for r in rows}),
        "arms_expected": ARMS_PER_TASK,
        "missing": sorted(exp_units - set(got))[:10],
        "n_missing": len(exp_units - set(got)),
        "n_duplicate": len(dupes),
        "n_unexpected": len(set(got) - exp_units),
        "parse_failed": sum(1 for r in rows if r["parse_status"] != "ok"),
        "a5_invalid": sum(1 for r in rows if not r["a5_valid"]),
        "technical_failures": sum(1 for r in rows if r["score"] is None
                                  and r["parse_status"] == "ok"),
    }
report["integrity"] = integrity

# ---- effects -------------------------------------------------------------------------
for m, rows in all_rows.items():
    sel = json.loads((OUT / f"SELECTED_LAYER_{m}.json").read_text(encoding="utf-8"))
    L = sel["selected_layer"]
    by_unit = {r["unit"]: r for r in rows}
    ent = {"selected_layer": L, "n_layers": sel["n_layers"],
           "eligible_layers": sel["eligible_layers"],
           "selection_metric": sel["selection_metric"],
           "layer_frozen_before_validation": sel["selected_before_any_validation_run"],
           "directions": {}}

    # identity controls
    for kind in ("noop", "same"):
        arms = [r for r in rows if r["arm"].startswith(kind + "_")]
        ident = sum(1 for r in arms if r["score"] == r["target_baseline"])
        ent[f"{kind}_identity"] = {"n": len(arms), "identical": ident,
                                   "rate": round(ident / len(arms), 4) if arms else None}
    # archived-score reproduction (reported, never used to exclude)
    base = [r for r in rows if r["arm"].startswith("baseline_")]
    repro = sum(1 for r in base if r.get("archived_behavioural_score") is not None
                and r["score"] == r["archived_behavioural_score"])
    ent["within_host_baseline_reproduces_archived"] = {
        "n": len(base), "matched": repro,
        "rate": round(repro / len(base), 4) if base else None,
        "used_to_exclude_tasks": False}

    for dkey, dname in DIRS.items():
        arm_sel, arm_l2 = f"patch_L{L}_{dkey}", f"patch_L2_{dkey}"
        raw_ds, norm_ds, pair_ds = (collections.defaultdict(dict),
                                    collections.defaultdict(dict),
                                    collections.defaultdict(dict))
        toward = away = unchanged = 0
        n_zero_denom = 0
        raw_all, norm_all = [], []
        for r in rows:
            if r["arm"] != arm_sel or r["score"] is None:
                continue
            d, t = r["dataset"], r["task_id"]
            tb, sb = r["target_baseline"], r["source_baseline"]
            if tb is None or sb is None:
                continue
            mv = r["score"] - tb
            raw_all.append(mv); raw_ds[d].setdefault(t, []).append(mv)
            sgn = np.sign(sb - tb)
            if mv == 0:
                unchanged += 1
            elif sgn != 0 and np.sign(mv) == sgn:
                toward += 1
            else:
                away += 1
            if sb == tb:
                n_zero_denom += 1
            else:
                nm = mv / (sb - tb)
                norm_all.append(nm); norm_ds[d].setdefault(t, []).append(nm)
            o = by_unit.get(f"{arm_l2}|{d}/{t}")
            if o and o["score"] is not None and sb != tb:
                pair_ds[d].setdefault(t, []).append(nm - (o["score"] - tb) / (sb - tb))
        n_tot = toward + away + unchanged
        rlo, rhi = strat_boot(raw_ds, np.mean)
        nlo, nhi = strat_boot(norm_ds, np.mean)
        plo, phi = strat_boot(pair_ds, np.mean)
        pair_vals = [v for ts in pair_ds.values() for vs in ts.values() for v in vs]
        c1 = not (nlo <= 0 <= nhi)
        c2 = not (plo <= 0 <= phi)
        ent["directions"][dname] = {
            "arm": arm_sel, "n_calls": n_tot,
            "raw_movement_mean": round(float(np.mean(raw_all)), 4) if raw_all else None,
            "raw_ci": [round(rlo, 4), round(rhi, 4)],
            "normalized_mean": round(float(np.mean(norm_all)), 4) if norm_all else None,
            "normalized_ci": [round(nlo, 4), round(nhi, 4)],
            "n_zero_denominator_excluded_from_normalized": n_zero_denom,
            "toward_fraction": round(toward / n_tot, 4) if n_tot else None,
            "away_fraction": round(away / n_tot, 4) if n_tot else None,
            "unchanged_fraction": round(unchanged / n_tot, 4) if n_tot else None,
            "paired_selected_minus_L2": {
                "n_paired_tasks": len(pair_vals),
                "mean_difference_normalized": round(float(np.mean(pair_vals)), 4)
                if pair_vals else None,
                "ci": [round(plo, 4), round(phi, 4)]},
            "criterion_1_normalized_ci_excludes_zero": bool(c1),
            "criterion_2_paired_vs_L2_ci_excludes_zero": bool(c2),
            "BOTH_CRITERIA_PASSED": bool(c1 and c2),
        }
    report["models"][m] = ent

(OUT / "crossmodel_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

i = report["integrity"]
print(f"  records {i['records_total']}/1440")
for m in MODELS:
    p = i["per_model"][m]
    print(f"    {m:<6} {p['records']}/720 unique {p['unique_units']}/{p['expected_units']} "
          f"tasks {p['n_tasks']} arms {p['n_arms']}/{p['arms_expected']} | missing "
          f"{p['n_missing']} dup {p['n_duplicate']} unexpected {p['n_unexpected']} | "
          f"parse_fail {p['parse_failed']} a5_invalid {p['a5_invalid']} tech {p['technical_failures']}")
for m in MODELS:
    e = report["models"][m]
    print(f"\n  === {m}  frozen L{e['selected_layer']} of {e['n_layers']} "
          f"(eligible {e['eligible_layers']}) ===")
    print(f"    noop identity {e['noop_identity']['identical']}/{e['noop_identity']['n']} "
          f"| same-cond {e['same_identity']['identical']}/{e['same_identity']['n']} "
          f"| baseline reproduces archived {e['within_host_baseline_reproduces_archived']['rate']:.1%}")
    for dn, d in e["directions"].items():
        print(f"    {dn}")
        print(f"      raw {d['raw_movement_mean']:+.4f} {d['raw_ci']}  "
              f"norm {d['normalized_mean']:+.4f} {d['normalized_ci']}  n={d['n_calls']}")
        print(f"      toward {d['toward_fraction']:.1%} away {d['away_fraction']:.1%} "
              f"unchanged {d['unchanged_fraction']:.1%}  zero-denom {d['n_zero_denominator_excluded_from_normalized']}")
        pp = d["paired_selected_minus_L2"]
        print(f"      selected-L2 paired {pp['mean_difference_normalized']:+.4f} {pp['ci']} "
              f"(n={pp['n_paired_tasks']})")
        print(f"      C1 {d['criterion_1_normalized_ci_excludes_zero']}  "
              f"C2 {d['criterion_2_paired_vs_L2_ci_excludes_zero']}  "
              f"BOTH {d['BOTH_CRITERIA_PASSED']}")
print(f"\n  [save] {OUT/'crossmodel_report.json'}")
