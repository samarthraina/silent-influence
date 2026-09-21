"""Stage-2 metrics. Held-out validation only; the layer window was fixed by stage 1.

Normalized movement is signed toward the SOURCE endpoint:
    norm = (patched - target_baseline) / (source_baseline - target_baseline)
so 0 = target unmoved, 1 = fully at the source endpoint. Tasks whose two baselines coincide
have no denominator and are excluded from the normalized statistic only (counted separately),
never from the raw one.

CIs are a task bootstrap: the resampling unit is the task, 10,000 replicates, seed 20260818.
"""
import collections
import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
V = HERE / "out/validation/validation_records.jsonl"
OUT = HERE / "out"
SEED, N_BOOT = 20260818, 10_000

rows = [json.loads(l) for l in V.open(encoding="utf-8") if l.strip()]
win = json.loads((HERE / "out/discovery/SELECTED_WINDOW.json").read_text(encoding="utf-8"))
WINDOW = win["window"]


def boot_mean(vals_by_task, rng):
    keys = sorted(vals_by_task)
    reps = []
    for _ in range(N_BOOT):
        idx = rng.integers(0, len(keys), size=len(keys))
        pool = [v for i in idx for v in vals_by_task[keys[i]]]
        reps.append(np.mean(pool) if pool else np.nan)
    reps = np.asarray(reps, float)
    reps = reps[~np.isnan(reps)]
    return float(np.percentile(reps, 2.5)), float(np.percentile(reps, 97.5))


def summarize(sub, label):
    rng = np.random.default_rng(SEED)
    raw_by_task, norm_by_task, raw, norm, pos = {}, {}, [], [], []
    n_no_denom = 0
    for r in sub:
        if r["score"] is None:
            continue
        tb, sb = r["target_baseline"], r["source_baseline"]
        if tb is None or sb is None:
            continue
        k = f"{r['dataset']}/{r['task_id']}"
        mv = r["score"] - tb
        raw.append(mv); raw_by_task.setdefault(k, []).append(mv)
        # positive direction = movement toward the source endpoint
        sgn = np.sign(sb - tb)
        pos.append(1.0 if (sgn != 0 and np.sign(mv) == sgn) else 0.0)
        if sb != tb:
            nm = mv / (sb - tb)
            norm.append(nm); norm_by_task.setdefault(k, []).append(nm)
        else:
            n_no_denom += 1
    if not raw:
        return None
    pos_by_task = {}
    for r, p in zip([x for x in sub if x["score"] is not None
                     and x["target_baseline"] is not None
                     and x["source_baseline"] is not None], pos):
        pos_by_task.setdefault(f"{r['dataset']}/{r['task_id']}", []).append(p)
    rl, rh = boot_mean(raw_by_task, np.random.default_rng(SEED))
    nl, nh = boot_mean(norm_by_task, np.random.default_rng(SEED)) if norm_by_task else (None, None)
    pl, ph = boot_mean(pos_by_task, np.random.default_rng(SEED))
    return {
        "label": label, "n_calls": len(raw), "n_tasks": len(raw_by_task),
        "raw_movement_mean": float(np.mean(raw)), "raw_ci": [rl, rh],
        "raw_median": float(np.median(raw)),
        "normalized_mean": float(np.mean(norm)) if norm else None,
        "normalized_ci": [nl, nh], "n_excluded_no_denominator": n_no_denom,
        "positive_direction_fraction": float(np.mean(pos)), "positive_ci": [pl, ph],
    }


report = {"stage": "HELD-OUT VALIDATION", "window": WINDOW,
          "selected_layer": win["selected_layer"],
          "layer_selected_before_validation": True,
          "normalization": "(patched - target_baseline) / (source_baseline - target_baseline)",
          "bootstrap": {"unit": "task", "n": N_BOOT, "seed": SEED}}

# ---- integrity: parse / A5 / no-op identity ------------------------------------------
n = len(rows)
report["integrity"] = {
    "n_calls": n,
    "parse_ok": sum(1 for r in rows if r["parse_status"] == "ok"),
    "parse_ok_rate": round(sum(1 for r in rows if r["parse_status"] == "ok") / n, 4),
    "a5_valid": sum(1 for r in rows if r["a5_valid"]),
    "a5_valid_rate": round(sum(1 for r in rows if r["a5_valid"]) / n, 4),
}
noop = [r for r in rows if r["kind"] == "noop"]
same = [r for r in rows if r["kind"] == "same_condition"]
report["integrity"]["noop_identity"] = {
    "n": len(noop),
    "n_identical_to_baseline": sum(1 for r in noop if r["score"] == r["target_baseline"]),
    "rate": round(sum(1 for r in noop if r["score"] == r["target_baseline"]) / len(noop), 4),
}
report["integrity"]["same_condition_identity"] = {
    "n": len(same),
    "n_identical_to_baseline": sum(1 for r in same if r["score"] == r["target_baseline"]),
    "rate": round(sum(1 for r in same if r["score"] == r["target_baseline"]) / len(same), 4),
}

# baselines reproduce the frozen behavioural scores?
base = [r for r in rows if r["kind"] == "baseline"]
report["integrity"]["baseline_matches_frozen_behavioural"] = {
    "n": len(base),
    "n_match": sum(1 for r in base if r["score"] == r["frozen_behavioural_score"]),
}

# ---- transfer, per direction per layer -----------------------------------------------
per = []
for kind in ("transfer", "early_control"):
    for L in sorted({r["layer"] for r in rows if r["kind"] == kind}):
        for d in ("self_low_2->no_history", "no_history->self_low_2"):
            sub = [r for r in rows if r["kind"] == kind and r["layer"] == L
                   and r.get("direction") == d]
            s = summarize(sub, f"{kind} L{L} {d}")
            if s:
                s.update(kind=kind, layer=L, direction=d)
                per.append(s)
report["by_layer_direction"] = per

# window-pooled per direction
for d in ("self_low_2->no_history", "no_history->self_low_2"):
    sub = [r for r in rows if r["kind"] == "transfer" and r["layer"] in WINDOW
           and r.get("direction") == d]
    report.setdefault("window_pooled", {})[d] = summarize(sub, f"window {WINDOW} {d}")

# ---- by dataset, descriptive ----------------------------------------------------------
byds = {}
for ds in sorted({r["dataset"] for r in rows}):
    for d in ("self_low_2->no_history", "no_history->self_low_2"):
        sub = [r for r in rows if r["kind"] == "transfer" and r["layer"] in WINDOW
               and r.get("direction") == d and r["dataset"] == ds]
        byds.setdefault(ds, {})[d] = summarize(sub, f"{ds} {d}")
report["by_dataset_DESCRIPTIVE"] = byds

(OUT / "validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

i = report["integrity"]
print(f"  calls {i['n_calls']}   parse ok {i['parse_ok']}/{i['n_calls']} ({i['parse_ok_rate']:.1%})"
      f"   A5 valid {i['a5_valid']}/{i['n_calls']} ({i['a5_valid_rate']:.1%})")
print(f"  no-op identity        {i['noop_identity']['n_identical_to_baseline']}/{i['noop_identity']['n']} ({i['noop_identity']['rate']:.1%})")
print(f"  same-condition identity {i['same_condition_identity']['n_identical_to_baseline']}/{i['same_condition_identity']['n']} ({i['same_condition_identity']['rate']:.1%})")
b = i["baseline_matches_frozen_behavioural"]
print(f"  baseline == frozen behavioural score  {b['n_match']}/{b['n']}")
print()
print(f"  {'cond':<34} {'n':>4} {'raw':>7} {'raw 95% CI':>18} {'norm':>7} {'norm 95% CI':>18} {'pos':>6}")
for s in per + [v for v in report["window_pooled"].values()]:
    nm = f"{s['normalized_mean']:+.3f}" if s["normalized_mean"] is not None else "   -  "
    nc = (f"[{s['normalized_ci'][0]:+.3f},{s['normalized_ci'][1]:+.3f}]"
          if s["normalized_ci"][0] is not None else "        -        ")
    print(f"  {s['label']:<34} {s['n_calls']:>4} {s['raw_movement_mean']:>+7.3f} "
          f"[{s['raw_ci'][0]:+.3f},{s['raw_ci'][1]:+.3f}] {nm:>7} {nc:>18} "
          f"{s['positive_direction_fraction']:>6.1%}")
print(f"\n  [save] {OUT/'validation_report.json'}")
