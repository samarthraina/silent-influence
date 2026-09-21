"""Output protocols (Phase 1C).

The protocol controls emission order only. Because generation is autoregressive, the order
in this block decides whether the score exists before the rationale is written or after.
The parser reads by key, so all three protocols parse through the same code path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

_PREAMBLE = "Respond with ONLY valid JSON (no markdown fences, no prose outside JSON):"

_REL = '  "relevance": <int 1-10>'
_RQ = '  "reasoning_quality": <int 1-10>'
_JUST = '  "justification": "<2-3 sentences>"'


@dataclass(frozen=True)
class Protocol:
    name: str
    fields: List[str]          # emission order
    wants_justification: bool

    def schema_block(self) -> str:
        line_for = {"relevance": _REL, "reasoning_quality": _RQ, "justification": _JUST}
        body = ",\n".join(line_for[f] for f in self.fields)
        return f"{_PREAMBLE}\n{{\n{body}\n}}"


SCORE_ONLY = Protocol("score_only", ["relevance", "reasoning_quality"], False)
SCORE_THEN_JUSTIFICATION = Protocol(
    "score_then_justification", ["relevance", "reasoning_quality", "justification"], True)
JUSTIFICATION_THEN_SCORE = Protocol(
    "justification_then_score", ["justification", "relevance", "reasoning_quality"], True)

PROTOCOLS: Dict[str, Protocol] = {
    p.name: p for p in (SCORE_ONLY, SCORE_THEN_JUSTIFICATION, JUSTIFICATION_THEN_SCORE)
}

DEFAULT_SWEEP = list(PROTOCOLS)


def resolve(name: str) -> Protocol:
    if name not in PROTOCOLS:
        raise KeyError(f"unknown output protocol {name!r}; known: {sorted(PROTOCOLS)}")
    return PROTOCOLS[name]
