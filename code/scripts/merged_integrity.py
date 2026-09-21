"""Merged-set integrity check. Read-only; reports counts and coverage only."""
import json, sys, hashlib, collections, pathlib

P = pathlib.Path("results/behavioral/merged_raw_results.jsonl")
rows = [json.loads(l) for l in P.open(encoding="utf-8") if l.strip()]
EXPECT = {"olmo32b": (468, 2), "llama": (1404, 6), "qwen": (1404, 6), "gemma": (1404, 6)}
PRIMARY_CONDS = {"no_history", "self_low_2"}
ALL_CONDS = {"no_history", "self_low_2", "other_low_2", "unrelated_low_2",
             "verbal_negative", "self_high_10"}
DATASETS = {"mtbench", "arena_hard", "wildbench"}

ids = [r["unit_id"] for r in rows]
dupes = {u: n for u, n in collections.Counter(ids).items() if n > 1}
by_scorer = collections.defaultdict(list)
for r in rows: by_scorer[r["scorer_key"]].append(r)

out, ok = {}, True
out["total_records"] = len(rows)
out["total_expected"] = 4680
out["unique_unit_ids"] = len(set(ids))
out["duplicate_unit_ids"] = len(dupes)
out["technical_failures"] = sum(1 for r in rows if r.get("generation_error"))
out["scorers_present"] = sorted(by_scorer)
ok &= len(rows) == 4680 and len(set(ids)) == 4680 and not dupes
ok &= out["technical_failures"] == 0
ok &= sorted(by_scorer) == sorted(EXPECT)

per = {}
for s, (n_exp, n_cond) in EXPECT.items():
    rs = by_scorer.get(s, [])
    conds = collections.Counter(r["condition"] for r in rs)
    ds = collections.Counter(r["dataset"] for r in rs)
    tasks = {(r["dataset"], r["source_task_id"]) for r in rs}
    exp_conds = PRIMARY_CONDS if n_cond == 2 else ALL_CONDS
    entry = {
        "records": len(rs), "records_expected": n_exp, "records_ok": len(rs) == n_exp,
        "n_conditions": len(conds), "n_conditions_expected": n_cond,
        "conditions": sorted(conds), "condition_set_exact": set(conds) == exp_conds,
        "per_condition": dict(sorted(conds.items())),
        "per_condition_uniform_234": set(conds.values()) == {234},
        "distinct_tasks": len(tasks), "tasks_ok": len(tasks) == 234,
        "per_dataset": dict(sorted(ds.items())),
        "dataset_set_exact": set(ds) == DATASETS,
        "per_dataset_uniform": set(ds.values()) == {78 * n_cond},
    }
    ok &= all(entry[k] for k in ("records_ok", "condition_set_exact",
                                 "per_condition_uniform_234", "tasks_ok",
                                 "dataset_set_exact", "per_dataset_uniform"))
    per[s] = entry
out["per_scorer"] = per

# every scorer must cover the SAME 234 tasks
tasksets = {s: {(r["dataset"], r["source_task_id"]) for r in rs} for s, rs in by_scorer.items()}
common = set.intersection(*tasksets.values())
out["identical_234_task_set_across_scorers"] = all(t == common for t in tasksets.values()) and len(common) == 234
ok &= out["identical_234_task_set_across_scorers"]
out["merged_sha256"] = hashlib.sha256(P.read_bytes()).hexdigest()
out["MERGED_INTEGRITY_PASS"] = bool(ok)

pathlib.Path("results/behavioral/merged_integrity.json").write_text(
    json.dumps(out, indent=2), encoding="utf-8")

print(f"  total_records            : {out['total_records']} / 4680")
print(f"  unique_unit_ids          : {out['unique_unit_ids']} / 4680")
print(f"  duplicate_unit_ids       : {out['duplicate_unit_ids']}")
print(f"  technical_failures       : {out['technical_failures']}")
print(f"  identical 234-task set   : {out['identical_234_task_set_across_scorers']}")
for s in ("olmo32b", "llama", "qwen", "gemma"):
    e = per[s]
    print(f"  {s:<8} {e['records']:>5}/{e['records_expected']}  conds={e['n_conditions']}/{e['n_conditions_expected']} "
          f"tasks={e['distinct_tasks']}  per_cond={sorted(set(e['per_condition'].values()))} "
          f"per_ds={sorted(set(e['per_dataset'].values()))}")
print(f"  MERGED_INTEGRITY_PASS    : {out['MERGED_INTEGRITY_PASS']}")
sys.exit(0 if ok else 1)
