"""Round-trip integration test for the final study's score-recovery / blinded
adjudication / independent-verification workflow: audit -> export -> both verifier passes
-> merge -> patch into adjudicated records. Synthetic data only; raw_results.jsonl (a
stand-in here) is never modified in place."""
from __future__ import annotations

import json
import sys

import audit_final_score_recovery as audit_mod
import build_final_adjudication_export as export_mod
import build_final_adjudicated_records as patch_mod
import merge_final_verifier_passes as merge_mod


def _write_raw_results(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _argv(monkeypatch, script_name, *args):
    """These scripts take argparse options, so main() must not inherit pytest's argv."""
    monkeypatch.setattr(sys, "argv", [script_name, *args])


def _base_row(unit_id, response, parse_ok, parsed_score=None):
    return {
        "unit_id": unit_id, "scorer_key": "llama", "dataset": "arena_hard",
        "source_task_id": unit_id.split("__")[2], "condition": "no_history",
        "response": response, "parse_ok": parse_ok, "parsed_score": parsed_score,
        "parse_status": "ok" if parse_ok else "no_marker",
    }


def test_full_adjudication_round_trip(tmp_path, monkeypatch):
    study_dir = tmp_path / "results" / "final_behavioral_study"
    study_dir.mkdir(parents=True)
    raw_path = study_dir / "raw_results.jsonl"

    rows = [
        _base_row("llama__arena_hard__t1__no_history", "Final Score: 8/10", True, 8.0),
        _base_row("llama__arena_hard__t2__no_history", "Puntuación final: 6/10", False),
        _base_row("llama__arena_hard__t3__no_history", "This is prose with no verdict at all.", False),
        _base_row("llama__arena_hard__t4__no_history", "", False),
    ]
    _write_raw_results(raw_path, rows)

    monkeypatch.setattr(audit_mod, "RAW_RESULTS", raw_path)
    monkeypatch.setattr(audit_mod, "OUT", study_dir / "score_recovery_pattern_pass.json")
    _argv(monkeypatch, "audit_final_score_recovery.py")
    assert audit_mod.main() == 0
    pattern_pass = json.loads((study_dir / "score_recovery_pattern_pass.json")
                              .read_text(encoding="utf-8"))
    assert pattern_pass["n_recovered_pattern"] == 1   # t2 (Spanish label pattern)
    assert pattern_pass["n_needs_manual_review"] == 1  # t3
    assert pattern_pass["n_unresolved"] == 1           # t4, empty response

    monkeypatch.setattr(export_mod, "PATTERN_PASS", study_dir / "score_recovery_pattern_pass.json")
    monkeypatch.setattr(export_mod, "OUT_DIR", study_dir)
    _argv(monkeypatch, "build_final_adjudication_export.py")
    assert export_mod.main() == 0
    blinded = json.loads((study_dir / "review_queue_blinded.json").read_text(encoding="utf-8"))
    assert blinded["n_items"] == 1  # only t3 needed manual review
    private_map = json.loads((study_dir / "review_id_map_PRIVATE.json").read_text(encoding="utf-8"))
    review_id = next(iter(private_map))
    assert private_map[review_id] == "llama__arena_hard__t3__no_history"
    # the blinded file must never leak the unit_id, scorer, dataset, or condition
    assert "unit_id" not in json.dumps(blinded)
    assert "llama" not in json.dumps(blinded)

    v1 = {review_id: {"score": 5.0, "evidence": "I'd say this is a 5/10 overall."}}
    v2 = {review_id: {"score": 5.0, "evidence": "roughly a 5 out of 10"}}
    (study_dir / "verifier_1_pass.json").write_text(json.dumps(v1), encoding="utf-8")
    (study_dir / "verifier_2_pass.json").write_text(json.dumps(v2), encoding="utf-8")

    for name, val in [("PATTERN_PASS", study_dir / "score_recovery_pattern_pass.json"),
                      ("PRIVATE_MAP", study_dir / "review_id_map_PRIVATE.json"),
                      ("VERIFIER_1", study_dir / "verifier_1_pass.json"),
                      ("VERIFIER_2", study_dir / "verifier_2_pass.json"),
                      ("FINAL_OUT", study_dir / "final_adjudication.json")]:
        monkeypatch.setattr(merge_mod, name, val)
    _argv(monkeypatch, "merge_final_verifier_passes.py")
    assert merge_mod.main() == 0
    final_adj = json.loads((study_dir / "final_adjudication.json").read_text(encoding="utf-8"))
    assert final_adj["n_recovered_pattern"] == 1
    assert final_adj["n_recovered_manual_agreed"] == 1
    assert final_adj["n_disagreement_unresolved"] == 0

    adjudicated_dir = tmp_path / "results" / "final_behavioral_study_adjudicated"
    monkeypatch.setattr(patch_mod, "RAW_RESULTS", raw_path)
    monkeypatch.setattr(patch_mod, "ADJUDICATION", study_dir / "final_adjudication.json")
    monkeypatch.setattr(patch_mod, "OUT_DIR", adjudicated_dir)
    monkeypatch.setattr(patch_mod, "OUT_RECORDS", adjudicated_dir / "raw_results_adjudicated.jsonl")
    _argv(monkeypatch, "build_final_adjudicated_records.py")
    assert patch_mod.main() == 0

    adjudicated_rows = [json.loads(l) for l in
                       open(adjudicated_dir / "raw_results_adjudicated.jsonl", encoding="utf-8")]
    by_id = {r["unit_id"]: r for r in adjudicated_rows}
    assert by_id["llama__arena_hard__t1__no_history"]["parsed_score"] == 8.0   # untouched
    assert by_id["llama__arena_hard__t2__no_history"]["parsed_score"] == 6.0   # pattern-patched
    assert by_id["llama__arena_hard__t2__no_history"]["parse_ok"] is True
    assert by_id["llama__arena_hard__t3__no_history"]["parsed_score"] == 5.0   # manual-agreed
    assert by_id["llama__arena_hard__t4__no_history"]["parse_ok"] is False     # still unresolved

    # the ORIGINAL raw_results.jsonl on disk must be byte-for-byte untouched
    original_rows = [json.loads(l) for l in open(raw_path, encoding="utf-8")]
    assert original_rows == rows


def test_disagreement_leaves_response_unresolved_never_splits_the_difference(tmp_path, monkeypatch):
    study_dir = tmp_path / "study"
    study_dir.mkdir(parents=True)
    pattern_pass = {"entries": [
        {"unit_id": "llama__arena_hard__t9__no_history", "status": "needs_manual_review",
        "recovered_score": None, "matched_text": None, "note": "x",
        "scorer_key": "llama", "dataset": "arena_hard", "source_task_id": "t9",
        "condition": "no_history", "response": "ambiguous text"},
    ]}
    (study_dir / "pattern.json").write_text(json.dumps(pattern_pass), encoding="utf-8")
    (study_dir / "map.json").write_text(json.dumps({"rev_x": "llama__arena_hard__t9__no_history"}),
                                        encoding="utf-8")
    (study_dir / "v1.json").write_text(json.dumps({"rev_x": {"score": 4.0, "evidence": "e1"}}),
                                       encoding="utf-8")
    (study_dir / "v2.json").write_text(json.dumps({"rev_x": {"score": 6.0, "evidence": "e2"}}),
                                       encoding="utf-8")

    for name, val in [("PATTERN_PASS", study_dir / "pattern.json"),
                      ("PRIVATE_MAP", study_dir / "map.json"),
                      ("VERIFIER_1", study_dir / "v1.json"),
                      ("VERIFIER_2", study_dir / "v2.json"),
                      ("FINAL_OUT", study_dir / "final.json")]:
        monkeypatch.setattr(merge_mod, name, val)
    _argv(monkeypatch, "merge_final_verifier_passes.py")
    assert merge_mod.main() == 0
    final_adj = json.loads((study_dir / "final.json").read_text(encoding="utf-8"))
    assert final_adj["n_disagreement_unresolved"] == 1
    entry = final_adj["entries"][0]
    assert entry["final_status"] == "unresolved"
    assert entry["final_score"] is None
    assert entry["final_score"] != 5.0  # never split the difference (4.0, 6.0) -> 5.0
