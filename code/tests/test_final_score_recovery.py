"""Tests for the final study's score-recovery rules. MANUAL_OVERRIDES/KNOWN_UNRESOLVED
start empty (no data exists yet); tests monkeypatch them to verify the lookup mechanism
without asserting anything about real study data (there is none)."""
from __future__ import annotations

from silent_influence import final_score_recovery as fsr


def test_pattern_recovery_matches_a_general_multilingual_label():
    result = fsr.recover_score("u1", "Puntuación final: 7/10")
    assert result.status == "recovered_pattern"
    assert result.score == 7.0


def test_no_pattern_match_and_no_override_is_queued_for_manual_review_not_unresolved():
    result = fsr.recover_score("u2", "This response has no labeled score at all, just prose.")
    assert result.status == "needs_manual_review"
    assert result.score is None


def test_empty_response_is_unresolved_not_queued():
    result = fsr.recover_score("u3", "")
    assert result.status == "unresolved"


def test_manual_override_lookup(monkeypatch):
    monkeypatch.setitem(fsr.MANUAL_OVERRIDES, "u4", (8.0, "quoted evidence phrase"))
    result = fsr.recover_score("u4", "irrelevant text since override wins")
    assert result.status == "recovered_manual"
    assert result.score == 8.0
    assert result.note == "quoted evidence phrase"


def test_known_unresolved_lookup(monkeypatch):
    monkeypatch.setitem(fsr.KNOWN_UNRESOLVED, "u5", "cut off mid-sentence")
    result = fsr.recover_score("u5", "some partial tex")
    assert result.status == "unresolved"
    assert result.note == "cut off mid-sentence"


def test_never_falls_back_to_bare_unlabeled_number():
    result = fsr.recover_score("u6", "I think this is roughly a 7 out of the possibilities.")
    assert result.status == "needs_manual_review"


def test_manual_overrides_and_known_unresolved_start_empty():
    assert fsr.MANUAL_OVERRIDES == {}
    assert fsr.KNOWN_UNRESOLVED == {}
