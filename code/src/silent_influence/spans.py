"""Phase 2C — downstream token spans for distributed activation patching.

The intervention patches every token state strictly after the prior-history sentence,
through the final input token. Three properties make the result interpretable, and each is
checked at run time rather than assumed:

  * no patched token lies inside the history sentence, so the target run still literally
    contains its own prior score;
  * the numeral itself is never patched;
  * the patched token ids are identical between source and target, so a state difference
    there can only have propagated from the earlier context.

Spans are built from character offsets into the *rendered* prompt and then intersected
with the downstream token set. A token straddling a block boundary is assigned exactly
once, by a fixed priority, so the three coarse spans partition the downstream set.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .activations import _tokens_covering
from .render import ANSWER_LABEL, INSTRUCTION

_QUESTION_HEADER = "QUESTION:\n"
_ANSWER_HEADER = f"ANSWER:\n**{ANSWER_LABEL}:**\n"
_RUBRIC_HEAD = "SCORING RUBRIC"

# The full downstream patch, then the three coarse localization spans that partition it.
BROAD = "downstream"
COARSE = ("candidate", "rubric_instruction", "other_downstream")


def downstream_token_indices(n_tokens: int, history_end_tokens: Sequence[int]) -> List[int]:
    """Every token strictly after the last token of the history sentence.

    Special and chat-template tokens are included: the span is defined positionally, not
    by whether a token carries visible text.
    """
    if not history_end_tokens:
        raise ValueError("history sentence not located; downstream span is undefined")
    return list(range(max(history_end_tokens) + 1, n_tokens))


def assert_history_excluded(offsets, downstream: Sequence[int],
                            history_char_span: Tuple[int, int]) -> None:
    """Raise if any downstream token overlaps the history sentence."""
    lo, hi = history_char_span
    for i in downstream:
        s, e = offsets[i]
        if e > s and s < hi and e > lo:
            raise AssertionError(
                f"downstream token {i} (chars {s}:{e}) overlaps the history sentence "
                f"{lo}:{hi}; the patch would carry the prior score directly")


def _find(hay: str, needle: str, start: int) -> int:
    i = hay.find(needle, start)
    if i < 0:
        raise ValueError(f"prompt block anchor not found: {needle[:48]!r}")
    return i


def char_blocks(templated: str, user_prompt: str, search_from: int
                ) -> Dict[str, Tuple[int, int]]:
    """Character spans of the downstream prompt blocks, in the templated text.

    `search_from` is the first character after the history sentence, so an anchor can
    never be matched inside the manipulated block.
    """
    u = templated.find(user_prompt)
    if u < 0:
        raise ValueError("rendered user prompt does not appear verbatim in the "
                         "chat-templated text; block anchors would be unreliable")
    u_end = u + len(user_prompt)

    i0 = _find(templated, INSTRUCTION, search_from)
    q0 = _find(templated, _QUESTION_HEADER, i0)
    a0 = _find(templated, _ANSWER_HEADER, q0)
    c0 = a0 + len(_ANSWER_HEADER)
    r0 = _find(templated, _RUBRIC_HEAD, c0)
    c1 = len(templated[:r0].rstrip())          # drop the blank line before the rubric
    return {"instruction": (i0, i0 + len(INSTRUCTION)),
            "question": (q0, a0),
            "candidate": (c0, c1),
            "rubric_schema": (r0, u_end)}


def coarse_spans(templated: str, offsets, user_prompt: str,
                 downstream: Sequence[int], search_from: int) -> Dict[str, List[int]]:
    """Partition the downstream tokens into the three coarse localization spans.

    candidate          — the candidate answer text being evaluated
    rubric_instruction — the scoring instruction, the rubric, and the output schema
    other_downstream   — the question, the block headers, separators and the chat tail
    """
    blocks = char_blocks(templated, user_prompt, search_from)
    down = set(downstream)

    cand = {i for i in _tokens_covering(offsets, *blocks["candidate"]) if i in down}
    rub = {i for i in _tokens_covering(offsets, *blocks["instruction"]) if i in down}
    rub |= {i for i in _tokens_covering(offsets, *blocks["rubric_schema"]) if i in down}
    rub -= cand                                # straddling token goes to the candidate
    rest = down - cand - rub

    out = {"candidate": sorted(cand), "rubric_instruction": sorted(rub),
           "other_downstream": sorted(rest)}
    covered = set().union(*out.values())
    if covered != down:
        raise AssertionError("coarse spans do not partition the downstream tokens")
    for name, idx in out.items():
        if not idx:
            raise AssertionError(f"coarse span {name!r} is empty")
    return out


def build(templated: str, offsets, user_prompt: str, history_end_tokens: Sequence[int],
          history_char_span: Tuple[int, int]) -> Dict[str, List[int]]:
    """All Phase 2C spans for one rendered prompt: the broad patch plus the partition."""
    down = downstream_token_indices(len(offsets), history_end_tokens)
    assert_history_excluded(offsets, down, history_char_span)
    out = {BROAD: down}
    out.update(coarse_spans(templated, offsets, user_prompt, down, history_char_span[1]))
    return out


def build_no_history(templated: str, offsets, user_prompt: str) -> Dict[str, List[int]]:
    """The same spans for a no_history prompt, which has no manipulated block to exclude.

    Every token is downstream, and the block anchors are searched from the start. The
    rubric span is byte-identical to the score conditions', so its token count must match;
    the caller checks that rather than assuming it.
    """
    down = list(range(len(offsets)))
    out = {BROAD: down}
    out.update(coarse_spans(templated, offsets, user_prompt, down, 0))
    return out
