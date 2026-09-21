"""Stage-3b metrics. Held-out control validation only; direction and beta were frozen first.

Normalized movement is signed toward the no_history endpoint, measured against each task's
OWN unpatched baselines from this run:
    norm = (patched - self_low_2_baseline) / (no_history_baseline - self_low_2_baseline)
Tasks whose two baselines coincide have no denominator; they are excluded from the
normalized statistic only, counted separately, and always kept in the raw statistic.

Control comparisons are paired by task: the learned arm minus the control arm on the same
task, bootstrapped over tasks. A CI on the DIFFERENCE is what decides "exceeds", not two
overlapping intervals.
"""
import collections
import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
V = HERE / "out/control_validation/control_records.jsonl"
FZ = json.loads((HERE / "out/control_discovery/DIRECTION_FREEZE.json").read_text(encoding="utf-8"))
SEED, N_BOOT = 20260818, 10_000

rows = [json.loads(l) for l in V.open(encoding="utf-8") if l.strip()]
by_arm = collections.defaultdict(dict)
for r in rows:
    by_arm[r["arm"]][(r["dataset"], r["task_id"])] = r
TASKS = sorted(by_arm["steer"])


def boot_ci(vals, seed=SEED):
    v = np.asarray([x for x in vals if x is not None and not np.isnan(x)], float)
    if v.size == 0:
        return (None, None)
    rng = np.random.default_rng(seed)
    reps = [v[rng.integers(0, v.size, v.size)].mean() for _ in range(N_BOOT)]
    return float(np.percentile(reps, 2.5)), float(np.percentile(reps, 97.5))


def arm_stats(arm, cond_key="self_low_2"):
    raw, norm, toward, away, unch = [], [], 0, 0, 0
    no_denom = 0
    for k in TASKS:
        r = by_arm[arm].get(k)
        if r is None or r["score"] is None:
            continue
        tb = r["target_baseline"]
        lo, hi = r["self_low_2_endpoint"], r["no_history_endpoint"]
        if tb is None:
            continue
        mv = r["score"] - tb
        raw.append(mv)
        if mv == 0:
            unch += 1
        elif np.sign(mv) == np.sign(hi - lo) and hi != lo:
            toward += 1
        else:
            away += 1
        if hi is not None and lo is not None and hi != lo:
            norm.append((r["score"] - lo) / (hi - lo) - (tb - lo) / (hi - lo))
        else:
            no_denom += 1
    n = len(raw)
    rl, rh = boot_ci(raw)
    nl, nh = boot_ci(norm)
    return {"arm": arm, "n": n,
            "raw_mean": float(np.mean(raw)) if raw else None, "raw_ci": [rl, rh],
            "normalized_mean": float(np.mean(norm)) if norm else None,
            "normalized_ci": [nl, nh], "n_excluded_no_denominator": no_denom,
            "frac_toward": toward / n if n else None, "frac_away": away / n if n else None,
            "frac_unchanged": unch / n if n else None}


def paired_diff(a, b):
    """learned minus control, per task."""
    d = []
    for k in TASKS:
        ra, rb = by_arm[a].get(k), by_arm[b].get(k)
        if not ra or not rb or ra["score"] is None or rb["score"] is None:
            continue
        lo, hi = ra["self_low_2_endpoint"], ra["no_history_endpoint"]
        if lo is None or hi is None or hi == lo:
            continue
        d.append(((ra["score"] - ra["target_baseline"]) - (rb["score"] - rb["target_baseline"]))
                 / (hi - lo))
    lo_, hi_ = boot_ci(d)
    return {"comparison": f"{a} - {b}", "n_tasks": len(d),
            "mean_normalized_difference": float(np.mean(d)) if d else None,
            "ci": [lo_, hi_],
            "exceeds_control": bool(d and lo_ is not None and lo_ > 0)}


ARMS = ["steer", "ablate", "noop", "steer_early_L2", "steer_random"]
report = {"stage": "HELD-OUT CONTROL VALIDATION",
          "layer": FZ["layer"], "beta": FZ["beta_selected"], "alpha": FZ["ablation_alpha"],
          "frozen_before_validation": True,
          "success_criteria": FZ["success_criteria"],
          "bootstrap": {"unit": "task", "n": N_BOOT, "seed": SEED}}

n = len(rows)
report["integrity"] = {
    "n_calls": n,
    "parse_ok": sum(1 for r in rows if r["parse_status"] == "ok"),
    "parse_ok_rate": round(sum(1 for r in rows if r["parse_status"] == "ok") / n, 4),
    "a5_valid": sum(1 for r in rows if r["a5_valid"]),
    "a5_valid_rate": round(sum(1 for r in rows if r["a5_valid"]) / n, 4),
}
noop = list(by_arm["noop"].values())
report["integrity"]["noop_identity"] = {
    "n": len(noop),
    "n_identical": sum(1 for r in noop if r["score"] == r["target_baseline"]),
    "rate": round(sum(1 for r in noop if r["score"] == r["target_baseline"]) / len(noop), 4)}

report["arms"] = {a: arm_stats(a) for a in ARMS}
report["specificity"] = {a: arm_stats(a) for a in
                         ("steer_on_no_history", "steer_on_unrelated")}

# gap between self_low_2 and no_history, before vs after steering
gaps_before, gaps_after = [], []
for k in TASKS:
    st = by_arm["steer"].get(k)
    if not st or st["score"] is None:
        continue
    lo, hi = st["self_low_2_endpoint"], st["no_history_endpoint"]
    if lo is None or hi is None:
        continue
    gaps_before.append(hi - lo)
    gaps_after.append(hi - st["score"])
gl, gh = boot_ci([b - a for b, a in zip(gaps_before, gaps_after)])
report["gap"] = {
    "n_tasks": len(gaps_before),
    "gap_before_mean": float(np.mean(gaps_before)),
    "gap_after_steering_mean": float(np.mean(gaps_after)),
    "gap_reduction_mean": float(np.mean(gaps_before) - np.mean(gaps_after)),
    "gap_reduction_ci": [gl, gh],
}

report["control_comparisons"] = [paired_diff("steer", "steer_early_L2"),
                                 paired_diff("steer", "steer_random"),
                                 paired_diff("steer", "noop")]

(HERE / "out/control_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

i = report["integrity"]
print(f"  calls {i['n_calls']}  parse ok {i['parse_ok']}/{n} ({i['parse_ok_rate']:.1%})  "
      f"A5 {i['a5_valid']}/{n} ({i['a5_valid_rate']:.1%})  "
      f"no-op identity {i['noop_identity']['n_identical']}/{i['noop_identity']['n']}")
g = report["gap"]
print(f"\n  gap self_low_2->no_history: before {g['gap_before_mean']:+.3f}  "
      f"after steering {g['gap_after_steering_mean']:+.3f}  "
      f"reduction {g['gap_reduction_mean']:+.3f} [{g['gap_reduction_ci'][0]:+.3f},{g['gap_reduction_ci'][1]:+.3f}]")
print(f"\n  {'arm':<22} {'n':>3} {'raw':>7} {'raw CI':>18} {'norm':>7} {'norm CI':>18} "
      f"{'tow':>5} {'away':>5} {'unch':>5}")
for a in ARMS + ["steer_on_no_history", "steer_on_unrelated"]:
    s = report["arms"].get(a) or report["specificity"][a]
    nm = f"{s['normalized_mean']:+.3f}" if s["normalized_mean"] is not None else "  -  "
    nc = (f"[{s['normalized_ci'][0]:+.3f},{s['normalized_ci'][1]:+.3f}]"
          if s["normalized_ci"][0] is not None else "       -        ")
    print(f"  {a:<22} {s['n']:>3} {s['raw_mean']:>+7.3f} "
          f"[{s['raw_ci'][0]:+.3f},{s['raw_ci'][1]:+.3f}] {nm:>7} {nc:>18} "
          f"{s['frac_toward']:>5.0%} {s['frac_away']:>5.0%} {s['frac_unchanged']:>5.0%}")
print("\n  control comparisons (paired, normalized):")
for c in report["control_comparisons"]:
    print(f"    {c['comparison']:<28} {c['mean_normalized_difference']:+.3f} "
          f"[{c['ci'][0]:+.3f},{c['ci'][1]:+.3f}]  exceeds={c['exceeds_control']}")
print(f"\n  [save] out/control_report.json")
