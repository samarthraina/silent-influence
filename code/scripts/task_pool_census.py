#!/usr/bin/env python3
"""Read-only census of the MT-Bench / Arena-Hard / WildBench task pools ahead of the
final large-scale experiment. Uses only the existing frozen structural-eligibility rules
already baked into the pinned prompt files (mtbench_t1_pinned.json,
arena_hard_v2_pinned_v2.json, wildbench_v2_pinned.json) -- this script adds no new
eligibility criterion of its own, selects nothing, runs no model, and does not touch any
existing result file. It only reads prompt pools, prior selection/usage records, and
computes counts, duplicates, and length/formatting statistics.

    python scripts/task_pool_census.py
"""
from __future__ import annotations

import os

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from _bootstrap import REPO

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from langdetect import DetectorFactory, detect
    DetectorFactory.seed = 0
    HAVE_LANGDETECT = True
except ImportError:
    HAVE_LANGDETECT = False

OUT_DIR = REPO / "results/task_pool_census"
# Release note: this pilot artifact is not part of the code tree. Point at it with
# the SI_PILOT_FROZEN environment variable, or place the file at the repository-relative
# default below.
PILOT_FROZEN = Path(os.environ.get(
    "SI_PILOT_FROZEN", str(REPO / "data", "pilot", "frozen_olmo_answers.json")))
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl_ids(path, id_field="prompt_id"):
    ids = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(str(json.loads(line)[id_field]))
    return ids


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def shingles(text: str, k: int = 5) -> set:
    words = normalize(text).split()
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a) + len(b) - inter
    return inter / union if union else 0.0


def detect_lang(text: str):
    if not HAVE_LANGDETECT:
        return None
    try:
        return detect(text[:1000])
    except Exception:
        return "unknown"


# ============================================================
# 1. Load each pool + previously-used sets
# ============================================================

def census_mtbench():
    pool = load_json(REPO / "data/prompts/mtbench_t1_pinned.json")
    total_source = pool["n_prompts"] + len(pool["excluded"])  # 78 + 2 = 80
    eligible = pool["prompts"]

    used_phase1a = set(str(c["prompt_id"]) for c in
                       load_json(REPO / "data/candidates/phase1a_mtbench_20.json")["candidates"])
    used_pilot = set(a["prompt_id"] for a in load_json(PILOT_FROZEN)["accepted"])
    sel = load_json(REPO / "data/prompts/scaled_tasks_seed20260816.json")
    used_90 = set(t["task_id"] for t in sel["datasets"]["mtbench"]["selected"])

    used = used_phase1a | used_pilot | used_90
    unused_eligible = [p for p in eligible if p["prompt_id"] not in used]

    return {
        "name": "mtbench", "total_source": total_source,
        "n_structurally_excluded": len(pool["excluded"]),
        "structural_exclusion_reasons": Counter(e["reason"] for e in pool["excluded"]),
        "n_eligible": len(eligible),
        "used_breakdown": {
            "phase1a_screening": len(used_phase1a),
            "pilot_24task": len(used_pilot),
            "scaled_90task": len(used_90),
        },
        "n_used_total": len(used),
        "n_unused_eligible": len(unused_eligible),
        "eligible_rows": eligible,
        "unused_eligible_rows": unused_eligible,
        "used_ids": used,
        "id_field": "prompt_id", "text_field": "prompt", "cat_field": "subcategory",
    }


def census_arena_hard():
    pool = load_json(REPO / "data/prompts/arena_hard_v2_pinned_v2.json")
    total_source = pool["n_prompts"] + len(pool["excluded"])  # 689 + 61 = 750
    eligible = pool["prompts"]

    sel = load_json(REPO / "data/prompts/scaled_tasks_seed20260816.json")
    used_90 = set(t["task_id"] for t in sel["datasets"]["arena_hard"]["selected"])

    legacy = load_json(REPO / "data/prompts/arena_hard_v2_30_seed42.json")
    legacy_ids = set(u["uid"] for u in legacy)
    eligible_ids = set(p["uid"] for p in eligible)
    overlap_with_fresh_pool = legacy_ids & eligible_ids

    # The legacy 30-task pull shares uids with the current pinned pool -- all 30 are
    # present in it -- and those tasks were genuinely consumed by earlier phases
    # (pinned_candidates_v1 / phase1a / phase1b / dose_direction). They must therefore
    # count as previously used, not merely be footnoted, or the unused pool is
    # overstated by 30. (The 90-task selection already excluded them correctly.)
    used = used_90 | legacy_ids
    unused_eligible = [p for p in eligible if p["uid"] not in used]

    return {
        "name": "arena_hard", "total_source": total_source,
        "n_structurally_excluded": len(pool["excluded"]),
        "structural_exclusion_reasons": Counter(
            e["reason"].split(":")[0] for e in pool["excluded"]),
        "n_eligible": len(eligible),
        "used_breakdown": {"scaled_90task": len(used_90),
                          "legacy_30task_pull": len(legacy_ids)},
        "n_used_total": len(used & eligible_ids),
        "n_unused_eligible": len(unused_eligible),
        "eligible_rows": eligible,
        "unused_eligible_rows": unused_eligible,
        "used_ids": used,
        "id_field": "uid", "text_field": "prompt", "cat_field": "subcategory",
        "legacy_pool_note": {
            "legacy_pool_size": len(legacy_ids),
            "legacy_all_used": True,
            "legacy_overlap_with_fresh_750_pool": len(overlap_with_fresh_pool),
            "legacy_overlap_with_scaled_90task": len(legacy_ids & used_90),
            "note": ("A 30-task pull that predates the current 750-task pinned pool but "
                    "shares uids with it; fully consumed by earlier phases and counted "
                    "in used_breakdown above."),
        },
    }


def census_wildbench():
    pool = load_json(REPO / "data/prompts/wildbench_v2_pinned.json")
    total_source = pool["n_prompts"] + len(pool["excluded"])  # 697 + 327 = 1024
    eligible = pool["prompts"]

    used_screen = load_jsonl_ids(REPO / "results/screen/wildbench/generation_records.jsonl")
    sel = load_json(REPO / "data/prompts/scaled_tasks_seed20260816.json")
    used_90 = set(t["task_id"] for t in sel["datasets"]["wildbench"]["selected"])

    used = used_screen | used_90
    unused_eligible = [p for p in eligible if p["prompt_id"] not in used]

    return {
        "name": "wildbench", "total_source": total_source,
        "n_structurally_excluded": len(pool["excluded"]),
        "structural_exclusion_reasons": Counter(
            e["reason"].split(":")[0].split("(")[0].strip() for e in pool["excluded"]),
        "n_eligible": len(eligible),
        "used_breakdown": {
            "screen_attempt_unfrozen": len(used_screen),
            "scaled_90task": len(used_90),
        },
        "n_used_total": len(used),
        "n_unused_eligible": len(unused_eligible),
        "eligible_rows": eligible,
        "unused_eligible_rows": unused_eligible,
        "used_ids": used,
        "id_field": "prompt_id", "text_field": "prompt", "cat_field": "subcategory",
    }


# ============================================================
# 2. Category / language breakdown
# ============================================================

def category_breakdown(census):
    cat_f = census["cat_field"]
    total_by_cat = Counter(r[cat_f] for r in census["eligible_rows"])
    unused_by_cat = Counter(r[cat_f] for r in census["unused_eligible_rows"])
    return total_by_cat, unused_by_cat


def language_breakdown(census, log):
    if not HAVE_LANGDETECT:
        return None
    text_f = census["text_field"]
    langs = Counter()
    for r in census["unused_eligible_rows"]:
        lang = detect_lang(r[text_f])
        langs[lang] += 1
    return langs


# ============================================================
# 3. Duplicate / near-duplicate detection
# ============================================================

def find_exact_duplicates(all_rows):
    """all_rows: list of (dataset, id, text). Returns within- and cross-dataset exact
    duplicate groups keyed by normalized text."""
    by_norm = defaultdict(list)
    for ds, rid, text in all_rows:
        by_norm[normalize(text)].append((ds, rid))
    within, cross = [], []
    for norm, members in by_norm.items():
        if len(members) < 2:
            continue
        datasets = set(m[0] for m in members)
        if len(datasets) > 1:
            cross.append(members)
        else:
            within.append(members)
    return within, cross


def find_near_duplicates(all_rows, threshold=0.6, k=5, log=print):
    """Length-bucket-blocked shingle-Jaccard near-duplicate search. Only compares pairs
    whose character length is within 15% of each other, to keep this tractable at ~1450
    items without a specialized similarity-search dependency."""
    items = [(ds, rid, text, shingles(text, k), len(text)) for ds, rid, text in all_rows
            if text and text.strip()]
    items.sort(key=lambda x: x[4])
    n = len(items)
    within_pairs, cross_pairs = [], []
    for i in range(n):
        ds_i, id_i, text_i, sh_i, len_i = items[i]
        if not sh_i:
            continue
        j = i + 1
        while j < n and items[j][4] <= len_i * (1 + (1 - threshold) * 0.5 + 0.15):
            ds_j, id_j, text_j, sh_j, len_j = items[j]
            if len_j > len_i * 1.15:
                break
            sim = jaccard(sh_i, sh_j)
            if sim >= threshold and normalize(text_i) != normalize(text_j):
                pair = {"a": (ds_i, id_i), "b": (ds_j, id_j), "similarity": round(sim, 3)}
                (within_pairs if ds_i == ds_j else cross_pairs).append(pair)
            j += 1
    return within_pairs, cross_pairs


# ============================================================
# 4. Length / formatting audit
# ============================================================

REPLACEMENT_CHAR = "\ufffd"
RATING_REQUEST_RE = re.compile(
    r"\brate\b.{0,30}\b(?:\d+\s*[-\u2013]\s*\d+|out of \d+|/\s*10|/\s*100)\b", re.I)


def length_format_audit(census):
    text_f = census["text_field"]
    rows = census["unused_eligible_rows"]
    lengths = sorted(len(r[text_f]) for r in rows)
    n = len(lengths)

    def pct(p):
        if n == 0:
            return None
        idx = min(n - 1, int(p * n))
        return lengths[idx]

    issues = {"empty_or_whitespace": [], "replacement_char": [],
             "rating_request_language": [], "very_short_lt20chars": [],
             "very_long_gt4000chars": []}
    for r in rows:
        text = r[text_f]
        rid = r[census["id_field"]]
        if not text or not text.strip():
            issues["empty_or_whitespace"].append(rid)
            continue
        if REPLACEMENT_CHAR in text:
            issues["replacement_char"].append(rid)
        if RATING_REQUEST_RE.search(text):
            issues["rating_request_language"].append(rid)
        if len(text) < 20:
            issues["very_short_lt20chars"].append(rid)
        if len(text) > 4000:
            issues["very_long_gt4000chars"].append(rid)

    return {
        "n": n, "min": lengths[0] if n else None, "p25": pct(0.25), "median": pct(0.5),
        "p75": pct(0.75), "p95": pct(0.95), "max": lengths[-1] if n else None,
        "issues": {k: {"count": len(v), "ids": v[:15]} for k, v in issues.items()},
    }


# ============================================================
# main
# ============================================================

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = print

    log(f"langdetect available: {HAVE_LANGDETECT}")
    mt = census_mtbench()
    ah = census_arena_hard()
    wb = census_wildbench()
    censuses = {"mtbench": mt, "arena_hard": ah, "wildbench": wb}

    report = {"generated_at_note": "read-only census, no models run, no selection made",
             "datasets": {}}

    for name, c in censuses.items():
        log("\n" + "=" * 90)
        log(f"{name.upper()}")
        log("=" * 90)
        log(f"total source tasks           : {c['total_source']}")
        log(f"structurally excluded        : {c['n_structurally_excluded']}  "
           f"{dict(c['structural_exclusion_reasons'])}")
        log(f"eligible (post-structural)   : {c['n_eligible']}")
        log(f"previously used (breakdown)  : {c['used_breakdown']}")
        log(f"previously used (total)      : {c['n_used_total']}")
        log(f"eligible AND unused          : {c['n_unused_eligible']}")
        if "legacy_pool_note" in c:
            log(f"legacy pool note              : {c['legacy_pool_note']}")

        total_cat, unused_cat = category_breakdown(c)
        log(f"category breakdown (eligible): {dict(sorted(total_cat.items()))}")
        log(f"category breakdown (unused)  : {dict(sorted(unused_cat.items()))}")

        langs = language_breakdown(c, log)
        if langs:
            log(f"language breakdown (unused, langdetect on unused-eligible pool): "
               f"{dict(langs.most_common())}")

        lf = length_format_audit(c)
        log(f"length stats (chars, unused-eligible): min={lf['min']} p25={lf['p25']} "
           f"median={lf['median']} p75={lf['p75']} p95={lf['p95']} max={lf['max']}")
        for issue, d in lf["issues"].items():
            if d["count"]:
                log(f"  [{issue}] {d['count']} tasks  e.g. {d['ids'][:5]}")

        report["datasets"][name] = {
            "total_source": c["total_source"],
            "n_structurally_excluded": c["n_structurally_excluded"],
            "structural_exclusion_reasons": dict(c["structural_exclusion_reasons"]),
            "n_eligible": c["n_eligible"],
            "used_breakdown": c["used_breakdown"],
            "n_used_total": c["n_used_total"],
            "n_unused_eligible": c["n_unused_eligible"],
            "category_breakdown_eligible": dict(sorted(total_cat.items())),
            "category_breakdown_unused": dict(sorted(unused_cat.items())),
            "language_breakdown_unused": dict(langs.most_common()) if langs else None,
            "length_format_audit": lf,
        }
        if "legacy_pool_note" in c:
            report["datasets"][name]["legacy_pool_note"] = c["legacy_pool_note"]

    # ---- duplicates: within unused-eligible pools, and cross-dataset ----
    all_rows = []
    for name, c in censuses.items():
        text_f, id_f = c["text_field"], c["id_field"]
        for r in c["unused_eligible_rows"]:
            all_rows.append((name, r[id_f], r[text_f]))

    log("\n" + "=" * 90)
    log("DUPLICATE / NEAR-DUPLICATE CENSUS (unused-eligible pools only, ~%d tasks)" % len(all_rows))
    log("=" * 90)
    exact_within, exact_cross = find_exact_duplicates(all_rows)
    log(f"exact duplicate groups (within-dataset): {len(exact_within)}")
    log(f"exact duplicate groups (cross-dataset)  : {len(exact_cross)}")
    for grp in exact_cross[:10]:
        log(f"  {grp}")

    near_within, near_cross = find_near_duplicates(all_rows, threshold=0.6, log=log)
    log(f"near-duplicate pairs, Jaccard>=0.60, 5-word shingles (within-dataset): {len(near_within)}")
    log(f"near-duplicate pairs, Jaccard>=0.60, 5-word shingles (cross-dataset) : {len(near_cross)}")
    for p in near_cross[:10]:
        log(f"  {p}")

    report["duplicates"] = {
        "method": "exact: normalized-text hash match. near: 5-word shingle Jaccard "
                 ">= 0.60, blocked by character length within ~15%.",
        "n_pool_checked": len(all_rows),
        "exact_within_dataset_groups": len(exact_within),
        "exact_cross_dataset_groups": len(exact_cross),
        "exact_cross_dataset_examples": exact_cross[:20],
        "near_within_dataset_pairs": len(near_within),
        "near_cross_dataset_pairs": len(near_cross),
        "near_cross_dataset_examples": near_cross[:20],
    }

    # ---- feasibility ----
    log("\n" + "=" * 90)
    log("500-600 TASK FEASIBILITY (arithmetic only, no allocation decision made)")
    log("=" * 90)
    total_unused = sum(c["n_unused_eligible"] for c in censuses.values())
    log(f"total eligible-and-unused across all 3 datasets: {total_unused}")
    for name, c in censuses.items():
        share_if_even_thirds = round(550 / 3)
        log(f"  {name}: {c['n_unused_eligible']} available "
           f"(need ~{share_if_even_thirds} for an even three-way split of 550)")
    report["feasibility"] = {
        "total_eligible_unused": total_unused,
        "target_range": [500, 600],
        "raw_capacity_sufficient": total_unused >= 600,
        "even_three_way_split_of_550_per_dataset": round(550 / 3),
        "mtbench_can_supply_even_share": mt["n_unused_eligible"] >= round(550 / 3),
    }

    out_path = OUT_DIR / "task_pool_census.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    log(f"\n[save] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
