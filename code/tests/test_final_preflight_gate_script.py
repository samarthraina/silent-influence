"""Integration tests for scripts/verify_final_preflight_gate.py against the real, frozen
578-task manifest (bundled in the repo, no network/GPU needed to read it) using the --stub
no-GPU path for the model-loading parts."""
from __future__ import annotations

import json
import sys

import pytest

import verify_final_preflight_gate as vpg


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["verify_final_preflight_gate.py"] + argv)
    return vpg.main()


def test_canonical_task_matches_the_pinned_hash():
    task = vpg.load_canonical_task(vpg.MANIFEST_FILE, skip_hash_check=False)
    assert task["dataset"] == vpg.CANONICAL_DATASET
    assert task["source_task_id"] == vpg.CANONICAL_SOURCE_TASK_ID
    assert task["question_sha256"] == vpg.CANONICAL_QUESTION_SHA256


def test_canonical_task_is_lexicographically_smallest_in_the_500_heldout_population():
    with open(vpg.MANIFEST_FILE, encoding="utf-8") as f:
        manifest = json.load(f)
    held = [(ds, t["source_task_id"]) for ds in ("arena_hard", "wildbench")
           for t in manifest["datasets"][ds]["selected"]]
    assert len(held) == 500
    assert min(held, key=lambda x: x[1]) == (vpg.CANONICAL_DATASET, vpg.CANONICAL_SOURCE_TASK_ID)


def test_manifest_hash_mismatch_is_fatal(tmp_path):
    tampered = tmp_path / "tampered_manifest.json"
    tampered.write_text('{"datasets": {}}', encoding="utf-8")
    with pytest.raises(SystemExit):
        vpg.load_canonical_task(tampered, skip_hash_check=False)


def test_stub_gate_produces_24_renders_and_a_report(tmp_path, monkeypatch):
    out_path = tmp_path / "preflight_gate_report.json"
    rc = _run(monkeypatch, ["--stub", "--out", str(out_path)])
    assert rc == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["manifest_provenance"]["variant"] == "public_redacted"
    assert report["manifest_provenance"]["actual_sha256"] == vpg.PUBLIC_MANIFEST_SHA256
    assert report["manifest_provenance"]["whole_manifest_hash_checked"] is True
    assert report["n_renders"] == 24
    assert len(report["scorers"]) == 4
    scorer_keys = {r["scorer_key"] for r in report["renders"]}
    assert scorer_keys == {"llama", "qwen", "gemma", "olmo32b"}
    condition_names = {r["condition"] for r in report["renders"]}
    assert len(condition_names) == 6
    # exactly 6 renders per scorer, one per condition
    from collections import Counter
    counts = Counter(r["scorer_key"] for r in report["renders"])
    assert all(v == 6 for v in counts.values())


def test_reproducibility_check_against_a_frozen_baseline(tmp_path, monkeypatch):
    baseline_path = tmp_path / "baseline.json"
    rc = _run(monkeypatch, ["--stub", "--out", str(baseline_path)])
    assert rc == 0

    second_path = tmp_path / "second.json"
    rc = _run(monkeypatch, ["--stub", "--out", str(second_path),
                           "--verify-against", str(baseline_path)])
    assert rc == 0
    report = json.loads(second_path.read_text(encoding="utf-8"))
    assert report["reproducibility_test_5"]["checked"] is True
    assert report["reproducibility_test_5"]["passed"] is True
    assert report["reproducibility_test_5"]["n_mismatches"] == 0
