#!/usr/bin/env python3
"""Freeze the 578-task selection for the final behavioral study.

Read-only against every prompt pool and prior-usage record; generates no answers, loads no
model, and never touches results/scaled_silent_influence*/. Selection happens exactly once:
this script refuses to overwrite an existing frozen manifest -- delete it explicitly to
regenerate.

Composition (per the approved plan):
  MT-Bench   : all 78 structurally eligible first-turn tasks, previous-use status marked
               per task. 74 of the 78 were used in an earlier phase; that re-use is
               deliberate and is recorded, not hidden.
  Arena-Hard : 250 drawn only from the eligible-and-unused pool, minus 3 manually
               confirmed corrupted-notation tasks. Two-stage proportional strata --
               first across coding / creative_writing / math, then within each category
               across English / non-English.
  WildBench  : 250 drawn only from the eligible-and-unused pool, minus 1 manually
               confirmed corrupted-notation task and minus one member of the confirmed
               near-duplicate pair (the lexicographically larger id is dropped).
               Proportional strata across the 11 categories.

Proportions are computed from each dataset's own SAMPLING FRAME (eligible-and-unused after
the exclusions above), not from the wider eligible pool. The two differ by well under a
percentage point in every category, and using the frame is the self-consistent choice: it
is what we actually draw from, so every stratum quota is guaranteed satisfiable. Recorded
explicitly in the manifest as `proportion_basis`.

Nothing outcome-dependent enters selection: no score, effect, answer quality, headroom, or
any statistic derived from a model response is read here. The only per-task properties used
are structural (source pool membership, category, detected language, prior use, and the
two manual exclusion lists established by reading the prompts).

    python scripts/select_final_tasks.py
"""
from __future__ import annotations

import os

import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0  # langdetect is nondeterministic unless seeded

BASE_SEED = 20260817
TARGET_TOTAL = 578
TARGET = {"mtbench": 78, "arena_hard": 250, "wildbench": 250}

OUT_MANIFEST = REPO / "data/prompts/final_tasks_seed20260817.json"
OUT_SUMMARY_DIR = REPO / "results/final_task_selection"

# Release note: this pilot artifact is not part of the code tree. Point at it with
# the SI_PILOT_FROZEN environment variable, or place the file at the repository-relative
# default below.
PILOT_FROZEN = Path(os.environ.get(
    "SI_PILOT_FROZEN", str(REPO / "data", "pilot", "frozen_olmo_answers.json")))
SCALED_SELECTION = REPO / "data/prompts/scaled_tasks_seed20260816.json"
WILDBENCH_SCREEN = REPO / "results/screen/wildbench/generation_records.jsonl"

# --- Manual exclusions: established by reading each prompt in full during the census. ---
# Not regex-derived; each id below was inspected and the defect confirmed by eye.
CORRUPTED_NOTATION = {
    "arena_hard": {
        "cc8aedd6a2bf493b": "corrupted training-data table: a perceptron class label "
                           "renders as '+\ufffd' instead of '+1'",
        "8ab68fda7bf04807": "mangled LaTeX/MathML throughout a Chinese competition string "
                           "problem; variable names replaced by U+FFFD",
        "02d2baed19ec450e": "mangled LaTeX/MathML throughout a Chinese competition math "
                           "problem; numerals replaced by U+FFFD",
    },
    "wildbench": {
        "33369d453616455d": "corrupted dynamical-systems notation; the recurrence is "
                           "unreadable (U+FFFD in place of every symbol)",
    },
}

# Confirmed near-duplicate pair (5-word-shingle Jaccard 0.879): the same 1000-word ethics
# essay prompt submitted twice, differing only in "a thousand words" vs "1000 words".
NEAR_DUPLICATE_PAIRS = {
    "wildbench": [("995b6bc63a1a4880", "b2fc10bfa5ee4646")],
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def detect_lang(text: str) -> str:
    try:
        return detect(text[:1000])
    except Exception:
        return "unknown"


def stratum_rng(*key_parts) -> random.Random:
    """Independent RNG per stratum, derived from the base seed and the stratum key, so
    adding or removing one stratum never perturbs another stratum's draw."""
    key = "|".join([str(BASE_SEED)] + [str(p) for p in key_parts])
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def largest_remainder(counts: dict, total: int) -> dict:
    """Hare-Niemeyer apportionment: floor the quotas, then hand out what's left to the
    largest fractional remainders. Ties break on the stratum key so it is deterministic."""
    pool_total = sum(counts.values())
    if pool_total == 0:
        return {k: 0 for k in counts}
    quotas = {k: total * c / pool_total for k, c in counts.items()}
    alloc = {k: int(q) for k, q in quotas.items()}
    remaining = total - sum(alloc.values())
    order = sorted(counts, key=lambda k: (-(quotas[k] - alloc[k]), str(k)))
    for k in order[:remaining]:
        alloc[k] += 1
    for k, a in alloc.items():
        assert a <= counts[k], f"stratum {k}: allocated {a} > available {counts[k]}"
    assert sum(alloc.values()) == total
    return alloc


# ============================================================
# Prior-use ledgers
# ============================================================

def mtbench_prior_use():
    used_phase1a = set(str(c["prompt_id"]) for c in
                       load_json(REPO / "data/candidates/phase1a_mtbench_20.json")["candidates"])
    used_pilot = set(a["prompt_id"] for a in load_json(PILOT_FROZEN)["accepted"])
    used_90 = set(t["task_id"] for t in
                  load_json(SCALED_SELECTION)["datasets"]["mtbench"]["selected"])
    return {"phase1a_screening": used_phase1a, "pilot_24task": used_pilot,
            "scaled_90task": used_90}


def arena_hard_prior_use():
    used_90 = set(t["task_id"] for t in
                  load_json(SCALED_SELECTION)["datasets"]["arena_hard"]["selected"])
    legacy = set(u["uid"] for u in
                 load_json(REPO / "data/prompts/arena_hard_v2_30_seed42.json"))
    return {"scaled_90task": used_90, "legacy_30task_pull": legacy}


def wildbench_prior_use():
    used_screen = load_jsonl_ids(WILDBENCH_SCREEN)
    used_90 = set(t["task_id"] for t in
                  load_json(SCALED_SELECTION)["datasets"]["wildbench"]["selected"])
    return {"screen_attempt_unfrozen": used_screen, "scaled_90task": used_90}


def prior_use_status(task_id: str, ledger: dict) -> tuple:
    phases = sorted(name for name, ids in ledger.items() if task_id in ids)
    return (bool(phases), phases)


def task_record(*, dataset, task_id, category, upstream_category, question, lang,
                previously_used, prior_use_phases, eligibility_decision, stratum,
                source_revision, source_file_sha256, extra=None):
    rec = {
        "dataset": dataset,
        "source_task_id": task_id,
        "category": category,
        "upstream_category": upstream_category,
        "question": question,
        "question_sha256": sha256_text(question),
        "question_chars": len(question),
        "detected_language": lang,
        "language_group": "english" if lang == "en" else "non_english",
        "previously_used": previously_used,
        "prior_use_phases": prior_use_phases,
        "eligibility_decision": eligibility_decision,
        "selection_stratum": stratum,
        "source_revision": source_revision,
        "source_file_sha256": source_file_sha256,
        "selection_seed": BASE_SEED,
    }
    if extra:
        rec.update(extra)
    return rec


# ============================================================
# Per-dataset selection
# ============================================================

def select_mtbench():
    pool = load_json(REPO / "data/prompts/mtbench_t1_pinned.json")
    ledger = mtbench_prior_use()
    rows = sorted(pool["prompts"], key=lambda r: int(r["prompt_id"]))

    selected = []
    for r in rows:
        used, phases = prior_use_status(r["prompt_id"], ledger)
        q = r["prompt"]
        selected.append(task_record(
            dataset="mtbench", task_id=r["prompt_id"], category=r["subcategory"],
            upstream_category=r["subcategory"], question=q, lang=detect_lang(q),
            previously_used=used, prior_use_phases=phases,
            eligibility_decision="structurally_eligible_included_census_complete",
            stratum="mtbench:all_eligible",
            source_revision=pool["source_revision"],
            source_file_sha256=pool["source_file_sha256"],
            extra={"n_turns_in_source": r.get("n_turns_in_source")},
        ))
    assert len(selected) == TARGET["mtbench"], f"mtbench: got {len(selected)}"

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/mtbench_t1_pinned.json",
        "n_source_total": pool["n_prompts"] + len(pool["excluded"]),
        "n_structurally_excluded": len(pool["excluded"]),
        "n_eligible": pool["n_prompts"],
        "selection_rule": ("census-complete: every structurally eligible first-turn task "
                          "is included, so no sampling and no seed is involved for this "
                          "dataset"),
        "proportion_basis": "n/a (census, not a sample)",
        "n_selected": len(selected),
        "selected": selected,
        "reserve": [],
    }


def select_arena_hard():
    pool = load_json(REPO / "data/prompts/arena_hard_v2_pinned_v2.json")
    ledger = arena_hard_prior_use()
    used_any = set().union(*ledger.values())
    corrupted = CORRUPTED_NOTATION["arena_hard"]

    frame = []
    for r in pool["prompts"]:
        tid = r["uid"]
        if tid in used_any or tid in corrupted:
            continue
        frame.append(r)
    frame.sort(key=lambda r: r["uid"])

    lang_of = {r["uid"]: detect_lang(r["prompt"]) for r in frame}

    by_cat = defaultdict(list)
    for r in frame:
        by_cat[r["subcategory"]].append(r)

    # Stage 1: 250 across the three categories.
    cat_counts = {c: len(v) for c, v in by_cat.items()}
    cat_alloc = largest_remainder(cat_counts, TARGET["arena_hard"])

    # Stage 2: within each category, across english / non_english.
    selected, reserve, stratum_report = [], [], {}
    for cat in sorted(by_cat):
        rows = by_cat[cat]
        groups = {"english": [], "non_english": []}
        for r in rows:
            key = "english" if lang_of[r["uid"]] == "en" else "non_english"
            groups[key].append(r)
        lang_counts = {k: len(v) for k, v in groups.items()}
        lang_alloc = largest_remainder(lang_counts, cat_alloc[cat])

        for lang_group in sorted(groups):
            candidates = sorted(groups[lang_group], key=lambda r: r["uid"])
            k = lang_alloc[lang_group]
            rng = stratum_rng("arena_hard", cat, lang_group)
            shuffled = candidates[:]
            rng.shuffle(shuffled)
            chosen, rest = shuffled[:k], shuffled[k:]
            stratum = f"arena_hard:{cat}:{lang_group}"
            stratum_report[stratum] = {
                "frame_size": len(candidates), "allocated": k,
            }
            for r in chosen + rest:
                used, phases = prior_use_status(r["uid"], ledger)
                rec = task_record(
                    dataset="arena_hard", task_id=r["uid"], category=r["subcategory"],
                    upstream_category=r.get("category"), question=r["prompt"],
                    lang=lang_of[r["uid"]], previously_used=used, prior_use_phases=phases,
                    eligibility_decision="structurally_eligible_unused_sampled",
                    stratum=stratum,
                    source_revision=pool["source_revision"],
                    source_file_sha256=pool["source_file_sha256"],
                )
                (selected if r in chosen else reserve).append(rec)

    assert len(selected) == TARGET["arena_hard"], f"arena_hard: got {len(selected)}"

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/arena_hard_v2_pinned_v2.json",
        "n_source_total": pool["n_prompts"] + len(pool["excluded"]),
        "n_structurally_excluded": len(pool["excluded"]),
        "n_eligible": pool["n_prompts"],
        "n_previously_used_excluded": len(used_any & set(r["uid"] for r in pool["prompts"])),
        "manual_exclusions": {"corrupted_notation": corrupted},
        "n_sampling_frame": len(frame),
        "selection_rule": ("two-stage proportional: 250 apportioned across "
                          "coding/creative_writing/math by largest remainder, then within "
                          "each category across english/non_english by largest remainder; "
                          "seeded shuffle within each terminal stratum"),
        "proportion_basis": "sampling frame (eligible-and-unused, post-manual-exclusion)",
        "category_allocation": cat_alloc,
        "stratum_allocation": stratum_report,
        "n_selected": len(selected),
        "selected": selected,
        "reserve": reserve,
    }


def select_wildbench():
    pool = load_json(REPO / "data/prompts/wildbench_v2_pinned.json")
    ledger = wildbench_prior_use()
    used_any = set().union(*ledger.values())
    corrupted = CORRUPTED_NOTATION["wildbench"]

    dedupe_dropped = {}
    for keep, drop in NEAR_DUPLICATE_PAIRS["wildbench"]:
        assert keep == min(keep, drop), "keep id must be the lexicographically smaller"
        dedupe_dropped[drop] = (f"near-duplicate of {keep} (5-word-shingle Jaccard 0.879); "
                               f"retained the lexicographically smaller id {keep}")

    frame = []
    for r in pool["prompts"]:
        tid = r["prompt_id"]
        if tid in used_any or tid in corrupted or tid in dedupe_dropped:
            continue
        frame.append(r)
    frame.sort(key=lambda r: r["prompt_id"])

    by_cat = defaultdict(list)
    for r in frame:
        by_cat[r["subcategory"]].append(r)

    cat_counts = {c: len(v) for c, v in by_cat.items()}
    cat_alloc = largest_remainder(cat_counts, TARGET["wildbench"])

    selected, reserve, stratum_report = [], [], {}
    for cat in sorted(by_cat):
        candidates = sorted(by_cat[cat], key=lambda r: r["prompt_id"])
        k = cat_alloc[cat]
        rng = stratum_rng("wildbench", cat)
        shuffled = candidates[:]
        rng.shuffle(shuffled)
        chosen, rest = shuffled[:k], shuffled[k:]
        stratum = f"wildbench:{cat}"
        stratum_report[stratum] = {"frame_size": len(candidates), "allocated": k}
        for r in chosen + rest:
            used, phases = prior_use_status(r["prompt_id"], ledger)
            q = r["prompt"]
            rec = task_record(
                dataset="wildbench", task_id=r["prompt_id"], category=r["subcategory"],
                upstream_category=r["subcategory"], question=q, lang=detect_lang(q),
                previously_used=used, prior_use_phases=phases,
                eligibility_decision="structurally_eligible_unused_sampled",
                stratum=stratum,
                source_revision=pool["source_revision"],
                source_file_sha256=pool["source_file_sha256"],
                extra={"secondary_tags": r.get("secondary_tags")},
            )
            (selected if r in chosen else reserve).append(rec)

    assert len(selected) == TARGET["wildbench"], f"wildbench: got {len(selected)}"

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/wildbench_v2_pinned.json",
        "n_source_total": pool["n_prompts"] + len(pool["excluded"]),
        "n_structurally_excluded": len(pool["excluded"]),
        "n_eligible": pool["n_prompts"],
        "n_previously_used_excluded": len(used_any & set(r["prompt_id"] for r in pool["prompts"])),
        "manual_exclusions": {"corrupted_notation": corrupted,
                             "near_duplicate_dropped": dedupe_dropped},
        "n_sampling_frame": len(frame),
        "selection_rule": ("proportional across the 11 categories by largest remainder; "
                          "seeded shuffle within each category"),
        "proportion_basis": "sampling frame (eligible-and-unused, post-manual-exclusion)",
        "category_allocation": cat_alloc,
        "stratum_allocation": stratum_report,
        "n_selected": len(selected),
        "selected": selected,
        "reserve": reserve,
    }


# ============================================================
# main
# ============================================================

def main() -> int:
    if OUT_MANIFEST.exists():
        raise SystemExit(f"refusing to overwrite an existing frozen manifest:\n"
                         f"  {OUT_MANIFEST}\ndelete it explicitly to regenerate.")

    datasets = {
        "mtbench": select_mtbench(),
        "arena_hard": select_arena_hard(),
        "wildbench": select_wildbench(),
    }

    all_selected = [t for d in datasets.values() for t in d["selected"]]

    manifest = {
        "experiment": "final_behavioral_study",
        "selection_seed": BASE_SEED,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_total": TARGET_TOTAL,
        "target_per_dataset": TARGET,
        "n_selected_total": len(all_selected),
        "selection_note": (
            "Frozen once, from prompt pools, prior-usage records, structural properties, "
            "and two manually-read exclusion lists only. No score, behavioral effect, "
            "answer quality, headroom, or any outcome-dependent quantity was consulted; "
            "no candidate answers exist for these tasks at selection time."),
        "language_detection": {
            "library": "langdetect", "detector_factory_seed": 0,
            "input": "first 1000 characters of the prompt",
            "note": ("Recorded per task in the manifest so the frozen value does not "
                    "depend on re-running the detector. Used only to form the "
                    "english/non_english stratum for Arena-Hard."),
        },
        "datasets": datasets,
    }

    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    # ---------------- validation ----------------
    log = print
    problems = []

    def check(label, ok, detail=""):
        log(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not ok:
            problems.append(label)

    log("=" * 92)
    log("VALIDATION")
    log("=" * 92)

    check("exactly 578 selected tasks", len(all_selected) == TARGET_TOTAL,
          f"got {len(all_selected)}")

    per_ds = Counter(t["dataset"] for t in all_selected)
    check("78 MT-Bench / 250 Arena-Hard / 250 WildBench",
          per_ds["mtbench"] == 78 and per_ds["arena_hard"] == 250 and per_ds["wildbench"] == 250,
          dict(per_ds))

    keys = [(t["dataset"], t["source_task_id"]) for t in all_selected]
    check("all selected task ids unique within dataset", len(keys) == len(set(keys)),
          f"{len(keys)} keys, {len(set(keys))} unique")

    global_ids = [t["source_task_id"] for t in all_selected]
    dup_global = [i for i, c in Counter(global_ids).items() if c > 1]
    check("no id collision across datasets", not dup_global, f"collisions: {dup_global}")

    q_hashes = [t["question_sha256"] for t in all_selected]
    dup_q = [h for h, c in Counter(q_hashes).items() if c > 1]
    check("no exact duplicate prompt text among selected", not dup_q,
          f"{len(dup_q)} duplicated prompt hashes")

    corrupted_all = set()
    for ds, m in CORRUPTED_NOTATION.items():
        corrupted_all |= set(m)
    sel_corrupt = [t["source_task_id"] for t in all_selected
                  if t["source_task_id"] in corrupted_all]
    check("no corrupted-notation task selected", not sel_corrupt, f"found {sel_corrupt}")

    dropped_dupes = {d for pairs in NEAR_DUPLICATE_PAIRS.values() for _, d in pairs}
    sel_dropped = [t["source_task_id"] for t in all_selected
                  if t["source_task_id"] in dropped_dupes]
    check("dropped near-duplicate member not selected", not sel_dropped,
          f"found {sel_dropped}")
    kept_dupes = {k for pairs in NEAR_DUPLICATE_PAIRS.values() for k, _ in pairs}
    n_kept = sum(1 for t in all_selected if t["source_task_id"] in kept_dupes)
    check("at most one member of each near-duplicate pair present", n_kept <= 1,
          f"{n_kept} of the pair present (retained id may or may not be drawn)")

    ah_used = [t["source_task_id"] for t in datasets["arena_hard"]["selected"]
              if t["previously_used"]]
    wb_used = [t["source_task_id"] for t in datasets["wildbench"]["selected"]
              if t["previously_used"]]
    check("no previously-used task in the Arena-Hard draw", not ah_used, f"{len(ah_used)}")
    check("no previously-used task in the WildBench draw", not wb_used, f"{len(wb_used)}")

    for name, d in datasets.items():
        sel_ids = set(t["source_task_id"] for t in d["selected"])
        res_ids = set(t["source_task_id"] for t in d["reserve"])
        check(f"{name}: selected and reserve disjoint", not (sel_ids & res_ids),
              f"overlap {len(sel_ids & res_ids)}")

    for t in all_selected:
        if sha256_text(t["question"]) != t["question_sha256"]:
            problems.append(f"hash mismatch {t['source_task_id']}")
    check("every question_sha256 matches its prompt text",
          not any(p.startswith("hash mismatch") for p in problems))

    # ---------------- report ----------------
    log("")
    log("=" * 92)
    log("COMPOSITION")
    log("=" * 92)
    n_prev = sum(1 for t in all_selected if t["previously_used"])
    n_held = len(all_selected) - n_prev
    log(f"previously used (any earlier phase) : {n_prev}")
    log(f"fully held-out (never used)          : {n_held}")
    log("")
    for name, d in datasets.items():
        sel = d["selected"]
        prev = sum(1 for t in sel if t["previously_used"])
        log(f"{name}: {len(sel)} selected  ({prev} previously used, {len(sel)-prev} held out)"
           f"  frame={d.get('n_sampling_frame', 'n/a')}  reserve={len(d['reserve'])}")
        log(f"   source: {d['source_repo']} @ {d['source_revision'][:12]}  "
           f"file sha256 {d['source_file_sha256'][:16]}")
        log(f"   categories: {dict(sorted(Counter(t['category'] for t in sel).items()))}")
        langs = Counter(t["detected_language"] for t in sel)
        groups = Counter(t["language_group"] for t in sel)
        log(f"   language groups: {dict(sorted(groups.items()))}")
        log(f"   detected languages: {dict(langs.most_common(12))}"
           + (" ..." if len(langs) > 12 else ""))
        if name == "mtbench":
            phases = Counter()
            for t in sel:
                if t["prior_use_phases"]:
                    phases["+".join(t["prior_use_phases"])] += 1
                else:
                    phases["never_used"] += 1
            log(f"   prior-use detail: {dict(sorted(phases.items()))}")

    log("")
    log("=" * 92)
    log("PROPORTION FIDELITY (frame share -> selected share)")
    log("=" * 92)
    for name in ("arena_hard", "wildbench"):
        d = datasets[name]
        frame_rows = d["selected"] + d["reserve"]
        fc = Counter(t["category"] for t in frame_rows)
        sc = Counter(t["category"] for t in d["selected"])
        ftot, stot = sum(fc.values()), sum(sc.values())
        log(f"{name}:")
        for cat in sorted(fc):
            log(f"   {cat:22} frame {fc[cat]:4} ({100*fc[cat]/ftot:5.2f}%)   "
               f"selected {sc[cat]:4} ({100*sc[cat]/stot:5.2f}%)")
        if name == "arena_hard":
            for cat in sorted(fc):
                fg = Counter(t["language_group"] for t in frame_rows if t["category"] == cat)
                sg = Counter(t["language_group"] for t in d["selected"] if t["category"] == cat)
                ft, st = sum(fg.values()), sum(sg.values())
                log(f"   {cat} EN/non-EN: frame "
                   f"{100*fg['english']/ft:5.2f}% EN   selected {100*sg['english']/st:5.2f}% EN")

    summary = {
        "n_selected_total": len(all_selected),
        "per_dataset": {k: v["n_selected"] for k, v in datasets.items()},
        "n_previously_used": n_prev, "n_held_out": n_held,
        "validation_problems": problems,
        "validation_passed": not problems,
        "sources": {k: {"repo": v["source_repo"], "revision": v["source_revision"],
                       "file_sha256": v["source_file_sha256"], "pool_file": v["pool_file"],
                       "n_source_total": v["n_source_total"],
                       "n_eligible": v["n_eligible"],
                       "n_sampling_frame": v.get("n_sampling_frame")}
                   for k, v in datasets.items()},
        "categories_selected": {k: dict(sorted(Counter(
            t["category"] for t in v["selected"]).items())) for k, v in datasets.items()},
        "language_groups_selected": {k: dict(sorted(Counter(
            t["language_group"] for t in v["selected"]).items()))
            for k, v in datasets.items()},
        "detected_languages_selected": {k: dict(Counter(
            t["detected_language"] for t in v["selected"]).most_common())
            for k, v in datasets.items()},
    }
    OUT_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_SUMMARY_DIR / "final_selection_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    manifest_sha = hashlib.sha256(OUT_MANIFEST.read_bytes()).hexdigest()
    log("")
    log(f"[save] {OUT_MANIFEST}")
    log(f"       manifest sha256 {manifest_sha}")
    log(f"[save] {OUT_SUMMARY_DIR / 'final_selection_summary.json'}")
    log("")
    log("RESULT: " + ("ALL VALIDATIONS PASSED" if not problems else f"FAILURES: {problems}"))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
