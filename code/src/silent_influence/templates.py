"""Dyadic prior-score history blocks.

Every template must contain `{score}` exactly once and must contain no other field that
varies across prior-score conditions. `SCORE_SENTINEL` is substituted instead of a numeral
when rendering canonically, which is how prompt invariance is proved rather than asserted.

The default referent is anonymous. Naming the other model would reintroduce identity as a
live variable inside the manipulation, which Phase 1 deliberately holds out.
"""
from __future__ import annotations

from typing import Dict

SCORE_SENTINEL = "\x00PRIOR_SCORE\x00"

DYADIC_ANON_PRIOR_ROUND = (
    "In an earlier round, the model that produced the answer below evaluated your own "
    "answers and scored them {score}/10."
)

DYADIC_RECORD = (
    "Prior interaction record\n"
    "  The model that produced the answer below scored your answers: {score}/10"
)

# Available for a named-referent contrast; not in any default sweep because it moves
# identity back inside the manipulated block.
DYADIC_NAMED_PRIOR_ROUND = (
    "In an earlier round, {evaluated_label} evaluated your own answers and scored them "
    "{score}/10. The answer below is from {evaluated_label}."
)

TEMPLATES: Dict[str, str] = {
    "dyadic_anon_prior_round": DYADIC_ANON_PRIOR_ROUND,
    "dyadic_record": DYADIC_RECORD,
    "dyadic_named_prior_round": DYADIC_NAMED_PRIOR_ROUND,
}

DEFAULT = "dyadic_anon_prior_round"


def resolve(name: str) -> str:
    if name not in TEMPLATES:
        raise KeyError(f"unknown history template {name!r}; known: {sorted(TEMPLATES)}")
    return TEMPLATES[name]
