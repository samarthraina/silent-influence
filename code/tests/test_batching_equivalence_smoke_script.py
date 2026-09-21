"""Integration tests for scripts/run_batching_equivalence_smoke.py against the real,
completed 90-task run's frozen answers (read-only, bundled in the repo) using the --stub
no-GPU path. Confirms the frozen task set, the no-contamination assertion, and that the
harness produces a verdict file run_final_scoring.py can consume."""
from __future__ import annotations

import json
import sys

import run_batching_equivalence_smoke as smoke


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["run_batching_equivalence_smoke.py"] + argv)
    return smoke.main()


def test_load_smoke_answers_finds_all_six_pinned_tasks_with_matching_char_counts():
    tasks = smoke.load_smoke_answers()
    assert len(tasks) == 6
    assert {t["dataset"] for t in tasks} == {"arena_hard", "wildbench"}


def test_smoke_task_ids_are_not_in_the_578_manifest():
    with open(smoke.REPO / "data/prompts/final_tasks_v2_english_seed20260817.json",
             encoding="utf-8") as f:
        manifest = json.load(f)
    ids_578 = {(ds, t["source_task_id"]) for ds, dd in manifest["datasets"].items()
              for t in dd["selected"]}
    for spec in smoke.SMOKE_SET:
        assert (spec["dataset"], spec["task_id"]) not in ids_578


def test_build_units_is_36():
    tasks = smoke.load_smoke_answers()
    units = smoke.build_units(tasks)
    assert len(units) == 36


def test_stub_run_produces_288_calls_and_a_passing_verdict(tmp_path, monkeypatch):
    rc = _run(monkeypatch, ["--stub", "--out", str(tmp_path), "--batch-size", "6"])
    assert rc == 0

    report = json.loads((tmp_path / "batching_equivalence_smoke_report.json")
                        .read_text(encoding="utf-8"))
    assert report["n_calls_total"] == 288           # 36 units x 4 scorers x 2 paths
    assert report["n_units"] == 36                  # 6 tasks x 6 conditions, per scorer

    verdict = json.loads((tmp_path / "batching_equivalence_verdict.json")
                         .read_text(encoding="utf-8"))
    assert set(verdict.keys()) == {"llama", "qwen", "gemma", "olmo32b"}
    # the stub is deterministic per-message content, so batch1 and batched agree exactly
    assert all(v["passed"] for v in verdict.values())
    assert all(v["n_mismatches"] == 0 for v in verdict.values())


def test_a_real_mismatch_is_detected_and_fails_that_scorer_only(tmp_path, monkeypatch):
    """Forces one scorer's batched path to diverge from its batch-1 path and confirms the
    comparison harness catches it and marks only that scorer as failed."""
    from silent_influence import exact_generation as eg

    real_batch_stub = eg.generate_exact_batch_stub

    def corrupting_batch_stub(loaded, list_of_messages, *, max_new_tokens, seed=42):
        results = real_batch_stub(loaded, list_of_messages, max_new_tokens=max_new_tokens,
                                  seed=seed)
        if loaded.spec.key == "llama" and results:
            results[0] = {**results[0], "generated_token_ids_sha256": "corrupted",
                         "text": "corrupted text"}
        return results

    monkeypatch.setattr(eg, "generate_exact_batch_stub", corrupting_batch_stub)

    rc = _run(monkeypatch, ["--stub", "--out", str(tmp_path), "--batch-size", "6"])
    assert rc == 0
    verdict = json.loads((tmp_path / "batching_equivalence_verdict.json")
                         .read_text(encoding="utf-8"))
    assert verdict["llama"]["passed"] is False
    assert verdict["llama"]["n_mismatches"] >= 1
    assert verdict["qwen"]["passed"] is True
    assert verdict["gemma"]["passed"] is True
    assert verdict["olmo32b"]["passed"] is True
