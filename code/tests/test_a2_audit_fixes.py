"""Regression tests for the five defects found in the independent Opus audit of
Amendment A2 / Clarification C1. Each test names the defect it guards and the audit point
it maps to. No GPU, no weights, no network.
"""
from __future__ import annotations

import hashlib
import json
import sys

import pytest

import run_final_scoring as rfs
import verify_final_preflight_gate as vpg
from silent_influence import exact_generation as eg
from silent_influence import final_preflight_checks as fpc

OLMO = next(s for s in rfs.SCORERS if s.key == "olmo32b")
LLAMA = next(s for s in rfs.SCORERS if s.key == "llama")


def _verdict(**over):
    base = {"passed": True, "token_equivalence_passed": True,
            "memory_preflight_required": True, "memory_preflight_passed": True,
            "stub": False}
    base.update(over)
    return {"olmo32b": base}


# ============ D1 (audit point 8): batching gate bypass via the rolled-up "passed" flag ===

def test_d1_fully_valid_measured_verdict_permits_batching():
    assert rfs.effective_batch_size("olmo32b", 6, _verdict(), spec=OLMO) == 6


def test_d1_stub_derived_verdict_never_permits_batching():
    """A --stub smoke run generates no real tokens and touches no GPU, yet previously
    produced a verdict whose rolled-up 'passed' was True for every scorer."""
    assert rfs.effective_batch_size("olmo32b", 6, _verdict(stub=True), spec=OLMO) == 1
    assert rfs.effective_batch_size("llama", 6,
                                    {"llama": {"passed": True,
                                              "token_equivalence_passed": True,
                                              "stub": True}}, spec=LLAMA) == 1


def test_d1_token_equivalence_failure_is_independently_enforced():
    assert rfs.effective_batch_size(
        "olmo32b", 6, _verdict(token_equivalence_passed=False), spec=OLMO) == 1


def test_d1_memory_preflight_failure_is_independently_enforced():
    assert rfs.effective_batch_size(
        "olmo32b", 6, _verdict(memory_preflight_passed=False), spec=OLMO) == 1


def test_d1_verdict_omitting_memory_fields_cannot_batch_a_spec_that_requires_them():
    """A pre-A2 producer would emit no memory fields at all; the SPEC still requires them."""
    stale = {"olmo32b": {"passed": True, "token_equivalence_passed": True, "stub": False}}
    assert rfs.effective_batch_size("olmo32b", 6, stale, spec=OLMO) == 1


def test_d1_verdict_cannot_downgrade_its_own_memory_requirement():
    """The requirement comes from spec.requires_memory_preflight, not from the verdict's
    self-reported memory_preflight_required -- otherwise a verdict could excuse itself."""
    lying = _verdict(memory_preflight_required=False, memory_preflight_passed=False)
    assert rfs.effective_batch_size("olmo32b", 6, lying, spec=OLMO) == 1


def test_d1_absent_or_malformed_verdict_falls_back_to_batch_one():
    assert rfs.effective_batch_size("olmo32b", 6, {}, spec=OLMO) == 1
    assert rfs.effective_batch_size("olmo32b", 6, {"olmo32b": "notadict"}, spec=OLMO) == 1
    assert rfs.effective_batch_size("olmo32b", 6, {"olmo32b": None}, spec=OLMO) == 1


def test_d1_requested_batch_one_is_always_one():
    assert rfs.effective_batch_size("olmo32b", 1, _verdict(), spec=OLMO) == 1
    assert rfs.effective_batch_size("olmo32b", 0, _verdict(), spec=OLMO) == 1


def test_d1_non_memory_scorer_still_gated_on_token_equivalence():
    v = {"llama": {"passed": True, "token_equivalence_passed": False, "stub": False}}
    assert rfs.effective_batch_size("llama", 6, v, spec=LLAMA) == 1


# ============ D2 (audit point 13): stub output contaminating the final results dir ======

def test_d2_stub_run_refuses_to_write_into_protected_results_dir():
    for protected in fpc.PROTECTED_RESULT_DIRS:
        with pytest.raises(SystemExit):
            fpc.assert_stub_output_is_not_a_protected_dir(
                protected, stub=True, repo_root=".")


def test_d2_stub_run_refuses_a_subdirectory_of_a_protected_dir():
    with pytest.raises(SystemExit):
        fpc.assert_stub_output_is_not_a_protected_dir(
            "results/final_behavioral_study/nested/deeper", stub=True, repo_root=".")


def test_d2_stub_run_allows_a_safe_output_dir(tmp_path):
    fpc.assert_stub_output_is_not_a_protected_dir(tmp_path, stub=True, repo_root=".")


def test_d2_non_stub_run_is_never_restricted():
    """The real run must of course write into the final results directory."""
    for protected in fpc.PROTECTED_RESULT_DIRS:
        fpc.assert_stub_output_is_not_a_protected_dir(protected, stub=False, repo_root=".")


def test_d2_verdict_file_records_the_stub_flag(tmp_path, monkeypatch):
    import run_batching_equivalence_smoke as smoke
    monkeypatch.setattr(sys, "argv", ["x", "--stub", "--out", str(tmp_path),
                                     "--batch-size", "6"])
    assert smoke.main() == 0
    verdict = json.loads((tmp_path / "batching_equivalence_verdict.json")
                         .read_text(encoding="utf-8"))
    assert all(v["stub"] is True for v in verdict.values()), \
        "a stub run must mark every scorer's verdict entry as stub-derived"
    # and that verdict must not license batching downstream
    for key in verdict:
        spec = next(s for s in rfs.SCORERS if s.key == key)
        assert rfs.effective_batch_size(key, 6, verdict, spec=spec) == 1


def test_d2_preflight_stub_default_out_is_refused(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["verify_final_preflight_gate.py", "--stub"])
    with pytest.raises(SystemExit):
        vpg.main()


# ============ D3 (audit point 14): vacuously-true C1_2 gates ============================

def test_d3_frozen_mandate_lists_olmo32b():
    assert "olmo32b" in vpg.CACHE_CHECK_REQUIRED_SCORERS


def test_d3_gate_fails_closed_when_a_mandated_cache_check_did_not_run(tmp_path, monkeypatch):
    """The real fail-open: if force_use_cache were cleared on olmo32b, the reports dicts
    would stay empty and `all({}.values())` would make both gates vacuously True.

    Amendment A3 F2 replaced C1_2's cache-on/off equivalence gate with the 18-call
    production-path reproducibility gate; the anti-vacuous property being tested here is
    unchanged and must hold for the replacement."""
    orig = vpg.SCORERS
    monkeypatch.setattr(vpg, "SCORERS", [
        eg.ExactModelSpec(key=s.key, hf_id=s.hf_id, revision=s.revision,
                          disable_thinking=s.disable_thinking, force_use_cache=False,
                          requires_memory_preflight=s.requires_memory_preflight)
        for s in orig])
    monkeypatch.setattr(sys, "argv", ["x", "--stub", "--out", str(tmp_path / "r.json")])
    rc = vpg.main()
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rc == 1
    assert report["use_cache_gate_passed"] is False
    assert report["production_reproducibility_gate_passed"] is False
    assert report["gate_passed"] is False


def test_d3_gate_passes_when_the_mandated_check_does_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x", "--stub", "--out", str(tmp_path / "r.json")])
    assert vpg.main() == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert set(report["production_reproducibility_reports"]) == {"olmo32b"}
    assert report["production_reproducibility_reports"]["olmo32b"]["n_calls"] == 18
    assert report["gate_passed"] is True


# ============ D4 / D5 (audit point 9): shard resolution + crash-instead-of-report =======

def test_d4_path_traversal_shard_name_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside_shard.bin"
    outside.write_bytes(b"Q" * 64)
    h = hashlib.sha256(b"Q" * 64).hexdigest()
    problems = eg.verify_weight_shard_hashes(tmp_path, {"../outside_shard.bin": h})
    assert problems and "invalid shard name" in problems[0]


def test_d4_subdirectory_shard_name_is_rejected(tmp_path):
    problems = eg.verify_weight_shard_hashes(tmp_path, {"sub/x.safetensors": "0" * 64})
    assert problems and "invalid shard name" in problems[0]


def test_d4_absolute_shard_name_is_rejected(tmp_path):
    problems = eg.verify_weight_shard_hashes(tmp_path, {"/etc/passwd": "0" * 64})
    assert problems and "invalid shard name" in problems[0]


def test_d4_degenerate_names_are_rejected(tmp_path):
    for bad in ("", ".", ".."):
        problems = eg.verify_weight_shard_hashes(tmp_path, {bad: "0" * 64})
        assert problems, f"{bad!r} should be rejected"


def test_d5_directory_masquerading_as_a_shard_is_reported_not_raised(tmp_path):
    (tmp_path / "model-00001-of-00014.safetensors").mkdir()
    problems = eg.verify_weight_shard_hashes(
        tmp_path, {"model-00001-of-00014.safetensors": "0" * 64})
    assert problems and "not a regular file" in problems[0]


def test_d4_d5_legitimate_bare_filenames_still_verify(tmp_path):
    content = b"Z" * 1024
    (tmp_path / "model-00001-of-00014.safetensors").write_bytes(content)
    expected = {"model-00001-of-00014.safetensors": hashlib.sha256(content).hexdigest()}
    assert eg.verify_weight_shard_hashes(tmp_path, expected) == []


def test_d4_every_frozen_shard_name_survives_the_hardening():
    """The hardening must not reject the real pin file's own 14 shard names."""
    from _bootstrap import REPO
    pin = json.loads((REPO / "configs/scorer_olmo3_1_32b_pin.json")
                     .read_text(encoding="utf-8"))
    names = [k for k in pin["weight_shard_lfs_sha256_for_later_verification"]
            if k != "note"]
    assert len(names) == 14
    import pathlib
    for n in names:
        assert pathlib.Path(n).name == n, f"frozen name would be rejected: {n}"
