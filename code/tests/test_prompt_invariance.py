"""Prompt-invariance and parsing tests.

The invariance tests are the load-bearing ones: they are what makes "only the prior score
changed" a fact about the code rather than a claim in a paper.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from silent_influence import parsing, protocols, rubrics, templates          # noqa: E402
from silent_influence.conditions import (FULL_SWEEP, NO_HISTORY_CONDITION,   # noqa: E402
                                         SCORE_MAX, SCORE_MIN, score_condition)
from silent_influence.render import (ANSWER_LABEL, INSTRUCTION,              # noqa: E402
                                     SYSTEM_PROMPT, assert_score_invariance, render)

Q = "Write a function that reverses a linked list and explain the invariant."
A = "Here is an implementation.\n\ndef reverse(head): ...\n\nThe invariant is that ..."

VARIANTS = list(itertools.product(sorted(rubrics.RUBRICS),
                                  sorted(protocols.PROTOCOLS),
                                  sorted(templates.TEMPLATES)))


def _render(cond, rv, op, tmpl, **kw):
    return render(question=Q, candidate_response=A, prior=cond, rubric_variant=rv,
                  output_protocol=op, history_template=tmpl,
                  evaluated_label="ModelX", **kw)


@pytest.mark.parametrize("rv,op,tmpl", VARIANTS)
def test_score_arms_differ_only_in_the_numeral(rv, op, tmpl):
    assert_score_invariance(question=Q, candidate_response=A, rubric_variant=rv,
                            output_protocol=op, history_template=tmpl,
                            evaluated_label="ModelX")


@pytest.mark.parametrize("rv,op,tmpl", VARIANTS)
def test_skeleton_is_identical_across_all_score_values(rv, op, tmpl):
    skeletons = {_render(score_condition(v), rv, op, tmpl, score_sentinel=True).user
                 for v in range(SCORE_MIN, SCORE_MAX + 1)}
    assert len(skeletons) == 1


@pytest.mark.parametrize("rv,op,tmpl", VARIANTS)
def test_system_prompt_is_constant_across_every_condition(rv, op, tmpl):
    systems = {_render(c, rv, op, tmpl).system for c in FULL_SWEEP}
    assert systems == {SYSTEM_PROMPT}


@pytest.mark.parametrize("rv,op,tmpl", VARIANTS)
def test_nothing_but_the_history_block_changes_vs_no_history(rv, op, tmpl):
    """no_history is the same prompt with the history block removed - nothing else."""
    nh = _render(NO_HISTORY_CONDITION, rv, op, tmpl).user
    s5 = _render(score_condition(5), rv, op, tmpl).user
    head, _, tail = s5.partition(INSTRUCTION)
    assert tail == nh.partition(INSTRUCTION)[2]
    assert nh.startswith(INSTRUCTION)
    assert head.strip().endswith("5/10") or "5/10" in head


@pytest.mark.parametrize("rv,op,tmpl", VARIANTS)
def test_forbidden_dimensions_are_constant(rv, op, tmpl):
    """Identity wording, competition framing, labels, rubric, task and instruction must
    not vary with the prior-score condition."""
    banned = ["competition", "competitor", "contest", "ranking", "rival"]
    rendered = {c.name: _render(c, rv, op, tmpl).user for c in FULL_SWEEP}
    for name, text in rendered.items():
        low = text.lower()
        for b in banned:
            assert b not in low, f"{name}/{tmpl}: prompt contains {b!r}"
        assert text.count(f"**{ANSWER_LABEL}:**") == 1
        assert rubrics.resolve(rv) in text
        assert protocols.resolve(op).schema_block() in text
        assert Q in text and A in text
        assert text.count(INSTRUCTION) == 1


def test_anonymous_template_names_no_model():
    for v in range(SCORE_MIN, SCORE_MAX + 1):
        t = _render(score_condition(v), "grounded", "score_only",
                    "dyadic_anon_prior_round").user
        assert "ModelX" not in t


def test_no_history_carries_no_score():
    t = _render(NO_HISTORY_CONDITION, "grounded", "score_only",
                "dyadic_anon_prior_round").user
    assert "/10" not in t.split("SCORING RUBRIC")[0]


def test_protocol_controls_emission_order():
    assert protocols.resolve("justification_then_score").fields[0] == "justification"
    assert protocols.resolve("score_then_justification").fields[-1] == "justification"
    assert "justification" not in protocols.resolve("score_only").fields


@pytest.mark.parametrize("raw,status", [
    ('{"relevance":7,"reasoning_quality":6,"justification":"j"}', parsing.OK),
    ('{"relevance":11,"reasoning_quality":6,"justification":"j"}', parsing.OUT_OF_RANGE),
    ('{"relevance":0,"reasoning_quality":6,"justification":"j"}', parsing.OUT_OF_RANGE),
    ('{"relevance":"x","reasoning_quality":6,"justification":"j"}', parsing.NON_NUMERIC),
    ('{"reasoning_quality":6}', parsing.MISSING_FIELDS),
    ('no json here', parsing.NO_JSON),
    ('', parsing.EMPTY_OUTPUT),
])
def test_parser_status_classification(raw, status):
    assert parsing.parse(raw, wants_justification=True).status == status


def test_parser_never_invents_a_number():
    """The legacy pipeline coerced unparseable subscores to 0.0 and averaged them."""
    pr = parsing.parse('{"relevance":"excellent","reasoning_quality":8,"justification":"j"}',
                       wants_justification=True)
    assert pr.total is None and pr.relevance is None


# --- score_0: post-hoc exploratory boundary extension -----------------------------

def test_score_0_is_not_in_the_frozen_sweep():
    """The confirmatory sweep must stay 1-10 + no_history; score_0 is added alongside."""
    from silent_influence.conditions import FULL_SWEEP, SCORE_0_CONDITION
    assert SCORE_0_CONDITION not in FULL_SWEEP
    assert [c.name for c in FULL_SWEEP] == ["no_history"] + [f"score_{v}" for v in range(1, 11)]
    assert len(FULL_SWEEP) == 11


def test_score_0_is_distinct_from_no_history():
    """score_0 has the history sentence with a 0 in it; no_history has no sentence."""
    from silent_influence.conditions import NO_HISTORY_CONDITION, SCORE_0_CONDITION
    assert SCORE_0_CONDITION.has_history is True
    assert SCORE_0_CONDITION.score == 0
    assert NO_HISTORY_CONDITION.has_history is False
    assert NO_HISTORY_CONDITION.score is None
    a = _render(SCORE_0_CONDITION, "grounded", "score_only", templates.DEFAULT)
    b = _render(NO_HISTORY_CONDITION, "grounded", "score_only", templates.DEFAULT)
    assert "0/10" in a.user and "earlier round" in a.user
    assert "earlier round" not in b.user
    assert a.user != b.user


@pytest.mark.parametrize("rv,op,tmpl", VARIANTS)
def test_score_0_prompt_invariance(rv, op, tmpl):
    """score_0 must be the same skeleton with '0' substituted — nothing else may move."""
    kw = dict(question=Q, candidate_response=A, rubric_variant=rv,
              output_protocol=op, history_template=tmpl)
    if "{evaluated_label}" in templates.resolve(tmpl):
        kw["evaluated_label"] = "Response A"
    assert_score_invariance(values=[0, *range(SCORE_MIN, SCORE_MAX + 1)], **kw)


def test_score_0_differs_from_score_1_only_in_the_numeral():
    from silent_influence.conditions import SCORE_0_CONDITION, score_condition
    a = _render(SCORE_0_CONDITION, "grounded", "score_only", templates.DEFAULT).user
    b = _render(score_condition(1), "grounded", "score_only", templates.DEFAULT).user
    assert a.replace("0/10", "@/10", 1) == b.replace("1/10", "@/10", 1)
