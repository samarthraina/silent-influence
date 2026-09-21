#!/usr/bin/env python3
"""Build the exclusion ledger and freeze the 90-task scaled selection, once.

Selection happens exactly once, before any candidate is generated or scored, and does not
change afterward: this script reads only prompt pools and prior-usage records, never any
answer or score. Re-running it is deterministic (same seed, same pools -> same output) but
the frozen file it writes is the artifact that downstream scripts actually read, and this
script never overwrites an existing frozen file — delete it explicitly to regenerate.

Previously-used exclusion, per dataset:
  MT-Bench   : union of data/candidates/phase1a_mtbench_20.json (20 ids, an earlier
               screening phase) and the pilot's own 24 heldout ids (Brain/work/
               mtbench_audit/frozen_olmo_answers.json). 78-pool minus 44 used minus the
               2 structural exclusions already baked into mtbench_t1_pinned.json = 34
               eligible.
  Arena-Hard : all 30 ids in data/prompts/arena_hard_v2_30_seed42.json are already used
               (data/candidates/pinned_candidates_v1.json). The fresh pool pinned by
               prepare_arena_hard_v2.py (689 structurally-eligible, disjoint source pull)
               is used instead; none of its ids overlap the legacy 30 (different uids from
               a fresh fetch), so no additional exclusion is needed there, but the 30 are
               still recorded and checked against by uid for auditability.
  WildBench  : the 12 ids attempted (never scored or frozen — the candidate-freeze gate
               failed on a token-cap truncation) in results/screen/wildbench/
               generation_records.jsonl. Excluded conservatively per instruction.

    python scripts/select_scaled_tasks.py
"""
from __future__ import annotations

import os

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

SEED = 20260816
TARGET = {"mtbench": 30, "arena_hard": 30, "wildbench": 30}
ARENA_HARD_SUBCATS = ("coding", "math", "creative_writing")

OUT_SELECTION = REPO / "data/prompts/scaled_tasks_seed20260816.json"
OUT_SUMMARY_DIR = REPO / "results/scaled_silent_influence"
# Release note: this pilot artifact is not part of the code tree. Point at it with
# the SI_PILOT_FROZEN environment variable, or place the file at the repository-relative
# default below.
PILOT_FROZEN = Path(os.environ.get(
    "SI_PILOT_FROZEN", str(REPO / "data", "pilot", "frozen_olmo_answers.json")))
WILDBENCH_SCREEN_RECORDS = REPO / "results/screen/wildbench/generation_records.jsonl"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl_ids(path: Path, id_field: str = "prompt_id") -> set:
    ids = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(str(json.loads(line)[id_field]))
    return ids


def balanced_allocation(target_n: int, eligible_counts: dict) -> dict:
    """Distribute target_n across categories as evenly as each category's eligible pool
    permits: water-fill one unit at a time to whichever category (with room left) is
    currently smallest, alphabetical tie-break, so the result is deterministic."""
    cats = sorted(eligible_counts)
    alloc = {c: 0 for c in cats}
    remaining = target_n
    while remaining > 0:
        room = [c for c in cats if alloc[c] < eligible_counts[c]]
        if not room:
            raise ValueError(f"pool exhausted: only {target_n - remaining} of "
                             f"{target_n} allocatable across {eligible_counts}")
        smallest = min(alloc[c] for c in room)
        pick = next(c for c in room if alloc[c] == smallest)
        alloc[pick] += 1
        remaining -= 1
    return alloc


def draw_with_reserve(rng: random.Random, pool: list, k: int) -> tuple:
    """Shuffle the whole eligible pool once; first k are selected, the rest (in the same
    shuffled order) become the ordered reserve for this stratum."""
    shuffled = pool[:]
    rng.shuffle(shuffled)
    return shuffled[:k], shuffled[k:]


def task_record(dataset: str, task_id: str, category, question: str,
                source_revision: str) -> dict:
    return {
        "dataset": dataset,
        "task_id": task_id,
        "category": category,
        "question": question,
        "question_sha256": sha256_text(question),
        "source_revision": source_revision,
        "selection_seed": SEED,
    }


def select_mtbench(rng: random.Random) -> dict:
    pool = load_json(REPO / "data/prompts/mtbench_t1_pinned.json")
    used_phase1a = set(str(c["prompt_id"]) for c in
                       load_json(REPO / "data/candidates/phase1a_mtbench_20.json")["candidates"])
    used_pilot = set(a["prompt_id"] for a in load_json(PILOT_FROZEN)["accepted"])
    used = used_phase1a | used_pilot

    eligible = [p for p in pool["prompts"] if p["prompt_id"] not in used]
    by_cat = {}
    for p in eligible:
        by_cat.setdefault(p["subcategory"], []).append(p)
    eligible_counts = {c: len(v) for c, v in by_cat.items()}

    alloc = balanced_allocation(TARGET["mtbench"], eligible_counts)

    selected, reserve = [], []
    for cat in sorted(by_cat):
        chosen, rest = draw_with_reserve(rng, by_cat[cat], alloc[cat])
        selected += [task_record("mtbench", p["prompt_id"], p["subcategory"], p["prompt"],
                                 pool["source_revision"]) for p in chosen]
        reserve += [task_record("mtbench", p["prompt_id"], p["subcategory"], p["prompt"],
                                pool["source_revision"]) for p in rest]

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/mtbench_t1_pinned.json",
        "n_pool_total": pool["n_prompts"],
        "structurally_excluded_ids": [e["prompt_id"] for e in pool["excluded"]],
        "previously_used_excluded_ids": sorted(used, key=lambda x: int(x)),
        "previously_used_sources": [
            {"file": "data/candidates/phase1a_mtbench_20.json", "n_ids": len(used_phase1a)},
            {"file": str(PILOT_FROZEN), "n_ids": len(used_pilot)},
        ],
        "n_eligible": len(eligible),
        "eligible_by_category": eligible_counts,
        "target_n": TARGET["mtbench"],
        "category_allocation": alloc,
        "selected": selected,
        "reserve": reserve,
    }


def select_arena_hard(rng: random.Random) -> dict:
    pool = load_json(REPO / "data/prompts/arena_hard_v2_pinned_v2.json")
    legacy_used_uids = set(u["uid"] for u in
                           load_json(REPO / "data/prompts/arena_hard_v2_30_seed42.json"))

    by_subcat = {}
    for p in pool["prompts"]:
        by_subcat.setdefault(p["subcategory"], []).append(p)
    overlap = set(p["uid"] for cat in by_subcat.values() for p in cat) & legacy_used_uids
    if overlap:
        for cat in by_subcat:
            by_subcat[cat] = [p for p in by_subcat[cat] if p["uid"] not in overlap]

    per_cat_n = TARGET["arena_hard"] // len(ARENA_HARD_SUBCATS)
    selected, reserve = [], []
    alloc = {}
    for cat in ARENA_HARD_SUBCATS:
        chosen, rest = draw_with_reserve(rng, by_subcat[cat], per_cat_n)
        alloc[cat] = per_cat_n
        selected += [task_record("arena_hard", p["uid"], p["subcategory"], p["prompt"],
                                 pool["source_revision"]) for p in chosen]
        reserve += [task_record("arena_hard", p["uid"], p["subcategory"], p["prompt"],
                                pool["source_revision"]) for p in rest]

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/arena_hard_v2_pinned_v2.json",
        "n_pool_total": pool["n_prompts"],
        "structurally_excluded_ids": [e["prompt_id"] for e in pool["excluded"]],
        "previously_used_excluded_ids": sorted(legacy_used_uids),
        "previously_used_sources": [
            {"file": "data/prompts/arena_hard_v2_30_seed42.json (legacy, disjoint pull)",
             "n_ids": len(legacy_used_uids), "n_overlap_with_fresh_pool": len(overlap)},
        ],
        "n_eligible": sum(len(v) for v in by_subcat.values()),
        "eligible_by_category": {c: len(v) for c, v in by_subcat.items()},
        "target_n": TARGET["arena_hard"],
        "category_allocation": alloc,
        "selected": selected,
        "reserve": reserve,
    }


def select_wildbench(rng: random.Random) -> dict:
    pool = load_json(REPO / "data/prompts/wildbench_v2_pinned.json")
    used = load_jsonl_ids(WILDBENCH_SCREEN_RECORDS)

    eligible = [p for p in pool["prompts"] if p["prompt_id"] not in used]
    chosen, rest = draw_with_reserve(rng, eligible, TARGET["wildbench"])

    selected = [task_record("wildbench", p["prompt_id"], p["subcategory"], p["prompt"],
                            pool["source_revision"]) for p in chosen]
    reserve = [task_record("wildbench", p["prompt_id"], p["subcategory"], p["prompt"],
                           pool["source_revision"]) for p in rest]
    from collections import Counter
    resulting_dist = dict(sorted(Counter(t["category"] for t in selected).items()))

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/wildbench_v2_pinned.json",
        "n_pool_total": pool["n_prompts"],
        "structurally_excluded_ids": [e["prompt_id"] for e in pool["excluded"]],
        "previously_used_excluded_ids": sorted(used),
        "previously_used_sources": [
            {"file": "results/screen/wildbench/generation_records.jsonl", "n_ids": len(used),
             "note": "attempted only; never scored or frozen (freeze gate failed on a "
                     "token-cap truncation); excluded conservatively"},
        ],
        "n_eligible": len(eligible),
        "target_n": TARGET["wildbench"],
        "selection_method": "unstratified seeded random sample",
        "resulting_category_distribution": resulting_dist,
        "selected": selected,
        "reserve": reserve,
    }


def main() -> int:
    if OUT_SELECTION.exists():
        raise SystemExit(f"refusing to overwrite an existing frozen selection: "
                         f"{OUT_SELECTION}\ndelete it explicitly to regenerate.")

    # Independent RNG per dataset (all seeded from the same base seed) so adding/removing
    # a dataset never perturbs another dataset's draw order.
    datasets = {
        "mtbench": select_mtbench(random.Random(SEED)),
        "arena_hard": select_arena_hard(random.Random(SEED)),
        "wildbench": select_wildbench(random.Random(SEED)),
    }

    n_selected_total = sum(len(d["selected"]) for d in datasets.values())
    payload = {
        "experiment": "scaled_silent_influence",
        "selection_seed": SEED,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection_note": ("Selection happens once, from prompt pools and prior-usage "
                           "records only. No answer-quality, baseline-score, headroom, or "
                           "effect information was available at selection time -- "
                           "candidate answers and scores did not yet exist."),
        "n_selected_total": n_selected_total,
        "datasets": datasets,
    }
    OUT_SELECTION.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_SELECTION, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    summary = {
        "selection_seed": SEED,
        "n_selected_total": n_selected_total,
        "per_dataset": {
            name: {
                "n_pool_total": d["n_pool_total"],
                "n_structurally_excluded": len(d["structurally_excluded_ids"]),
                "n_previously_used_excluded": len(d["previously_used_excluded_ids"]),
                "n_eligible": d["n_eligible"],
                "n_selected": len(d["selected"]),
                "n_reserve": len(d["reserve"]),
                **({"category_allocation": d["category_allocation"]}
                   if "category_allocation" in d else {}),
                **({"resulting_category_distribution": d["resulting_category_distribution"]}
                   if "resulting_category_distribution" in d else {}),
            }
            for name, d in datasets.items()
        },
    }
    OUT_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_SUMMARY_DIR / "dataset_selection_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, indent=2))
    print(f"\n[save] {OUT_SELECTION}")
    print(f"[save] {OUT_SUMMARY_DIR / 'dataset_selection_summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
