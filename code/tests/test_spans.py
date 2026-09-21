"""Phase 2C span construction.

The load-bearing claim of the distributed patch is that nothing inside the manipulated
block is ever written, and that the patched text is identical across conditions. Both are
properties of the span builder, so they are tested here rather than asserted in prose.

A character tokenizer stands in for the real one: one token per character, offsets known
exactly. That isolates the span logic from tokenizer behaviour, which the run-time gate
checks separately against the real tokenizer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from silent_influence import spans, templates                            # noqa: E402
from silent_influence.conditions import score_condition                  # noqa: E402
from silent_influence.render import render                               # noqa: E402

Q = "Compare two indexing strategies for a 10 TB table and justify the choice."
A = "Use a covering index on (tenant_id, created_at).\n\nIt scores 10/10 on read paths."
PREFIX = templates.DYADIC_ANON_PRIOR_ROUND.split("{score}")[0]


def _templated(value):
    """Render one condition and wrap it the way a chat template would."""
    r = render(question=Q, candidate_response=A, prior=score_condition(value),
               rubric_variant="grounded", output_protocol="score_only")
    text = f"<|s|>{r.system}<|e|><|u|>{r.user}<|e|><|a|>\n"
    offsets = [(i, i + 1) for i in range(len(text))]
    anchor = text.find(PREFIX)
    dot = text.index(".", text.index(f"{value}/10", anchor))
    return text, offsets, r.user, [dot], (anchor, dot + 1)


def _build(value):
    text, offs, user, hist_end, hist_char = _templated(value)
    return text, spans.build(text, offs, user, hist_end, hist_char), hist_char


@pytest.mark.parametrize("value", [1, 10])
def test_history_and_numeral_never_downstream(value):
    """The candidate answer deliberately contains "10/10" too, so a builder that located
    the numeral by searching the whole prompt would patch it and fail here."""
    text, sp, (lo, hi) = _build(value)
    down = set(sp[spans.BROAD])
    injected = text.index(f"{value}/10", lo)
    assert injected < hi <= min(down)
    assert not down & set(range(lo, hi))
    patched = "".join(text[i] for i in sorted(down))
    assert PREFIX not in patched
    assert text[lo:hi] not in patched


@pytest.mark.parametrize("value", [1, 10])
def test_downstream_runs_to_the_final_token(value):
    text, sp, _ = _build(value)
    down = sp[spans.BROAD]
    assert down[-1] == len(text) - 1
    assert down == list(range(down[0], len(text)))


@pytest.mark.parametrize("value", [1, 10])
def test_coarse_spans_partition_the_downstream(value):
    _, sp, _ = _build(value)
    down = set(sp[spans.BROAD])
    parts = [set(sp[k]) for k in spans.COARSE]
    assert set().union(*parts) == down
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            assert not a & b


def test_coarse_spans_carry_the_expected_text():
    text, sp, _ = _build(7)
    cand = "".join(text[i] for i in sp["candidate"])
    rub = "".join(text[i] for i in sp["rubric_instruction"])
    rest = "".join(text[i] for i in sp["other_downstream"])
    assert cand == A
    assert "SCORING RUBRIC" in rub and "Respond with ONLY valid JSON" in rub
    assert "Score the following answer" in rub
    assert Q in rest and "<|a|>" in rest
    assert "SCORING RUBRIC" not in rest


def test_patched_text_is_identical_across_conditions():
    """What makes the intervention interpretable: same text, same sizes, both ends."""
    t1, s1, _ = _build(1)
    t10, s10, _ = _build(10)
    for name in (spans.BROAD,) + spans.COARSE:
        assert len(s1[name]) == len(s10[name])
        assert "".join(t1[i] for i in s1[name]) == "".join(t10[i] for i in s10[name])


def test_missing_history_is_rejected():
    with pytest.raises(ValueError):
        spans.downstream_token_indices(100, [])
