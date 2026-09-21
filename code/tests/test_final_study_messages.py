"""Tests for the scorer message-wrapping decision (Amendment A2's E8 resolution,
replacing the never-run Mistral scorer with allenai/Olmo-3.1-32B-Instruct)."""
from __future__ import annotations

import pytest

from silent_influence import final_study_messages as fsm


def test_olmo32b_gets_explicit_empty_system_message():
    msgs = fsm.build_scorer_messages("olmo32b", "PROMPT TEXT")
    assert msgs == [{"role": "system", "content": ""}, {"role": "user", "content": "PROMPT TEXT"}]


@pytest.mark.parametrize("scorer_key", ["llama", "qwen", "gemma"])
def test_other_scorers_are_user_only(scorer_key):
    msgs = fsm.build_scorer_messages(scorer_key, "PROMPT TEXT")
    assert msgs == [{"role": "user", "content": "PROMPT TEXT"}]


def test_unknown_scorer_key_raises():
    with pytest.raises(KeyError):
        fsm.build_scorer_messages("not_a_real_scorer", "x")


def test_retired_mistral_key_now_raises():
    """Amendment A2 retires the never-run Mistral scorer; MISTRAL_KEY no longer exists and
    the string "mistral" is not a recognized scorer_key. This guards against a stale
    caller silently falling through to some default instead of failing loudly."""
    assert not hasattr(fsm, "MISTRAL_KEY")
    with pytest.raises(KeyError):
        fsm.build_scorer_messages("mistral", "x")


def test_no_scorer_is_both_user_only_and_empty_system():
    overlap = set(fsm.USER_ONLY_SCORER_KEYS) & set(fsm.EMPTY_SYSTEM_SCORER_KEYS)
    assert overlap == set()


def test_scorer_panel_is_exactly_four_active_keys():
    all_keys = set(fsm.USER_ONLY_SCORER_KEYS) | set(fsm.EMPTY_SYSTEM_SCORER_KEYS)
    assert all_keys == {"llama", "qwen", "gemma", "olmo32b"}


def test_olmo32b_key_constant_matches_the_wrapping_decision():
    assert fsm.OLMO32B_KEY == "olmo32b"
    assert fsm.EMPTY_SYSTEM_SCORER_KEYS == (fsm.OLMO32B_KEY,)
