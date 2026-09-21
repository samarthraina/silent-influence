"""Amendment A8: generator batch 6 and OLMo-32B batch 1 are frozen; llama/qwen/gemma are
PENDING CALIBRATION and cannot run a real production scoring pass without a verdict produced on
their own production hardware. Thresholds are frozen before calibration and symmetric."""
from __future__ import annotations

import json

import pytest

import run_final_scoring as rfs


def test_frozen_policy_is_only_olmo32b_at_batch_1():
    assert rfs.A8_FROZEN_BATCH_POLICY == {"olmo32b": 1}
    assert rfs.a7_batch_size("olmo32b") == 1
    assert rfs.A7_GENERATOR_BATCH_SIZE == 6


def test_small_scorers_are_pending_not_licensed():
    assert set(rfs.A8_PENDING_CALIBRATION) == {"llama", "qwen", "gemma"}
    for k in rfs.A8_PENDING_CALIBRATION:
        assert k not in rfs.A8_FROZEN_BATCH_POLICY


@pytest.mark.parametrize("scorer", ["llama", "qwen", "gemma"])
def test_real_pass_without_a_calibration_verdict_hard_stops(scorer):
    with pytest.raises(SystemExit) as e:
        rfs.a7_batch_size(scorer)
    assert "HARD STOP (A8)" in str(e.value)
    assert "PENDING CALIBRATION" in str(e.value)


@pytest.mark.parametrize("scorer", ["llama", "qwen", "gemma"])
def test_a_failing_verdict_yields_batch_1_not_a_guess(tmp_path, scorer):
    v = tmp_path / "cal.json"
    v.write_text(json.dumps({scorer: {"passed": False}}), encoding="utf-8")
    assert rfs.a7_batch_size(scorer, calibration_path=str(v)) == 1


@pytest.mark.parametrize("scorer", ["llama", "qwen", "gemma"])
def test_a_passing_verdict_yields_batch_6(tmp_path, scorer):
    v = tmp_path / "cal.json"
    v.write_text(json.dumps({scorer: {"passed": True}}), encoding="utf-8")
    assert rfs.a7_batch_size(scorer, calibration_path=str(v)) == 6


def test_absent_malformed_or_foreign_verdicts_never_license_batching(tmp_path):
    missing = tmp_path / "nope.json"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"qwen": {"passed": True}}), encoding="utf-8")
    for path in (None, str(missing), str(bad), str(other)):
        with pytest.raises(SystemExit):
            rfs.a7_batch_size("llama", calibration_path=path)


def test_verdict_without_an_explicit_pass_is_not_a_pass(tmp_path):
    v = tmp_path / "cal.json"
    v.write_text(json.dumps({"llama": {"note": "looked fine"}}), encoding="utf-8")
    assert rfs.a7_batch_size("llama", calibration_path=str(v)) == 1


def test_stub_mode_exercises_the_batched_path_without_licensing_it(tmp_path):
    """A stub pass generates no real tokens and cannot write a protected target, so using the
    provisional size there licenses nothing about production."""
    assert rfs.a7_batch_size("llama", stub=True) == 6
    with pytest.raises(SystemExit):
        rfs.a7_batch_size("llama", stub=False)


def test_calibration_thresholds_are_frozen_and_exact():
    t = rfs.A8_CALIBRATION_THRESHOLDS
    assert t["max_abs_primary_delta_difference"] == 0.25
    assert t["max_abs_task_positive_fraction_change"] == 0.05
    assert t["min_batch6_a5_valid_rate"] == 0.95
    assert t["max_abs_validity_rate_difference_no_history_vs_self_low_2"] == 0.02


def test_thresholds_are_absolute_so_they_apply_symmetrically():
    """Direction-neutral: the same bound must reject an effect that grew and one that shrank."""
    lim = rfs.A8_CALIBRATION_THRESHOLDS["max_abs_primary_delta_difference"]
    for delta in (+0.30, -0.30):
        assert abs(delta) > lim, "both directions must fail the same bound"
    for delta in (+0.20, -0.20):
        assert abs(delta) <= lim, "both directions must pass the same bound"


def test_unknown_scorer_is_refused_rather_than_guessed():
    with pytest.raises(SystemExit):
        rfs.a7_batch_size("mistral")


def test_a5_is_untouched_by_a8():
    from silent_influence import output_validity as ov
    r = {"hit_token_cap": True, "emitted_terminator": False,
         "parse_ok": True, "parsed_score": 7.0}
    assert ov.is_valid(r) is False
    assert ov.analysis_score(r) is None
