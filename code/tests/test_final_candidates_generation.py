"""Integration tests for scripts/generate_final_candidates.py: checkpoint/resume exercised
with synthetic (fabricated) records via the --stub no-GPU path, and the frozen
no-reserve-substitution failure policy. No GPU, no weights, no network.
"""
from __future__ import annotations

import json
import sys

import pytest

import generate_final_candidates as gfc
from silent_influence import exact_generation as eg


def _write_manifest(path, tasks):
    """tasks: list of (dataset, source_task_id, question) triples."""
    by_ds = {}
    for ds, tid, q in tasks:
        by_ds.setdefault(ds, {"selected": []})
        by_ds[ds]["selected"].append({
            "dataset": ds, "source_task_id": tid, "category": "cat", "question": q,
            "question_sha256": "x", "previously_used": False, "prior_use_phases": [],
        })
    manifest = {"n_selected_total": len(tasks), "selection_seed": 1, "datasets": by_ds}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["generate_final_candidates.py"] + argv)
    return gfc.main()


def test_first_run_accepts_every_task_under_stub(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [("mtbench", "t1", "Q1"), ("arena_hard", "t2", "Q2"),
                                    ("wildbench", "t3", "Q3")])
    out_dir = tmp_path / "out"
    candidates_out = tmp_path / "candidates.json"

    rc = _run(monkeypatch, ["--stub", "--skip-hash-check",
                           "--manifest-file", str(manifest_path),
                           "--out", str(out_dir), "--candidates-out", str(candidates_out)])
    assert rc == 0

    payload = json.loads(candidates_out.read_text(encoding="utf-8"))
    assert payload["n_accepted"] == 3
    assert payload["n_permanently_failed"] == 0
    assert payload["reserve_substitution"] == "disabled"
    assert {a["source_task_id"] for a in payload["accepted"]} == {"t1", "t2", "t3"}


def test_interrupt_and_resume_never_regenerates_an_accepted_task(tmp_path, monkeypatch):
    """Exercises checkpoint/resume with synthetic records: run generation for only the
    first task (simulating an interrupted run), then run again for the full set, and
    confirm the first task's accepted record is not regenerated -- only the remaining
    tasks produce new generation_records.jsonl entries."""
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [("mtbench", "t1", "Q1"), ("arena_hard", "t2", "Q2"),
                                    ("wildbench", "t3", "Q3")])
    out_dir = tmp_path / "out"
    candidates_out = tmp_path / "candidates.json"
    base_args = ["--stub", "--skip-hash-check", "--manifest-file", str(manifest_path),
                "--out", str(out_dir), "--candidates-out", str(candidates_out)]

    rc = _run(monkeypatch, base_args + ["--limit", "1"])
    assert rc == 0
    state_after_first = json.loads((out_dir / "generation_state.json").read_text(encoding="utf-8"))
    assert state_after_first["tasks"]["mtbench:t1"]["status"] == "accepted"
    assert state_after_first["tasks"]["arena_hard:t2"]["status"] == "pending"
    n_records_after_first = sum(1 for _ in open(out_dir / "generation_records.jsonl", encoding="utf-8"))
    assert n_records_after_first == 1

    rc = _run(monkeypatch, base_args)  # no --limit: finish the remaining tasks
    assert rc == 0
    state_final = json.loads((out_dir / "generation_state.json").read_text(encoding="utf-8"))
    assert all(v["status"] == "accepted" for v in state_final["tasks"].values())
    n_records_final = sum(1 for _ in open(out_dir / "generation_records.jsonl", encoding="utf-8"))
    # exactly 2 NEW attempts were appended (t2, t3); t1's original record was never rewritten
    assert n_records_final == 3

    payload = json.loads(candidates_out.read_text(encoding="utf-8"))
    assert payload["n_accepted"] == 3


def test_permanent_failure_is_not_substituted_and_does_not_block_other_tasks(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [("mtbench", "good1", "Q_GOOD"),
                                    ("arena_hard", "bad1", "Q_ALWAYS_FAILS"),
                                    ("wildbench", "good2", "Q_GOOD_2")])
    out_dir = tmp_path / "out"
    candidates_out = tmp_path / "candidates.json"

    real_stub = eg.generate_exact_stub
    attempts = {"bad1": 0}

    def flaky_stub(loaded, messages, *, max_new_tokens, seed=42, use_cache=None):
        content = messages[-1]["content"]
        if "Q_ALWAYS_FAILS" in content:
            attempts["bad1"] += 1
            raise RuntimeError("simulated persistent technical failure")
        return real_stub(loaded, messages, max_new_tokens=max_new_tokens, seed=seed,
                         use_cache=use_cache)

    monkeypatch.setattr(eg, "generate_exact_stub", flaky_stub)

    # Amendment A7: generation runs in batches of 6 in frozen manifest order, so these three
    # tasks share one physical batch. A batched call that RAISES loses every row, and A7 forbids
    # both retrying one member at a different batch size and silently failing its batch-mates.
    # Exhausting the identical-batch retries on a raising call is therefore an irrecoverable
    # technical error -- a hard stop -- rather than a permanent failure of the whole batch.
    # The retry is still bounded: exactly MAX_RETRIES_PER_TASK attempts, not endless.
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, ["--stub", "--skip-hash-check", "--manifest-file", str(manifest_path),
                          "--out", str(out_dir), "--candidates-out", str(candidates_out)])
    assert "HARD STOP (A7)" in str(excinfo.value)
    assert attempts["bad1"] == gfc.MAX_RETRIES_PER_TASK  # bounded retry, not endless
    # and no candidates file is produced, so nothing downstream can mistake a hard-stopped run
    # for a complete one
    assert not candidates_out.exists()
    # No task is marked failed_permanently by an infrastructure fault: A7 stops the run so the
    # cause can be fixed and the identical batch rerun, rather than burning the batch's tasks.
    state_path = out_dir / "generation_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        statuses = {k: v["status"] for k, v in state["tasks"].items()}
        assert "failed_permanently" not in statuses.values(), statuses


def test_no_reserve_substitution_for_a_task_that_produces_empty_output(tmp_path, monkeypatch):
    """The no-substitution rule still holds for the case A7 leaves as a per-row failure: the
    batched call SUCCEEDS but one row comes back empty. That row fails permanently after the
    bounded identical-batch retries; its batch-mates keep their results and are accepted."""
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [("mtbench", "good1", "Q_GOOD"),
                                    ("arena_hard", "empty1", "Q_EMPTY"),
                                    ("wildbench", "good2", "Q_GOOD_2")])
    out_dir = tmp_path / "out"
    candidates_out = tmp_path / "candidates.json"
    real_stub = eg.generate_exact_stub

    def empty_for_one(loaded, messages, *, max_new_tokens, seed=42, use_cache=None):
        out = real_stub(loaded, messages, max_new_tokens=max_new_tokens, seed=seed,
                        use_cache=use_cache)
        if "Q_EMPTY" in messages[-1]["content"]:
            return {**out, "text": ""}
        return out

    monkeypatch.setattr(eg, "generate_exact_stub", empty_for_one)
    rc = _run(monkeypatch, ["--stub", "--skip-hash-check", "--manifest-file", str(manifest_path),
                           "--out", str(out_dir), "--candidates-out", str(candidates_out)])
    assert rc == 0
    payload = json.loads(candidates_out.read_text(encoding="utf-8"))
    assert payload["n_accepted"] == 2
    assert payload["n_permanently_failed"] == 1
    assert payload["permanently_failed"][0]["source_task_id"] == "empty1"
    assert {a["source_task_id"] for a in payload["accepted"]} == {"good1", "good2"}
    assert "empty1" not in {a["source_task_id"] for a in payload["accepted"]}


def test_manifest_hash_gate_stops_on_mismatch(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path, [("mtbench", "t1", "Q1")])
    with pytest.raises(SystemExit):
        _run(monkeypatch, ["--stub", "--manifest-file", str(manifest_path),
                          "--out", str(tmp_path / "out"),
                          "--candidates-out", str(tmp_path / "c.json")])
