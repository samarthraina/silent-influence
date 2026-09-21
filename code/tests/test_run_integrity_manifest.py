"""Tests for scripts/write_run_integrity_manifest.py's frozen-artifact hash verification."""
from __future__ import annotations

import json

import write_run_integrity_manifest as wrim


def test_frozen_artifacts_currently_match_on_disk():
    """Guards against a silent drift of any of the four frozen artifacts during this
    implementation pass -- the same hashes the user gave before implementation began."""
    for name, spec in wrim.FROZEN_ARTIFACTS.items():
        p = wrim.REPO / spec["path"]
        assert p.exists(), f"{name}: {p} missing"
        assert wrim.sha256_file(p) == spec["expected_sha256"], f"{name} hash drifted"


def test_main_detects_a_tampered_frozen_artifact(tmp_path, monkeypatch):
    tampered = tmp_path / "tampered_manifest.json"
    tampered.write_text('{"datasets": {}}', encoding="utf-8")
    monkeypatch.setitem(wrim.FROZEN_ARTIFACTS, "task_manifest_v2",
                        {"path": str(tampered),  # absolute path; REPO / abs_path == abs_path
                        "expected_sha256": "a001d48b7769311da33cba1a8ef51bb4e9d1a27b2cc0d007bce85adab606037f",
                        "status": "active"})
    out_dir = tmp_path / "results" / "final_behavioral_study"
    monkeypatch.setattr(wrim, "OUT_DIR", out_dir)
    rc = wrim.main()
    assert rc == 1
    manifest = json.loads((out_dir / "run_integrity_manifest.json").read_text(encoding="utf-8"))
    assert manifest["all_frozen_artifacts_match"] is False


# ---------------------------------------------------------------- Amendment A2 / C1 -------

def test_active_scorer_registry_is_olmo32b_not_mistral():
    assert {s["key"] for s in wrim.SCORERS} == {"llama", "qwen", "gemma", "olmo32b"}
    assert len(wrim.SCORERS) == 4
    olmo = next(s for s in wrim.SCORERS if s["key"] == "olmo32b")
    assert olmo["hf_id"] == "allenai/Olmo-3.1-32B-Instruct"
    assert olmo["revision"] == "ac0587e4a7744a551c059d8cd17ba220bc940dae"
    assert olmo["force_use_cache"] is True


def test_superseded_scorers_lists_mistral_as_historical_and_never_run():
    assert len(wrim.SUPERSEDED_SCORERS) == 1
    mistral = wrim.SUPERSEDED_SCORERS[0]
    assert mistral["key"] == "mistral"
    assert mistral["ever_run"] is False
    assert mistral["status"] == "historical_unused"
    assert "mistral" not in {s["key"] for s in wrim.SCORERS}


def test_a2_and_c1_and_olmo32b_pin_are_gated_as_active_frozen_artifacts():
    active = {name for name, spec in wrim.FROZEN_ARTIFACTS.items()
             if spec.get("status") == "active"}
    assert "analysis_plan_amendment_A2" in active
    assert "analysis_plan_clarification_C1" in active
    assert "olmo32b_scorer_pin" in active


def test_mistral_pin_is_gated_but_marked_historical_unused():
    spec = wrim.FROZEN_ARTIFACTS["mistral_scorer_pin"]
    assert spec["status"] == "historical_unused"
    # still integrity-checked, not removed from the gate entirely
    p = wrim.REPO / spec["path"]
    assert p.exists()
    assert wrim.sha256_file(p) == spec["expected_sha256"]


def test_active_frozen_artifacts_match_ignores_historical_corruption(tmp_path, monkeypatch):
    """A corrupted HISTORICAL artifact (e.g. the unused Mistral pin) must not be conflated
    with the active-registry gate: all_frozen_artifacts_match may go False, but
    active_frozen_artifacts_match should stay True if every ACTIVE artifact is intact."""
    tampered = tmp_path / "tampered_mistral_pin.json"
    tampered.write_text("{}", encoding="utf-8")
    monkeypatch.setitem(wrim.FROZEN_ARTIFACTS, "mistral_scorer_pin",
                        {"path": str(tampered),
                        "expected_sha256": "0" * 64, "status": "historical_unused"})
    out_dir = tmp_path / "results" / "final_behavioral_study"
    monkeypatch.setattr(wrim, "OUT_DIR", out_dir)
    rc = wrim.main()
    manifest = json.loads((out_dir / "run_integrity_manifest.json").read_text(encoding="utf-8"))
    assert manifest["all_frozen_artifacts_match"] is False
    assert manifest["active_frozen_artifacts_match"] is True
    assert rc == 1  # corruption anywhere still halts, even if only historical


# ---------------------------------------------------------------- Amendment A3 -------------

def test_a3_config_and_freeze_record_are_gated_as_active():
    for name, path in [
        ("analysis_plan_amendment_A3", "configs/final_analysis_plan_v2_3.json"),
        ("freeze_record_A3",
         "results/final_task_selection/final_analysis_plan_A3_freeze_record.json"),
    ]:
        spec = wrim.FROZEN_ARTIFACTS[name]
        assert spec["path"] == path
        assert spec["status"] == "active"


def test_full_amendment_chain_is_gated_without_dropping_history():
    """A3 must be added to the chain, not substituted for it."""
    names = set(wrim.FROZEN_ARTIFACTS)
    for required in ("analysis_plan_v2", "analysis_plan_amendment_A1",
                     "analysis_plan_amendment_A2", "analysis_plan_clarification_C1",
                     "analysis_plan_amendment_A3", "freeze_record_plan_v2",
                     "freeze_record_A1", "freeze_record_A2", "freeze_record_A2_C1",
                     "freeze_record_A3", "olmo32b_scorer_pin", "mistral_scorer_pin"):
        assert required in names, f"{required} dropped from the integrity manifest"
    assert wrim.FROZEN_ARTIFACTS["mistral_scorer_pin"]["status"] == "historical_unused"


def test_a3_narrative_is_referenced_out_of_tree_and_matches():
    """Uses the script's own resolver, not a hardcoded layout: the notes directory sits at a
    different depth on the workstation and on the GPU host."""
    spec = wrim.OUT_OF_TREE_REFERENCES["amendment_A3_narrative"]
    p = wrim.resolve_out_of_tree(spec["path"])
    assert p.exists(), f"narrative unreachable at {p}; expected beside the repo"
    assert wrim.sha256_file(p) == spec["expected_sha256"]
    # and the in-repo freeze record must assert the same hash, so the chain is closed
    rec = json.loads((wrim.REPO / spec["asserted_by"]).read_text(encoding="utf-8"))
    asserted = rec["new_artifacts_sha256"]["Code/research_notes/"
                                          "final_analysis_plan_amendment_A3.md"]
    assert asserted == spec["expected_sha256"]


def test_narrative_is_not_inside_the_pushable_tree():
    """Working notes must stay out of the repo; a copy appearing inside it is a leak."""
    assert not (wrim.REPO / "research_notes").exists()
    assert not (wrim.REPO / "Code/research_notes").exists()


def test_unreachable_narrative_is_not_a_failure(tmp_path, monkeypatch):
    """On the GPU host the narrative is intentionally absent; that must not fail the gate."""
    monkeypatch.setitem(wrim.OUT_OF_TREE_REFERENCES, "amendment_A3_narrative",
                        {"path": "research_notes/does_not_exist.md",
                         "expected_sha256": "0" * 64, "asserted_by": "x"})
    monkeypatch.setattr(wrim, "OUT_DIR", tmp_path / "r")
    assert wrim.main() == 0
    m = json.loads((tmp_path / "r" / "run_integrity_manifest.json").read_text(encoding="utf-8"))
    v = m["out_of_tree_reference_verification"]["amendment_A3_narrative"]
    assert v["reachable"] is False and v["status"] == "not_reachable_by_design"


def test_reachable_but_tampered_narrative_fails(tmp_path, monkeypatch):
    bad = wrim.resolve_out_of_tree(
        wrim.OUT_OF_TREE_REFERENCES["amendment_A3_narrative"]["path"])
    assert bad.exists(), "test needs a reachable narrative to tamper with"
    monkeypatch.setitem(wrim.OUT_OF_TREE_REFERENCES, "amendment_A3_narrative",
                        {"path": str(bad), "expected_sha256": "1" * 64,
                         "asserted_by": "x"})
    monkeypatch.setattr(wrim, "OUT_DIR", tmp_path / "r")
    assert wrim.main() == 1
