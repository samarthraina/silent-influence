"""Tests for scripts/verify_all_frozen_hashes.py -- the chain-wide frozen-hash gate.

The property under test throughout is that the gate cannot pass while skipping something:
every assertion in every freeze record is either verified, or named as a hard failure. Tests
build real records and real files on disk and assert the exit code, rather than re-reading the
gate's own constants back at it.
"""
from __future__ import annotations

import hashlib
import json

import pytest

import verify_all_frozen_hashes as vafh


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _record(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ------------------------------------------------------------------ the real chain

def test_the_real_chain_verifies_end_to_end():
    assert vafh.main() == 0


def test_every_freeze_record_in_the_chain_is_walked():
    names = {p.name for p in vafh.FREEZE_RECORDS}
    for expected in ("final_analysis_plan_v2_freeze_record.json",
                     "final_analysis_plan_A1_freeze_record.json",
                     "final_analysis_plan_A2_freeze_record.json",
                     "final_analysis_plan_A2_C1_freeze_record.json",
                     "final_analysis_plan_A3_freeze_record.json",
                     "final_analysis_plan_A4_freeze_record.json",
                     "final_analysis_plan_A5_freeze_record.json",
                     "final_analysis_plan_A6_freeze_record.json",
                     "final_analysis_plan_A7_freeze_record.json",
                     "final_analysis_plan_A8_freeze_record.json",
                     "final_analysis_plan_A9_freeze_record.json",
                     "manifest_v2_freeze_record.json"):
        assert expected in names, f"{expected} not walked by the chain gate"


@pytest.mark.parametrize("path", [
    "configs/final_analysis_plan_v2_8.json",
    "Code/research_notes/final_analysis_plan_amendment_A8.md",
    "scripts/run_final_scoring.py",
    "scripts/generate_final_candidates.py",
    "configs/final_analysis_plan_v2_6.json",
    "Code/research_notes/final_analysis_plan_amendment_A6.md",
    "src/silent_influence/exact_generation.py",
    "configs/final_analysis_plan_v2_5.json",
    "Code/research_notes/final_analysis_plan_amendment_A5.md",
    "src/silent_influence/output_validity.py",
    "configs/final_analysis_plan_v2_4.json",
    "Code/research_notes/final_analysis_plan_amendment_A4.md",
    "Code/research_notes/OBSERVATIONS.md",
    "Code/research_notes/JOURNAL.md",
    "configs/final_analysis_plan_v2_3.json",
    "Code/research_notes/final_analysis_plan_amendment_A3.md",
    # These two are asserted ONLY in shapes an earlier version of the gate did not read, so
    # they were verified by nothing. Their presence here is the regression guard.
    "results/final_task_selection/manifest_v2_freeze_record.json",
    "select_final_tasks_v2_english.py",
])
def test_every_shape_is_collected(path):
    assert any(a["path"] == path for a in vafh.collect()), \
        f"{path} is asserted in the chain but not collected -> would never be verified"


def test_all_six_assertion_shapes_are_represented():
    """Flat map, named-object-with-path, single object, alias map, bare module name, and the
    <name>/<name>_sha256 sibling convention must all reach the classifier."""
    assertions = vafh.collect()
    kinds = {vafh.classify(a) for a in assertions}
    assert {"repo", "note", "alias", "module_basename", "non_repo_snapshot"} <= kinds
    assert "unclassifiable" not in kinds, \
        [a for a in assertions if vafh.classify(a) == "unclassifiable"]
    # the sibling convention resolves to a path, not to the literal key
    assert any(a["path"] == "configs/scorer_mistral_small_24b_pin.json"
               and a["keypath"].endswith("pin_file_sha256") for a in assertions)


def test_verified_file_count_is_pinned_to_the_actual_chain():
    seen = {a["path"] for a in vafh.collect() if vafh.classify(a) in ("repo", "note")}
    assert len(seen) >= vafh.EXPECTED_VERIFIED_FILES - 2  # aliases/basenames dedupe into these
    assert vafh.EXPECTED_VERIFIED_FILES == 57


# ------------------------------------------------------------------ hard-fail behaviour

def test_tampered_artifact_fails(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    target.write_text("tampered", encoding="utf-8")
    rec = _record(tmp_path, "r_freeze_record.json",
                  {"new_artifacts_sha256": {str(target): "0" * 64}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [rec])
    assert vafh.main() == 1


def test_missing_repo_artifact_fails(tmp_path, monkeypatch):
    rec = _record(tmp_path, "r_freeze_record.json",
                  {"new_artifacts_sha256": {"configs/does_not_exist.json": "0" * 64}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [rec])
    assert vafh.main() == 1


def test_unreachable_working_note_is_a_hard_failure_not_a_skip(tmp_path, monkeypatch):
    """The regression that motivated this test: an out-of-tree note that cannot be found was
    printed as [N/A] and the gate still exited 0, so a vanished or renamed working note was
    indistinguishable from a verified one."""
    rec = _record(tmp_path, "r_freeze_record.json",
                  {"new_artifacts_sha256":
                   {"Code/research_notes/vanished_note.md": "0" * 64}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [rec])
    assert vafh.main() == 1


def test_conflicting_records_fail_rather_than_pick_one(tmp_path, monkeypatch):
    target = tmp_path / "artifact.json"
    target.write_text("x", encoding="utf-8")
    a = _record(tmp_path, "a_freeze_record.json",
                {"new_artifacts_sha256": {str(target): "a" * 64}})
    b = _record(tmp_path, "b_freeze_record.json",
                {"new_artifacts_sha256": {str(target): "b" * 64}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [a, b])
    assert vafh.main() == 1


def test_unclassifiable_assertion_fails_instead_of_being_dropped(tmp_path, monkeypatch):
    rec = _record(tmp_path, "r_freeze_record.json",
                  {"weird_group": {"not_a_path_at_all": "0" * 64}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [rec])
    assert vafh.main() == 1


def test_alias_whose_hash_matches_nothing_fails(tmp_path, monkeypatch):
    rec = _record(tmp_path, "r_freeze_record.json",
                  {"preserved_artifacts": {"some_alias": "0" * 64}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [rec])
    assert vafh.main() == 1


def test_count_deviation_fails_even_when_every_hash_matches(tmp_path, monkeypatch):
    """A shape quietly stopping being collected would leave fewer files verified while every
    remaining hash still matched. The pinned count is what catches that."""
    target = tmp_path / "one.json"
    target.write_text("x", encoding="utf-8")
    rec = _record(tmp_path, "r_freeze_record.json",
                  {"new_artifacts_sha256": {str(target): sha(b"x")}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [rec])
    assert vafh.main() == 1, "1 verified file must not satisfy an expectation of 57"


def test_empty_record_list_refuses_to_report_success(monkeypatch):
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [])
    assert vafh.main() == 1


# ------------------------------------------------------------------ path handling

def test_note_resolution_works_under_either_host_layout(monkeypatch, tmp_path):
    """The workstation nests the repo as PROJECT/Code/GitHub/<repo>; the GPU host puts
    /workspace/Code beside /workspace/<repo>."""
    repo = tmp_path / "workspace" / "silent-influence"
    repo.mkdir(parents=True)
    notes = tmp_path / "workspace" / "Code" / "research_notes"
    notes.mkdir(parents=True)
    (notes / "n.md").write_text("note", encoding="utf-8")
    monkeypatch.setattr(vafh, "REPO", repo)
    assert vafh.resolve_note("Code/research_notes/n.md") == notes / "n.md"

    deep = tmp_path / "P" / "Code" / "GitHub" / "repo"
    deep.mkdir(parents=True)
    dnotes = tmp_path / "P" / "Code" / "research_notes"
    dnotes.mkdir(parents=True)
    (dnotes / "n.md").write_text("note", encoding="utf-8")
    monkeypatch.setattr(vafh, "REPO", deep)
    assert vafh.resolve_note("Code/research_notes/n.md") == dnotes / "n.md"


def test_absolute_note_path_without_a_portable_twin_is_not_guessed(tmp_path, monkeypatch):
    """An absolute spelling must only be accepted when the same tail is also asserted as a
    portable Code/... path. Otherwise re-pointing it at a same-named file in the notes
    directory would verify a different file than the record names and report a pass."""
    repo = tmp_path / "workspace" / "silent-influence"
    repo.mkdir(parents=True)
    notes = tmp_path / "workspace" / "Code" / "research_notes"
    notes.mkdir(parents=True)
    (notes / "decoy.md").write_text("decoy content", encoding="utf-8")
    monkeypatch.setattr(vafh, "REPO", repo)
    rec = _record(tmp_path, "r_freeze_record.json",
                  {"new_artifacts_sha256":
                   {"D:/somewhere/else/research_notes/decoy.md": sha(b"decoy content")}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [rec])
    # the hash would MATCH the same-named local file; the gate must still refuse
    assert vafh.main() == 1


def test_absolute_note_path_with_a_portable_twin_is_accepted():
    """A2's record spells one note absolutely; the real chain also asserts it portably, so it
    is provably the same artifact and is verified rather than skipped."""
    assertions = vafh.collect()
    abs_notes = [a for a in assertions
                 if vafh.classify(a) == "note" and vafh.looks_absolute(a["path"])]
    assert abs_notes, "expected the historical absolute-path spelling to still be present"
    for a in abs_notes:
        tail = a["path"].replace("\\", "/")
        tail = tail[tail.find("research_notes/"):]
        assert any(o["path"].startswith("Code/") and o["path"].endswith(tail)
                   for o in assertions), f"no portable twin for {a['path']}"


def test_absoluteness_is_host_independent():
    for p in ("/workspace/x.md", "C:/Users/x.md", "D:\\x.md", "\\\\server\\x.md"):
        assert vafh.looks_absolute(p), p
    for p in ("configs/x.json", "Code/research_notes/x.md", "x.py"):
        assert not vafh.looks_absolute(p), p


# ------------------------------------------------------- living (append-only) documents

def test_journal_and_observations_are_treated_as_append_only():
    """Successive freeze records legitimately record different hashes for the journal, because
    a journal grows. Freezing it as immutable would make the next entry a hard failure -- which
    is exactly what happened when A5's entry was written after A4 had hashed the file."""
    assert vafh.is_living_document("Code/research_notes/JOURNAL.md")
    assert vafh.is_living_document("Code/research_notes/OBSERVATIONS.md")
    for immutable in ("Code/research_notes/final_analysis_plan_amendment_A5.md",
                      "configs/final_analysis_plan_v2_5.json",
                      "src/silent_influence/output_validity.py"):
        assert not vafh.is_living_document(immutable), immutable


def test_a_living_document_is_verified_against_the_newest_assertion(tmp_path, monkeypatch):
    notes = tmp_path / "workspace" / "Code" / "research_notes"
    notes.mkdir(parents=True)
    repo = tmp_path / "workspace" / "repo"
    repo.mkdir(parents=True)
    # write_bytes, not write_text: on Windows the latter translates \n to \r\n, so the file on
    # disk would not hash to sha(body).
    body = b"entry one\nentry two\n"
    (notes / "JOURNAL.md").write_bytes(body)
    monkeypatch.setattr(vafh, "REPO", repo)
    current = sha(body)
    old = _record(tmp_path, "a_freeze_record.json",
                  {"frozen_at_utc": "2026-08-17T10:00:00+00:00",
                   "new_artifacts_sha256": {"Code/research_notes/JOURNAL.md": "0" * 64}})
    new = _record(tmp_path, "b_freeze_record.json",
                  {"frozen_at_utc": "2026-08-17T20:00:00+00:00",
                   "new_artifacts_sha256": {"Code/research_notes/JOURNAL.md": current}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [old, new])
    monkeypatch.setattr(vafh, "EXPECTED_VERIFIED_FILES", 1)
    assert vafh.main() == 0, "the newest assertion should be the one verified"


def test_a_living_document_still_fails_when_the_newest_assertion_is_wrong(tmp_path, monkeypatch):
    """Append-only does not mean unchecked: the current content must still match the most
    recent record."""
    notes = tmp_path / "workspace" / "Code" / "research_notes"
    notes.mkdir(parents=True)
    repo = tmp_path / "workspace" / "repo"
    repo.mkdir(parents=True)
    (notes / "JOURNAL.md").write_text("tampered", encoding="utf-8")
    monkeypatch.setattr(vafh, "REPO", repo)
    new = _record(tmp_path, "b_freeze_record.json",
                  {"frozen_at_utc": "2026-08-17T20:00:00+00:00",
                   "new_artifacts_sha256": {"Code/research_notes/JOURNAL.md": "1" * 64}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [new])
    monkeypatch.setattr(vafh, "EXPECTED_VERIFIED_FILES", 1)
    assert vafh.main() == 1


def test_a_non_living_document_conflict_is_still_a_hard_failure(tmp_path, monkeypatch):
    target = tmp_path / "plan.json"
    target.write_text("x", encoding="utf-8")
    a = _record(tmp_path, "a_freeze_record.json",
                {"frozen_at_utc": "2026-08-17T10:00:00+00:00",
                 "new_artifacts_sha256": {str(target): "a" * 64}})
    b = _record(tmp_path, "b_freeze_record.json",
                {"frozen_at_utc": "2026-08-17T20:00:00+00:00",
                 "new_artifacts_sha256": {str(target): "b" * 64}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [a, b])
    assert vafh.main() == 1, "recency must not excuse a conflict about an immutable artifact"


# ------------------------------------------------- declared supersession (A8 re-pins A7's code)

def test_a8_declared_supersession_is_recognised():
    declared = vafh.declared_supersessions()
    assert "scripts/run_final_scoring.py" in declared
    assert "scripts/generate_final_candidates.py" in declared


def test_an_undeclared_conflict_is_still_a_hard_failure(tmp_path, monkeypatch):
    """Being newer is not a licence to disagree: only a record that explicitly names the path
    may re-pin it."""
    target = tmp_path / "plan.json"
    target.write_text("x", encoding="utf-8")
    a = _record(tmp_path, "a_freeze_record.json",
                {"frozen_at_utc": "2026-08-17T10:00:00+00:00",
                 "new_artifacts_sha256": {str(target): "a" * 64}})
    b = _record(tmp_path, "b_freeze_record.json",
                {"frozen_at_utc": "2026-08-17T20:00:00+00:00",
                 "new_artifacts_sha256": {str(target): sha(b"x")}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [a, b])
    assert vafh.main() == 1, "undeclared conflict must fail even though one hash is correct"


def test_a_declared_supersession_resolves_to_the_newest_and_still_verifies_content(
        tmp_path, monkeypatch):
    target = tmp_path / "code.py"
    target.write_text("x", encoding="utf-8")
    a = _record(tmp_path, "a_freeze_record.json",
                {"frozen_at_utc": "2026-08-17T10:00:00+00:00",
                 "new_artifacts_sha256": {str(target): "a" * 64}})
    b = _record(tmp_path, "b_freeze_record.json",
                {"frozen_at_utc": "2026-08-17T20:00:00+00:00",
                 "new_artifacts_sha256": {str(target): sha(b"x")},
                 "supersedes_hashes": {str(target): {"old": "a" * 64, "new": sha(b"x")}}})
    monkeypatch.setattr(vafh, "FREEZE_RECORDS", [a, b])
    monkeypatch.setattr(vafh, "EXPECTED_VERIFIED_FILES", 1)
    assert vafh.main() == 0

    # and a declared supersession whose NEW hash is wrong still fails
    target.write_text("tampered", encoding="utf-8")
    assert vafh.main() == 1, "declaration must not excuse wrong content"


def test_supersession_documentation_hashes_are_not_read_as_assertions():
    docs = [a for a in vafh.collect() if vafh.classify(a) == "documentation"]
    assert docs, "expected A8's supersedes_hashes_from_A7 block to be classified documentation"
    assert all(k in a["keypath"] for a in docs
               for k in [""])  # keypath present
    assert "unclassifiable" not in {vafh.classify(a) for a in vafh.collect()}
