#!/usr/bin/env python3
"""Freeze the version-2, English-only 578-task selection for the final confirmatory study.

Prospective scope decision: no model output exists for any task in either manifest version,
so restricting to English-language tasks is a design choice made before any observation, not
an outcome-based exclusion. Version 1 (the multilingual manifest,
data/prompts/final_tasks_seed20260817.json, sha256 b3e3f49d...3475ea9) is left untouched and
is recorded inside this manifest as the superseded predecessor.

Composition, unchanged in size from v1:
  MT-Bench   : all 78 structurally eligible first-turn tasks, each confirmed substantively
               English, previous-use status marked per task.
  Arena-Hard : 250 from the eligible-and-unused ENGLISH pool, minus the 3 corrupted-notation
               tasks carried over from v1. Proportional across coding / creative_writing /
               math. No language sub-stratum is needed now that the frame is English-only.
  WildBench  : 250 from the eligible-and-unused ENGLISH pool, minus the 1 corrupted-notation
               task and minus the near-duplicate member dropped in v1 (the lexicographically
               larger id). Proportional across the 11 categories.

"Substantively English" is decided by silent_influence.english_assessment (multi-signal:
Unicode script profile on the full text, function-word counts on code-stripped prose,
Vietnamese diacritic count, langdetect as advisory only) with every ambiguous or
detector-disagreeing case hand-read and recorded in silent_influence.language_decisions.
Short-text language detection is never trusted on its own, and a task is never excluded for
being code-heavy or notation-heavy: a prompt with little prose and no positive evidence of
another language counts as English.

Proportions are computed from each dataset's own English sampling frame, so every stratum
quota is satisfiable. Because non-English tasks are concentrated in Arena-Hard's
creative_writing and math categories, the English-only frame has a materially different
category mix than v1's multilingual frame; that shift is reported, not smoothed over.

    python scripts/select_final_tasks_v2_english.py
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

from silent_influence import english_assessment as ea
from silent_influence.language_decisions import MANUAL_LANGUAGE_DECISIONS

DetectorFactory.seed = 0

BASE_SEED = 20260817
TARGET_TOTAL = 578
TARGET = {"mtbench": 78, "arena_hard": 250, "wildbench": 250}

V1_MANIFEST = REPO / "data/prompts/final_tasks_seed20260817.json"
OUT_MANIFEST = REPO / "data/prompts/final_tasks_v2_english_seed20260817.json"
OUT_SUMMARY_DIR = REPO / "results/final_task_selection"

# Release note: this pilot artifact is not part of the code tree. Point at it with
# the SI_PILOT_FROZEN environment variable, or place the file at the repository-relative
# default below.
PILOT_FROZEN = Path(os.environ.get(
    "SI_PILOT_FROZEN", str(REPO / "data", "pilot", "frozen_olmo_answers.json")))
SCALED_SELECTION = REPO / "data/prompts/scaled_tasks_seed20260816.json"
WILDBENCH_SCREEN = REPO / "results/screen/wildbench/generation_records.jsonl"

# Carried over verbatim from v1 -- established by reading each prompt during the census.
CORRUPTED_NOTATION = {
    "arena_hard": {
        "cc8aedd6a2bf493b": "corrupted training-data table: a perceptron class label renders "
                           "as '+\ufffd' instead of '+1'",
        "8ab68fda7bf04807": "mangled LaTeX/MathML in a Chinese competition string problem",
        "02d2baed19ec450e": "mangled LaTeX/MathML in a Chinese competition math problem",
    },
    "wildbench": {
        "33369d453616455d": "corrupted dynamical-systems notation; recurrence unreadable",
    },
}
NEAR_DUPLICATE_PAIRS = {"wildbench": [("995b6bc63a1a4880", "b2fc10bfa5ee4646")]}


def sha256_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl_ids(p, field="prompt_id"):
    out = set()
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.add(str(json.loads(line)[field]))
    return out


def detect_lang(text: str) -> str:
    try:
        return detect(text[:1000])
    except Exception:
        return "unknown"


def stratum_rng(*parts) -> random.Random:
    key = "|".join([str(BASE_SEED)] + [str(p) for p in parts])
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def largest_remainder(counts: dict, total: int) -> dict:
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


# ============================================================
# Language determination
# ============================================================

def english_verdict(task_id: str, text: str) -> dict:
    """Returns the decision plus the full evidence trail for the manifest."""
    ld = detect_lang(text)
    a = ea.assess(text, ld)
    manual = MANUAL_LANGUAGE_DECISIONS.get(task_id)
    if manual:
        verdict, evidence = manual
        return {"is_english": verdict == "english",
                "language_verdict": verdict,
                "decided_by": "manual_review",
                "evidence": evidence,
                "automated_verdict": a.verdict,
                "automated_reason": a.reason,
                "langdetect_label": ld,
                "signals": a.as_dict()}
    # A needs_review verdict must never resolve itself. Without this guard an ambiguous task
    # would fall through to is_english=False and be excluded with no human ever reading it --
    # exactly the blind-detection failure this whole module exists to avoid. Fail loudly so
    # the case gets adjudicated and recorded in language_decisions.py instead.
    if a.verdict == "needs_review":
        raise SystemExit(
            f"task {task_id} needs human adjudication and has no entry in "
            f"language_decisions.MANUAL_LANGUAGE_DECISIONS.\n"
            f"  automated reason: {a.reason}\n"
            f"  langdetect: {ld}\n"
            f"Read the prompt and add an explicit (verdict, evidence) entry before selecting.")

    is_en = a.verdict in ("english", "english_low_prose")
    return {"is_english": is_en,
            "language_verdict": "english" if is_en else "non_english",
            "decided_by": "automated_" + a.verdict,
            "evidence": a.reason,
            "automated_verdict": a.verdict,
            "automated_reason": a.reason,
            "langdetect_label": ld,
            "signals": a.as_dict()}


def prior_use(task_id: str, ledger: dict):
    phases = sorted(n for n, ids in ledger.items() if task_id in ids)
    return bool(phases), phases


def record(*, dataset, task_id, category, upstream_category, question, lang_info,
           previously_used, prior_use_phases, eligibility_decision, stratum,
           source_revision, source_file_sha256, extra=None):
    r = {
        "dataset": dataset,
        "source_task_id": task_id,
        "category": category,
        "upstream_category": upstream_category,
        "question": question,
        "question_sha256": sha256_text(question),
        "question_chars": len(question),
        "language_verdict": lang_info["language_verdict"],
        "language_decided_by": lang_info["decided_by"],
        "language_evidence": lang_info["evidence"],
        "langdetect_label": lang_info["langdetect_label"],
        "language_signals": lang_info["signals"],
        "previously_used": previously_used,
        "prior_use_phases": prior_use_phases,
        "eligibility_decision": eligibility_decision,
        "selection_stratum": stratum,
        "source_revision": source_revision,
        "source_file_sha256": source_file_sha256,
        "selection_seed": BASE_SEED,
    }
    if extra:
        r.update(extra)
    return r


# ============================================================
# Per-dataset selection
# ============================================================

def select_mtbench():
    pool = load_json(REPO / "data/prompts/mtbench_t1_pinned.json")
    ledger = {
        "phase1a_screening": set(str(c["prompt_id"]) for c in
                                 load_json(REPO / "data/candidates/phase1a_mtbench_20.json")["candidates"]),
        "pilot_24task": set(a["prompt_id"] for a in load_json(PILOT_FROZEN)["accepted"]),
        "scaled_90task": set(t["task_id"] for t in
                             load_json(SCALED_SELECTION)["datasets"]["mtbench"]["selected"]),
    }
    rows = sorted(pool["prompts"], key=lambda r: int(r["prompt_id"]))

    selected, non_english = [], []
    for r in rows:
        li = english_verdict(r["prompt_id"], r["prompt"])
        if not li["is_english"]:
            non_english.append({"task_id": r["prompt_id"], "evidence": li["evidence"]})
            continue
        used, phases = prior_use(r["prompt_id"], ledger)
        selected.append(record(
            dataset="mtbench", task_id=r["prompt_id"], category=r["subcategory"],
            upstream_category=r["subcategory"], question=r["prompt"], lang_info=li,
            previously_used=used, prior_use_phases=phases,
            eligibility_decision="structurally_eligible_english_confirmed_census_complete",
            stratum="mtbench:all_eligible_english",
            source_revision=pool["source_revision"],
            source_file_sha256=pool["source_file_sha256"],
            extra={"n_turns_in_source": r.get("n_turns_in_source")}))

    assert not non_english, (f"MT-Bench: {len(non_english)} task(s) failed the English check, "
                             f"so all 78 cannot be included: {non_english}")
    assert len(selected) == TARGET["mtbench"]

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/mtbench_t1_pinned.json",
        "n_source_total": pool["n_prompts"] + len(pool["excluded"]),
        "n_structurally_excluded": len(pool["excluded"]),
        "n_eligible": pool["n_prompts"],
        "n_english_frame": len(selected),
        "n_excluded_non_english": len(non_english),
        "selection_rule": "census-complete: all 78 structurally eligible tasks, each "
                          "confirmed substantively English; no sampling, no seed used",
        "n_selected": len(selected), "selected": selected, "reserve": [],
        "exclusions": {"non_english": non_english},
    }


def select_arena_hard():
    pool = load_json(REPO / "data/prompts/arena_hard_v2_pinned_v2.json")
    ledger = {
        "scaled_90task": set(t["task_id"] for t in
                             load_json(SCALED_SELECTION)["datasets"]["arena_hard"]["selected"]),
        "legacy_30task_pull": set(u["uid"] for u in
                                  load_json(REPO / "data/prompts/arena_hard_v2_30_seed42.json")),
    }
    used_any = set().union(*ledger.values())
    corrupted = CORRUPTED_NOTATION["arena_hard"]

    n_used_in_pool = 0
    frame, excl_non_en = [], []
    for r in pool["prompts"]:
        tid = r["uid"]
        if tid in used_any:
            n_used_in_pool += 1
            continue
        if tid in corrupted:
            continue
        li = english_verdict(tid, r["prompt"])
        if not li["is_english"]:
            excl_non_en.append({"task_id": tid, "category": r["subcategory"],
                                "evidence": li["evidence"]})
            continue
        frame.append((r, li))
    frame.sort(key=lambda x: x[0]["uid"])

    by_cat = defaultdict(list)
    for r, li in frame:
        by_cat[r["subcategory"]].append((r, li))
    alloc = largest_remainder({c: len(v) for c, v in by_cat.items()}, TARGET["arena_hard"])

    selected, reserve, strata = [], [], {}
    for cat in sorted(by_cat):
        cands = sorted(by_cat[cat], key=lambda x: x[0]["uid"])
        rng = stratum_rng("arena_hard", cat)
        shuffled = cands[:]
        rng.shuffle(shuffled)
        k = alloc[cat]
        chosen_ids = set(r["uid"] for r, _ in shuffled[:k])
        strata[f"arena_hard:{cat}"] = {"frame_size": len(cands), "allocated": k}
        for r, li in shuffled:
            used, phases = prior_use(r["uid"], ledger)
            rec = record(dataset="arena_hard", task_id=r["uid"], category=r["subcategory"],
                         upstream_category=r.get("category"), question=r["prompt"],
                         lang_info=li, previously_used=used, prior_use_phases=phases,
                         eligibility_decision="structurally_eligible_unused_english_sampled",
                         stratum=f"arena_hard:{cat}",
                         source_revision=pool["source_revision"],
                         source_file_sha256=pool["source_file_sha256"])
            (selected if r["uid"] in chosen_ids else reserve).append(rec)

    assert len(selected) == TARGET["arena_hard"], f"arena_hard got {len(selected)}"

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/arena_hard_v2_pinned_v2.json",
        "n_source_total": pool["n_prompts"] + len(pool["excluded"]),
        "n_structurally_excluded": len(pool["excluded"]),
        "n_eligible": pool["n_prompts"],
        "n_previously_used_excluded": n_used_in_pool,
        "n_corrupted_excluded": len(corrupted),
        "n_excluded_non_english": len(excl_non_en),
        "n_english_frame": len(frame),
        "selection_rule": "proportional across coding/creative_writing/math by largest "
                          "remainder over the English frame; seeded shuffle within category",
        "proportion_basis": "English sampling frame (eligible, unused, non-corrupted, English)",
        "category_allocation": alloc, "stratum_allocation": strata,
        "n_selected": len(selected), "selected": selected, "reserve": reserve,
        "exclusions": {"corrupted_notation": corrupted,
                       "non_english": excl_non_en},
    }


def select_wildbench():
    pool = load_json(REPO / "data/prompts/wildbench_v2_pinned.json")
    ledger = {"screen_attempt_unfrozen": load_jsonl_ids(WILDBENCH_SCREEN),
              "scaled_90task": set(t["task_id"] for t in
                                   load_json(SCALED_SELECTION)["datasets"]["wildbench"]["selected"])}
    used_any = set().union(*ledger.values())
    corrupted = CORRUPTED_NOTATION["wildbench"]
    dedupe = {}
    for keep, drop in NEAR_DUPLICATE_PAIRS["wildbench"]:
        assert keep == min(keep, drop)
        dedupe[drop] = (f"near-duplicate of {keep} (5-word-shingle Jaccard 0.879); retained "
                        f"the lexicographically smaller id {keep}")

    n_used_in_pool = 0
    frame, excl_non_en = [], []
    for r in pool["prompts"]:
        tid = r["prompt_id"]
        if tid in used_any:
            n_used_in_pool += 1
            continue
        if tid in corrupted or tid in dedupe:
            continue
        li = english_verdict(tid, r["prompt"])
        if not li["is_english"]:
            excl_non_en.append({"task_id": tid, "category": r["subcategory"],
                                "evidence": li["evidence"]})
            continue
        frame.append((r, li))
    frame.sort(key=lambda x: x[0]["prompt_id"])

    by_cat = defaultdict(list)
    for r, li in frame:
        by_cat[r["subcategory"]].append((r, li))
    alloc = largest_remainder({c: len(v) for c, v in by_cat.items()}, TARGET["wildbench"])

    selected, reserve, strata = [], [], {}
    for cat in sorted(by_cat):
        cands = sorted(by_cat[cat], key=lambda x: x[0]["prompt_id"])
        rng = stratum_rng("wildbench", cat)
        shuffled = cands[:]
        rng.shuffle(shuffled)
        k = alloc[cat]
        chosen = shuffled[:k]
        chosen_ids = set(r["prompt_id"] for r, _ in chosen)
        strata[f"wildbench:{cat}"] = {"frame_size": len(cands), "allocated": k}
        for r, li in shuffled:
            used, phases = prior_use(r["prompt_id"], ledger)
            rec = record(dataset="wildbench", task_id=r["prompt_id"], category=r["subcategory"],
                         upstream_category=r["subcategory"], question=r["prompt"],
                         lang_info=li, previously_used=used, prior_use_phases=phases,
                         eligibility_decision="structurally_eligible_unused_english_sampled",
                         stratum=f"wildbench:{cat}",
                         source_revision=pool["source_revision"],
                         source_file_sha256=pool["source_file_sha256"],
                         extra={"secondary_tags": r.get("secondary_tags")})
            (selected if r["prompt_id"] in chosen_ids else reserve).append(rec)

    assert len(selected) == TARGET["wildbench"], f"wildbench got {len(selected)}"

    return {
        "source_repo": pool["source_repo"], "source_revision": pool["source_revision"],
        "source_file_sha256": pool["source_file_sha256"],
        "pool_file": "data/prompts/wildbench_v2_pinned.json",
        "n_source_total": pool["n_prompts"] + len(pool["excluded"]),
        "n_structurally_excluded": len(pool["excluded"]),
        "n_eligible": pool["n_prompts"],
        "n_previously_used_excluded": n_used_in_pool,
        "n_corrupted_excluded": len(corrupted),
        "n_near_duplicate_excluded": len(dedupe),
        "n_excluded_non_english": len(excl_non_en),
        "n_english_frame": len(frame),
        "selection_rule": "proportional across the 11 categories by largest remainder over "
                          "the English frame; seeded shuffle within category",
        "proportion_basis": "English sampling frame (eligible, unused, non-corrupted, "
                            "de-duplicated, English)",
        "category_allocation": alloc, "stratum_allocation": strata,
        "n_selected": len(selected), "selected": selected, "reserve": reserve,
        "exclusions": {"corrupted_notation": corrupted, "near_duplicate_dropped": dedupe,
                       "non_english": excl_non_en},
    }


def main() -> int:
    if OUT_MANIFEST.exists():
        raise SystemExit(f"refusing to overwrite an existing frozen manifest:\n  {OUT_MANIFEST}")
    assert V1_MANIFEST.exists(), "v1 manifest must remain present and untouched"
    v1_hash = sha256_file(V1_MANIFEST)

    datasets = {"mtbench": select_mtbench(), "arena_hard": select_arena_hard(),
                "wildbench": select_wildbench()}
    all_sel = [t for d in datasets.values() for t in d["selected"]]

    manifest = {
        "experiment": "final_behavioral_study",
        "manifest_version": 2,
        "scope": "english_language_tasks_only",
        "scope_rationale": ("Prospective scope decision taken before any model output existed "
                            "for any task in either manifest version; not an outcome-based "
                            "exclusion."),
        "supersedes": {"version": 1, "path": str(V1_MANIFEST.relative_to(REPO)),
                       "sha256": v1_hash,
                       "note": "preserved unmodified; multilingual"},
        "selection_seed": BASE_SEED,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target_total": TARGET_TOTAL, "target_per_dataset": TARGET,
        "n_selected_total": len(all_sel),
        "english_determination": {
            "module": "silent_influence.english_assessment",
            "manual_decisions_module": "silent_influence.language_decisions",
            "method": ("multi-signal: Unicode script profile over the full text; function-word "
                       "counts for English and 11 other Latin-script languages over "
                       "code/notation-stripped prose; Vietnamese diacritic count; langdetect "
                       "recorded as advisory only and never decisive"),
            "code_heavy_policy": ("a prompt with little prose after stripping code and notation "
                                  "is English-compatible unless it carries positive evidence of "
                                  "another language; code-heavy and symbol-heavy tasks are NOT "
                                  "excluded for containing code or notation"),
            "adjudication_rule": "the language of the task instruction governs",
            "n_hand_adjudicated": len(MANUAL_LANGUAGE_DECISIONS),
        },
        "note": ("No score, behavioural effect, answer quality, headroom, or any other "
                 "outcome-dependent quantity was consulted; no candidate answers exist for "
                 "these tasks."),
        "datasets": datasets,
    }
    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    # ---------------- validation ----------------
    problems = []

    def check(label, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))
        if not ok:
            problems.append(label)

    print("=" * 94)
    print("VALIDATION")
    print("=" * 94)
    check("exactly 578 selected", len(all_sel) == TARGET_TOTAL, f"got {len(all_sel)}")
    per = Counter(t["dataset"] for t in all_sel)
    check("78 MT-Bench / 250 Arena-Hard / 250 WildBench",
          per["mtbench"] == 78 and per["arena_hard"] == 250 and per["wildbench"] == 250, dict(per))
    keys = [(t["dataset"], t["source_task_id"]) for t in all_sel]
    check("unique (dataset, id) keys", len(keys) == len(set(keys)),
          f"{len(keys)} / {len(set(keys))} unique")
    check("no cross-dataset id collision",
          len(set(t["source_task_id"] for t in all_sel)) == len(all_sel))
    qh = [t["question_sha256"] for t in all_sel]
    check("no duplicate prompt text", len(set(qh)) == len(qh))
    check("every selected task is verdict=english",
          all(t["language_verdict"] == "english" for t in all_sel),
          f"{sum(1 for t in all_sel if t['language_verdict'] != 'english')} violations")
    corrupt_all = {k for m in CORRUPTED_NOTATION.values() for k in m}
    check("no corrupted task selected",
          not (set(t["source_task_id"] for t in all_sel) & corrupt_all))
    dropped = {d for pairs in NEAR_DUPLICATE_PAIRS.values() for _, d in pairs}
    check("dropped near-duplicate absent",
          not (set(t["source_task_id"] for t in all_sel) & dropped))
    check("no previously-used task in Arena-Hard draw",
          not any(t["previously_used"] for t in datasets["arena_hard"]["selected"]))
    check("no previously-used task in WildBench draw",
          not any(t["previously_used"] for t in datasets["wildbench"]["selected"]))
    check("every question_sha256 matches its text",
          all(sha256_text(t["question"]) == t["question_sha256"] for t in all_sel))
    check("v1 manifest still present and unmodified",
          V1_MANIFEST.exists() and sha256_file(V1_MANIFEST) == v1_hash, f"sha256 {v1_hash[:16]}")
    for name, d in datasets.items():
        s = set(t["source_task_id"] for t in d["selected"])
        r = set(t["source_task_id"] for t in d["reserve"])
        check(f"{name}: selected/reserve disjoint", not (s & r), f"overlap {len(s & r)}")

    # ---------------- report ----------------
    print()
    print("=" * 94)
    print("ENGLISH-ONLY SAMPLING FRAMES")
    print("=" * 94)
    for name, d in datasets.items():
        print(f"{name}:")
        print(f"   source total {d['n_source_total']} -> structurally eligible {d['n_eligible']}"
              f" (structural exclusions {d['n_structurally_excluded']})")
        bits = []
        if d.get("n_previously_used_excluded"):
            bits.append(f"previously used -{d['n_previously_used_excluded']}")
        if d.get("n_corrupted_excluded"):
            bits.append(f"corrupted -{d['n_corrupted_excluded']}")
        if d.get("n_near_duplicate_excluded"):
            bits.append(f"near-duplicate -{d['n_near_duplicate_excluded']}")
        bits.append(f"non-English -{d['n_excluded_non_english']}")
        print(f"   {'; '.join(bits)}  =>  English frame {d['n_english_frame']}"
              f"  =>  selected {d['n_selected']}  (reserve {len(d['reserve'])})")

    print()
    print("=" * 94)
    print("COMPOSITION")
    print("=" * 94)
    n_prev = sum(1 for t in all_sel if t["previously_used"])
    print(f"previously used : {n_prev}")
    print(f"fully held out  : {len(all_sel) - n_prev}")
    for name, d in datasets.items():
        sel = d["selected"]
        p = sum(1 for t in sel if t["previously_used"])
        print(f"\n{name}: {len(sel)} selected ({p} previously used, {len(sel)-p} held out)")
        print(f"   source {d['source_repo']} @ {d['source_revision'][:12]} "
              f"file sha256 {d['source_file_sha256'][:16]}")
        print(f"   categories: {dict(sorted(Counter(t['category'] for t in sel).items()))}")
        print(f"   langdetect labels among selected (advisory only): "
              f"{dict(Counter(t['langdetect_label'] for t in sel).most_common(8))}")
        print(f"   language decided by: "
              f"{dict(Counter(t['language_decided_by'] for t in sel).most_common())}")
        if name == "mtbench":
            ph = Counter("+".join(t["prior_use_phases"]) if t["prior_use_phases"] else "never_used"
                         for t in sel)
            print(f"   prior-use detail: {dict(sorted(ph.items()))}")

    print()
    print("=" * 94)
    print("PROPORTION FIDELITY (English frame share -> selected share)")
    print("=" * 94)
    for name in ("arena_hard", "wildbench"):
        d = datasets[name]
        fr = d["selected"] + d["reserve"]
        fc, sc = Counter(t["category"] for t in fr), Counter(t["category"] for t in d["selected"])
        ft, st = sum(fc.values()), sum(sc.values())
        print(f"{name}:")
        for c in sorted(fc):
            print(f"   {c:22} frame {fc[c]:4} ({100*fc[c]/ft:5.2f}%)   "
                  f"selected {sc[c]:4} ({100*sc[c]/st:5.2f}%)")

    print()
    print("=" * 94)
    print("v1 -> v2 CATEGORY MIX SHIFT (English-only restriction)")
    print("=" * 94)
    v1 = load_json(V1_MANIFEST)
    for name in ("arena_hard", "wildbench"):
        a = Counter(t["category"] for t in v1["datasets"][name]["selected"])
        b = Counter(t["category"] for t in datasets[name]["selected"])
        print(f"{name}:")
        for c in sorted(set(a) | set(b)):
            print(f"   {c:22} v1 {a.get(c,0):4}  ->  v2 {b.get(c,0):4}")

    summary = {
        "manifest_version": 2, "scope": "english_only",
        "supersedes_v1_sha256": v1_hash,
        "n_selected_total": len(all_sel),
        "per_dataset": {k: v["n_selected"] for k, v in datasets.items()},
        "n_previously_used": n_prev, "n_held_out": len(all_sel) - n_prev,
        "english_frames": {k: v["n_english_frame"] for k, v in datasets.items()},
        "exclusion_counts": {
            k: {"structural": v["n_structurally_excluded"],
                "previously_used": v.get("n_previously_used_excluded", 0),
                "corrupted": v.get("n_corrupted_excluded", 0),
                "near_duplicate": v.get("n_near_duplicate_excluded", 0),
                "non_english": v["n_excluded_non_english"]}
            for k, v in datasets.items()},
        "categories_selected": {k: dict(sorted(Counter(t["category"] for t in v["selected"]).items()))
                                for k, v in datasets.items()},
        "validation_problems": problems, "validation_passed": not problems,
        "sources": {k: {"repo": v["source_repo"], "revision": v["source_revision"],
                        "file_sha256": v["source_file_sha256"]} for k, v in datasets.items()},
    }
    OUT_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_SUMMARY_DIR / "final_selection_v2_english_summary.json", "w",
              encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print()
    print(f"[save] {OUT_MANIFEST}")
    print(f"       v2 manifest sha256 {sha256_file(OUT_MANIFEST)}")
    print(f"[save] {OUT_SUMMARY_DIR / 'final_selection_v2_english_summary.json'}")
    print()
    print("RESULT: " + ("ALL VALIDATIONS PASSED" if not problems else f"FAILURES: {problems}"))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
