"""Guard against scientifically misleading summaries and silent artifact corruption."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))
from explore_results import summarize, matched_example

spec = importlib.util.spec_from_file_location("public_verifier", ROOT / "verify_package.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def fixture_results(tmp_path):
    for rel in ["results/behavioral/final_analysis_results.json",
                "results/figure_inputs/headline_metrics.json"]:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path / "results/behavioral/final_analysis_results.json"


def test_reported_estimate_uses_all_twelve_equal_weight_cells():
    result = summarize()
    assert result["matched_pairs"] == 900
    assert result["mean_shift"] == pytest.approx(1.1699584012855417)
    assert result["models"]["gemma"]["matched_pairs"] == 230
    assert result["context_unmentioned"]["denominator"] == 913


def test_missing_model_dataset_cell_is_rejected(tmp_path):
    path = fixture_results(tmp_path)
    data = json.loads(path.read_text())
    del data["complete_case"]["secondary"]["cell_means"]["mtbench|olmo32b"]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="12 cells"):
        summarize(tmp_path)


def test_changed_cell_mean_cannot_silently_keep_old_headline(tmp_path):
    path = fixture_results(tmp_path)
    data = json.loads(path.read_text())
    data["complete_case"]["secondary"]["cell_means"]["mtbench|llama"] += 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="macro estimate"):
        summarize(tmp_path)


def test_example_preserves_answer_and_selection_caveat():
    item = matched_example()
    assert item["_outcome_selected"] is True
    assert item["conditions"]["self_low_2"]["score"] == 4
    assert item["conditions"]["self_high_10"]["context_mention_label"] is None


def mini_manifest(tmp_path, relative="data.txt"):
    data = b"measured result\n"
    (tmp_path / "data.txt").write_bytes(data)
    entry = {"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (tmp_path / "ARTIFACT_MANIFEST.json").write_text(json.dumps({
        "n_files": 1, "total_bytes": len(data), "files": [entry]}))


def test_integrity_detects_same_size_tampering(tmp_path):
    mini_manifest(tmp_path)
    assert verifier.verify(tmp_path) == []
    (tmp_path / "data.txt").write_bytes(b"modified result\n")
    assert "Changed: data.txt" in verifier.verify(tmp_path)


def test_integrity_rejects_unlisted_payload(tmp_path):
    mini_manifest(tmp_path)
    (tmp_path / "extra.txt").write_text("untracked")
    assert "Unmanifested: extra.txt" in verifier.verify(tmp_path)


def test_integrity_rejects_path_traversal(tmp_path):
    mini_manifest(tmp_path, "../data.txt")
    assert "Unsafe manifest path: ../data.txt" in verifier.verify(tmp_path)


def test_preflight_rejects_changed_question_even_when_old_hash_field_is_retained(tmp_path):
    import verify_final_preflight_gate as preflight
    data = json.loads(preflight.MANIFEST_FILE.read_text())
    task = next(t for t in data["datasets"][preflight.CANONICAL_DATASET]["selected"]
                if t["source_task_id"] == preflight.CANONICAL_SOURCE_TASK_ID)
    task["question"] += " changed"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(data))
    with pytest.raises(SystemExit, match="question bytes mismatch"):
        preflight.load_canonical_task(changed, skip_hash_check=True)
