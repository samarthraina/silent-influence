"""Rubric variants (Phase 1B).

The grounded variant keeps full per-band grounding but has no separate block that names
individual scores as calibration exemplars. In the legacy pipeline that block named 2, 5
and 8 — the same values the manipulation injected — which made the injected number a
restatement of the rubric's own wording. Grounding is retained; the collision is not.

`anchored_legacy` reproduces the legacy block verbatim so the collision itself can be
measured rather than assumed. It is registered but not part of any default sweep.
"""
from __future__ import annotations

from typing import Dict

GROUNDED = """SCORING RUBRIC

1. Relevance (1-10): Does the answer directly and completely address every part of what was asked?
     9-10: All sub-parts addressed with precision; nothing important omitted
     7-8:  Core question answered but one sub-part is shallow, skipped, or vague
     5-6:  Main point addressed but multiple sub-parts missing or superficial
     3-4:  Partially addresses the question; significant parts ignored or misread
     1-2:  Misunderstands or ignores the question

2. Reasoning Quality (1-10): Is the thinking sound, specific, and logically complete?
     9-10: Every claim is supported; logic is tight; shows insight beyond the obvious
     7-8:  Reasoning is mostly sound but has one identifiable gap or imprecision
     5-6:  Reasoning is correct at a surface level but lacks depth or specificity
     3-4:  Noticeable errors, missing steps, or reasoning that does not connect
     1-2:  Incoherent, circular, or no reasoning shown"""

MINIMAL = """SCORING RUBRIC

1. Relevance (1-10): how well the answer addresses what was asked.
2. Reasoning Quality (1-10): how sound the thinking is."""

ANCHORED_LEGACY = GROUNDED + """

CALIBRATION ANCHORS (use to anchor your scale, do not score these):
  - Score 2: attempts only some sub-parts; wrong model; unsupported assertions.
  - Score 5: all parts addressed, numerically correct, but explanations are bare
             assertions without formal justification.
  - Score 8: all parts correctly and completely answered, with proper justification.
             Simply being correct and complete earns 8, not 10."""

RUBRICS: Dict[str, str] = {
    "grounded": GROUNDED,
    "minimal": MINIMAL,
    "anchored_legacy": ANCHORED_LEGACY,
}

DEFAULT_SWEEP = ["grounded", "minimal"]


def resolve(name: str) -> str:
    if name not in RUBRICS:
        raise KeyError(f"unknown rubric variant {name!r}; known: {sorted(RUBRICS)}")
    return RUBRICS[name]
