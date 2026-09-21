#!/usr/bin/env python3
"""Amendment A9: select the 234 tasks that will be scored -- all 78 MT-Bench, 78 Arena-Hard and
78 WildBench -- from the frozen 578-task manifest.

The allocation procedure and strata are exactly those used to build the 250-task pools
(scripts/select_final_tasks_v2_english.py): stratify by the task's frozen `category`, allocate
with largest_remainder, then within each stratum sort candidates by task id, shuffle with a
stratum RNG seeded from sha256("<seed>|<dataset>|<category>"), and take the first k. Only the
seed differs: A9 uses 20260818.

Reads ONLY pre-existing task metadata -- dataset, source_task_id and category. It never opens
the generated answers, and nothing about answer content, length, scores, rationales, parse
behaviour or any experimental outcome can reach the selection.

    python scripts/select_a9_scoring_tasks.py --out data/prompts/a9_scoring_tasks_seed20260818.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

MANIFEST = REPO / "data/prompts/final_tasks_v2_english_seed20260817.json"
MANIFEST_SHA256 = "a001d48b7769311da33cba1a8ef51bb4e9d1a27b2cc0d007bce85adab606037f"
A9_SEED = 20260818
TARGET = {"mtbench": 78, "arena_hard": 78, "wildbench": 78}
TOTAL = 234


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stratum_rng(*parts) -> random.Random:
    """Identical construction to the frozen selector, with A9's seed."""
    key = "|".join([str(A9_SEED)] + [str(p) for p in parts])
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def largest_remainder(counts: dict, total: int) -> dict:
    """Byte-for-byte the frozen allocator."""
    pool = sum(counts.values())
    if pool == 0:
        return {k: 0 for k in counts}
    quotas = {k: total * c / pool for k, c in counts.items()}
    alloc = {k: int(q) for k, q in quotas.items()}
    order = sorted(counts, key=lambda k: (-(quotas[k] - alloc[k]), str(k)))
    for k in order[:total - sum(alloc.values())]:
        alloc[k] += 1
    for k, a in alloc.items():
        assert a <= counts[k], f"stratum {k}: allocated {a} > available {counts[k]}"
    assert sum(alloc.values()) == total
    return alloc


def select_dataset(dataset: str, tasks: list, target: int) -> dict:
    """Census when the frame equals the target (MT-Bench), otherwise stratified sampling."""
    if len(tasks) == target:
        return {"rule": "census-complete: every task in the frozen pool is scored",
                "selected": [t["source_task_id"] for t in
                             sorted(tasks, key=lambda t: t["source_task_id"])],
                "strata": {f"{dataset}:all": {"frame_size": len(tasks), "allocated": target}},
                "seed_used": None}

    by_cat: dict = {}
    for t in tasks:
        by_cat.setdefault(t["category"], []).append(t)
    alloc = largest_remainder({c: len(v) for c, v in by_cat.items()}, target)

    selected, strata = [], {}
    for cat in sorted(by_cat):
        cands = sorted(by_cat[cat], key=lambda t: t["source_task_id"])
        rng = stratum_rng(dataset, cat)
        shuffled = cands[:]
        rng.shuffle(shuffled)
        k = alloc[cat]
        strata[f"{dataset}:{cat}"] = {"frame_size": len(cands), "allocated": k}
        selected.extend(t["source_task_id"] for t in shuffled[:k])
    assert len(selected) == target, f"{dataset}: got {len(selected)}"
    return {"rule": ("stratified by frozen category; largest-remainder allocation; per-stratum "
                     "shuffle seeded from sha256(seed|dataset|category); metadata only"),
            "selected": sorted(selected), "strata": strata, "seed_used": A9_SEED}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest-file", default=str(MANIFEST))
    ap.add_argument("--out", default=str(REPO / "data/prompts/a9_scoring_tasks_seed20260818.json"))
    ap.add_argument("--skip-hash-check", action="store_true")
    args = ap.parse_args()

    mpath = Path(args.manifest_file)
    got = sha256_file(mpath)
    if not args.skip_hash_check and got != MANIFEST_SHA256:
        raise SystemExit(f"FROZEN MANIFEST MISMATCH: {got} != {MANIFEST_SHA256}")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))

    out = {"record_id": "a9_scoring_task_selection",
           "amendment": "A9", "selection_seed": A9_SEED,
           "source_manifest": str(mpath.relative_to(REPO)).replace("\\", "/"),
           "source_manifest_sha256": got,
           "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "n_selected_total": 0, "target_per_dataset": TARGET,
           "metadata_only": True,
           "inputs_used": ["dataset", "source_task_id", "category"],
           "never_consulted": ["generated answer content", "answer length", "scores",
                               "rationales", "parse behaviour", "any experimental outcome"],
           "datasets": {}}

    for ds in ("mtbench", "arena_hard", "wildbench"):
        pool = manifest["datasets"][ds]["selected"]
        tasks = [{"source_task_id": t["source_task_id"], "category": t["category"]}
                 for t in pool]
        res = select_dataset(ds, tasks, TARGET[ds])
        cat_of = {t["source_task_id"]: t["category"] for t in tasks}
        res["n_pool"] = len(pool)
        res["n_selected"] = len(res["selected"])
        res["category_counts"] = {}
        for tid in res["selected"]:
            c = cat_of[tid]
            res["category_counts"][c] = res["category_counts"].get(c, 0) + 1
        res["category_counts"] = dict(sorted(res["category_counts"].items()))
        out["datasets"][ds] = res
        out["n_selected_total"] += res["n_selected"]

    assert out["n_selected_total"] == TOTAL, out["n_selected_total"]
    all_ids = [(ds, tid) for ds in out["datasets"] for tid in out["datasets"][ds]["selected"]]
    assert len(all_ids) == len(set(all_ids)) == TOTAL, "duplicate selection"

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_bytes((json.dumps(out, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"[a9] selected {out['n_selected_total']} tasks "
          f"({', '.join(f'{d}={out['datasets'][d]['n_selected']}' for d in out['datasets'])})")
    for ds, r in out["datasets"].items():
        print(f"  {ds:11s} pool={r['n_pool']:3d} -> {r['n_selected']:2d}  {r['category_counts']}")
    print(f"[save] {outp}")
    print(f"[sha256] {sha256_file(outp)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
