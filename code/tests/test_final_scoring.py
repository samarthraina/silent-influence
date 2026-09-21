"""Integration tests for scripts/run_final_scoring.py: unit identity, checkpoint/resume
with synthetic records, and the batching-verdict-driven automatic fallback to batch size 1.
No GPU, no weights -- uses the --stub path throughout."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import run_final_scoring as rfs
from silent_influence import scaled_conditions as sc


def _write_candidates(path, n_per_dataset=1):
    accepted = []
    for ds in ("mtbench", "arena_hard", "wildbench"):
        for i in range(n_per_dataset):
            accepted.append({
                "dataset": ds, "source_task_id": f"{ds}_t{i}", "category": "cat",
                "question": f"Question {ds} {i}?", "question_sha256": "x",
                "previously_used": False, "prior_use_phases": [],
                "answer": f"Answer {ds} {i}.", "answer_sha256": "y",
                "output_tokens": 10, "hit_token_cap": False, "generation_seconds": 0.1,
                "generator_model": "olmo", "generator_revision": "r",
            })
    path.write_text(json.dumps({"accepted": accepted}), encoding="utf-8")
    return accepted


def _selection_for(candidates_file, tmp_path):
    """A9 restricts scoring to a frozen 234-task set. Tests use synthetic tasks, so they supply
    their own selection covering exactly those tasks (with --skip-hash-check)."""
    cands = json.loads(Path(candidates_file).read_text(encoding="utf-8"))["accepted"]
    by_ds = {}
    for c in cands:
        by_ds.setdefault(c["dataset"], []).append(c["source_task_id"])
    sel = {"datasets": {ds: {"selected": sorted(ids)} for ds, ids in by_ds.items()}}
    p = Path(tmp_path) / "a9_selection.json"
    p.write_text(json.dumps(sel), encoding="utf-8")
    return str(p)


def _run(monkeypatch, argv):
    if "--task-selection" not in argv:
        cf = argv[argv.index("--candidates-file") + 1] if "--candidates-file" in argv else None
        out = argv[argv.index("--out") + 1] if "--out" in argv else None
        if cf and out:
            argv = argv + ["--task-selection", _selection_for(cf, Path(out).parent),
                           "--skip-hash-check"]
    monkeypatch.setattr(sys, "argv", ["run_final_scoring.py"] + argv)
    return rfs.main()


def test_effective_batch_size_defaults_to_one_with_no_verdict_file():
    assert rfs.effective_batch_size("llama", requested=8, verdict={}) == 1


def test_effective_batch_size_forced_to_one_on_failed_verdict():
    verdict = {"llama": {"passed": False}}
    assert rfs.effective_batch_size("llama", requested=8, verdict=verdict) == 1


def test_effective_batch_size_honors_a_complete_passing_verdict():
    """A verdict must carry every gate field explicitly, not just the rolled-up
    "passed" flag -- see tests/test_a2_audit_fixes.py D1 for why a bare
    {"passed": True} is deliberately no longer sufficient."""
    verdict = {"llama": {"passed": True, "token_equivalence_passed": True,
                        "memory_preflight_required": False,
                        "memory_preflight_passed": True, "stub": False}}
    assert rfs.effective_batch_size("llama", requested=8, verdict=verdict) == 8


def test_effective_batch_size_rejects_a_bare_passed_flag():
    """Guards the D1 fix: the rolled-up flag alone is not evidence the gates ran."""
    assert rfs.effective_batch_size("llama", requested=8,
                                    verdict={"llama": {"passed": True}}) == 1


def test_effective_batch_size_never_below_one_even_if_requested_zero():
    assert rfs.effective_batch_size("llama", requested=0, verdict={}) == 1


def test_unit_id_is_stable_and_scorer_condition_sensitive():
    a = rfs.unit_id("llama", "arena_hard", "t1", "no_history")
    b = rfs.unit_id("llama", "arena_hard", "t1", "self_low_2")
    c = rfs.unit_id("qwen", "arena_hard", "t1", "no_history")
    assert a != b != c
    assert a == rfs.unit_id("llama", "arena_hard", "t1", "no_history")


def test_build_units_is_candidates_times_conditions():
    candidates = [{"dataset": "mtbench", "source_task_id": "t1"},
                 {"dataset": "arena_hard", "source_task_id": "t2"}]
    units = rfs.build_units(candidates)
    assert len(units) == 2 * len(sc.CONDITIONS)


def test_full_run_covers_every_scorer_dataset_condition_and_wraps_olmo32b_with_system(tmp_path, monkeypatch):
    candidates_file = tmp_path / "candidates.json"
    _write_candidates(candidates_file, n_per_dataset=1)
    out_dir = tmp_path / "out"

    rc = _run(monkeypatch, ["--stub", "--candidates-file", str(candidates_file),
                           "--out", str(out_dir)])
    assert rc == 0

    records = [json.loads(l) for l in open(out_dir / "raw_results.jsonl", encoding="utf-8")]
    # A9: 3 tasks x 6 conditions x 3 small scorers + 3 tasks x 2 conditions for
    # olmo32b (the larger-model primary-effect replication).
    assert len(records) == sum(3 * len(rfs.conditions_for(sp.key))
                              for sp in rfs.SCORERS), len(records)

    olmo32b_records = [r for r in records if r["scorer_key"] == "olmo32b"]
    assert olmo32b_records
    assert all(r["messages"][0] == {"role": "system", "content": ""} for r in olmo32b_records)

    llama_records = [r for r in records if r["scorer_key"] == "llama"]
    assert all(len(r["messages"]) == 1 and r["messages"][0]["role"] == "user"
              for r in llama_records)


def test_scorer_panel_is_exactly_four_active_keys():
    assert {s.key for s in rfs.SCORERS} == {"llama", "qwen", "gemma", "olmo32b"}
    assert len(rfs.SCORERS) == 4


def test_olmo32b_scorer_spec_matches_the_frozen_pin():
    olmo = next(s for s in rfs.SCORERS if s.key == "olmo32b")
    assert olmo.hf_id == "allenai/Olmo-3.1-32B-Instruct"
    assert olmo.revision == "ac0587e4a7744a551c059d8cd17ba220bc940dae"
    assert olmo.force_use_cache is True
    assert olmo.requires_memory_preflight is True


def test_total_scoring_calls_are_13872_on_the_real_578_task_manifest():
    import json as _json
    from _bootstrap import REPO
    man = _json.loads((REPO / "data/prompts/final_tasks_v2_english_seed20260817.json")
                      .read_text(encoding="utf-8"))
    n_tasks = sum(len(d["selected"]) for d in man["datasets"].values())
    # A9 supersedes the 13,872 figure: 234 tasks, 4,680 logical judgments.
    assert rfs.A9_N_TASKS == 234
    assert sum(rfs.A9_EXPECTED_LOGICAL.values()) == rfs.A9_EXPECTED_TOTAL == 4680
    assert rfs.A9_EXPECTED_LOGICAL['olmo32b'] == 234 * 2
    assert 234 * 6 * 3 == 4212


def test_resume_skips_already_scored_units(tmp_path, monkeypatch):
    candidates_file = tmp_path / "candidates.json"
    _write_candidates(candidates_file, n_per_dataset=1)
    out_dir = tmp_path / "out"

    rc = _run(monkeypatch, ["--stub", "--candidates-file", str(candidates_file),
                           "--out", str(out_dir), "--limit", "2"])
    assert rc == 0
    n_after_first = sum(1 for _ in open(out_dir / "raw_results.jsonl", encoding="utf-8"))
    # Amendment A7: --limit is BATCH-granular, because a batch cannot be partially run without
    # changing the composition A7 froze. limit=2 therefore yields one full batch of 6 for each
    # batch-6 scorer and 2 single-unit batches for olmo32b.
    def _bs(sp):
        # stub=True: this is a --stub plumbing run, which A8 lets exercise the batched path
        return rfs.a7_batch_size(sp.key, stub=True)
    expected_first = sum(min(_bs(sp) * max(1, 2 // _bs(sp)), len(sc.CONDITIONS))
                         for sp in rfs.SCORERS)
    assert n_after_first == expected_first, (n_after_first, expected_first)

    rc = _run(monkeypatch, ["--stub", "--candidates-file", str(candidates_file),
                           "--out", str(out_dir)])  # no --limit: finish the rest
    assert rc == 0
    n_final = sum(1 for _ in open(out_dir / "raw_results.jsonl", encoding="utf-8"))
    # A9: llama/qwen/gemma run all six conditions; olmo32b runs only the two primary
    # ones as the larger-model replication.
    expected_total = sum(3 * len(rfs.conditions_for(sp.key)) for sp in rfs.SCORERS)
    assert n_final == expected_total, n_final

    seen_uids = set()
    dupes = []
    for line in open(out_dir / "raw_results.jsonl", encoding="utf-8"):
        uid = json.loads(line)["unit_id"]
        if uid in seen_uids:
            dupes.append(uid)
        seen_uids.add(uid)
    assert dupes == []  # resume never re-writes a unit already on disk


def test_a7_batch_policy_governs_batch_size_end_to_end(tmp_path, monkeypatch):
    candidates_file = tmp_path / "candidates.json"
    _write_candidates(candidates_file, n_per_dataset=2)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    verdict_path = out_dir / "batching_equivalence_verdict.json"
    def entry(passed, mem_required=False):
        return {"passed": passed, "token_equivalence_passed": passed,
                "memory_preflight_required": mem_required,
                "memory_preflight_passed": passed, "stub": False}

    verdict_path.write_text(json.dumps({
        "llama": entry(True), "qwen": entry(False), "gemma": entry(True),
        "olmo32b": entry(False, mem_required=True)}), encoding="utf-8")

    rc = _run(monkeypatch, ["--stub", "--candidates-file", str(candidates_file),
                           "--out", str(out_dir), "--batch-size", "4",
                           "--batching-verdict", str(verdict_path)])
    assert rc == 0
    records = [json.loads(l) for l in open(out_dir / "raw_results.jsonl", encoding="utf-8")]
    llama_batch_sizes = {r["batch_size"] for r in records if r["scorer_key"] == "llama"}
    qwen_batch_sizes = {r["batch_size"] for r in records if r["scorer_key"] == "qwen"}
    # Amendment A7 supersedes verdict-gated batching: the batch size is frozen policy, so a
    # failing verdict no longer forces batch 1 and a passing one no longer grants batching.
    assert llama_batch_sizes == {6}, llama_batch_sizes
    assert qwen_batch_sizes == {6}, qwen_batch_sizes
    olmo = {r["batch_size"] for r in records if r["scorer_key"] == "olmo32b"}
    assert olmo == {1}, olmo
