"""Phase 2F expected-score objective.

The objective replaces a parsed integer with a differentiable expectation, so the thing
worth testing is that it means the same: the same ten rubric-valid values, read at the
same position, weighted by the model's own probabilities. The tokenizer audit is the gate
that keeps that true, so it must fail loudly rather than approximate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from silent_influence import expected_score as es                      # noqa: E402

OUT = '{\n  "relevance": 10,\n  "reasoning_quality": 7\n}'


class _Tok:
    """A digit-level stand-in: every value 1..9 is one token, 10 is two."""

    def __init__(self, single_ten=True):
        self.single_ten = single_ten

    def __call__(self, s, add_special_tokens=False, return_offsets_mapping=False):
        ids, offs, i = [], [], 0
        while i < len(s):
            if self.single_ten and s.startswith("10", i):
                ids.append(910); offs.append((i, i + 2)); i += 2
                continue
            ids.append(ord(s[i])); offs.append((i, i + 1)); i += 1
        return {"input_ids": ids, "offset_mapping": offs}

    def decode(self, ids):
        return "".join("10" if i == 910 else chr(i) for i in ids)


def test_audit_accepts_single_token_values():
    v = es.audit_value_tokens(_Tok(single_ten=True))
    assert v.values == list(range(1, 11))
    assert len(set(v.ids)) == 10
    assert v.ids[-1] == 910


def test_audit_refuses_a_multi_token_value():
    """The failure mode the audit exists for: silently treating "10" as one class."""
    with pytest.raises(ValueError, match="not single tokens"):
        es.audit_value_tokens(_Tok(single_ten=False))


def test_value_token_locations():
    where = es.locate_value_tokens(_Tok(), OUT)
    assert set(where) == set(es.FIELDS)
    enc = _Tok()(OUT, return_offsets_mapping=True)
    assert enc["input_ids"][where["relevance"]] == 910
    assert enc["input_ids"][where["reasoning_quality"]] == ord("7")


def test_expected_score_is_the_weighted_value():
    torch = pytest.importorskip("torch")
    vocab = es.audit_value_tokens(_Tok())
    lg = torch.full((2, 1000), -30.0)
    lg[0, vocab.ids[9]] = 30.0          # relevance -> 10
    lg[1, vocab.ids[6]] = 30.0          # reasoning_quality -> 7
    per_field, total = es.expected_scores(lg, vocab)
    assert per_field[0].item() == pytest.approx(10.0, abs=1e-4)
    assert per_field[1].item() == pytest.approx(7.0, abs=1e-4)
    assert total.item() == pytest.approx(8.5, abs=1e-4)   # matches the frozen `total`


def test_expected_score_interpolates_and_is_differentiable():
    torch = pytest.importorskip("torch")
    vocab = es.audit_value_tokens(_Tok())
    lg = torch.full((2, 1000), -30.0, requires_grad=False)
    lg[0, vocab.ids[7]] = 0.0           # 8 and 9 equally likely -> 8.5
    lg[0, vocab.ids[8]] = 0.0
    lg[1, vocab.ids[4]] = 30.0
    lg = lg.clone().requires_grad_(True)
    per_field, total = es.expected_scores(lg, vocab)
    assert per_field[0].item() == pytest.approx(8.5, abs=1e-3)
    total.backward()
    assert torch.isfinite(lg.grad).all()
    assert lg.grad.abs().sum() > 0


def test_restricted_mass_flags_a_distribution_that_is_elsewhere():
    torch = pytest.importorskip("torch")
    vocab = es.audit_value_tokens(_Tok())
    lg = torch.full((1, 1000), -30.0)
    lg[0, vocab.ids[0]] = 0.0
    assert es.restricted_mass(lg, vocab)[0].item() > 0.9
    lg[0, 5] = 10.0                      # most mass now on a token that is not a value
    assert es.restricted_mass(lg, vocab)[0].item() < 0.1
