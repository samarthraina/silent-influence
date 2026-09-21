"""Phase 2A READ — hidden-state extraction at pre-specified prompt positions.

Reads only. A single forward pass per unit with `output_hidden_states=True`; nothing is
generated and no weights are touched.

Token positions are located from the *rendered* prompt via offset mapping, never by
assuming a numeral is one token: "1" and "10" tokenize differently, and the leading space
is often absorbed into the same token.

Hidden-state indexing convention, stated once and used everywhere:
`hidden_states` has len == n_layers + 1; index 0 is the embedding output and index L is
the output of transformer block L. Layer axis is stored with that same convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Position names, in the order they are stored on the position axis.
POSITIONS = ("score_span", "history_end", "final_input")


@dataclass
class SpanInfo:
    name: str
    char_start: Optional[int]
    char_end: Optional[int]
    token_indices: List[int]
    text: Optional[str]


def _tokens_covering(offsets, lo: int, hi: int) -> List[int]:
    """Token indices whose character span intersects [lo, hi)."""
    out = []
    for i, (s, e) in enumerate(offsets):
        if e <= s:            # special tokens carry an empty (0,0) span
            continue
        if s < hi and e > lo:
            out.append(i)
    return out


def locate_positions(templated: str, offsets, history_prefix: Optional[str],
                     score_value: Optional[int]) -> Dict[str, SpanInfo]:
    """Locate the three read positions in a rendered prompt.

    `history_prefix` is the fixed part of the history sentence up to the numeral, used to
    anchor the search so a numeral appearing elsewhere in the task cannot be matched.
    For no_history, both history positions are absent and only final_input is returned.
    """
    n_tok = len(offsets)
    final = SpanInfo("final_input", None, None, [n_tok - 1], None)

    if history_prefix is None or score_value is None:
        return {"score_span": SpanInfo("score_span", None, None, [], None),
                "history_end": SpanInfo("history_end", None, None, [], None),
                "final_input": final}

    anchor = templated.find(history_prefix)
    if anchor < 0:
        raise ValueError("history sentence not found in the rendered prompt")
    num = str(score_value)
    ns = templated.find(num + "/10", anchor)
    if ns < 0:
        raise ValueError(f"injected numeral {num!r} not found after the history anchor")
    ne = ns + len(num)

    # End of the history sentence: the first sentence terminator at or after the numeral.
    dot = templated.find(".", ne)
    if dot < 0:
        raise ValueError("no sentence terminator after the injected numeral")

    return {
        "score_span": SpanInfo("score_span", ns, ne,
                               _tokens_covering(offsets, ns, ne), templated[ns:ne]),
        "history_end": SpanInfo("history_end", dot, dot + 1,
                                _tokens_covering(offsets, dot, dot + 1),
                                templated[dot:dot + 1]),
        "final_input": final,
    }


def stratified_split(tasks: List[Tuple[str, str]], seed: int = 42
                     ) -> Tuple[List[str], List[str]]:
    """Category-stratified halving. `tasks` is [(prompt_id, category), ...].

    Deterministic and dependent only on the task list and seed, so it can be frozen and
    recorded before any activation is computed.
    """
    import random
    from collections import defaultdict

    by_cat = defaultdict(list)
    for pid, cat in tasks:
        by_cat[cat].append(pid)
    rng = random.Random(seed)
    shuffled = {c: rng.sample(sorted(v), len(v)) for c, v in sorted(by_cat.items())}

    # Exact halves overall. Each category contributes floor(n/2) first; the leftover
    # tasks from odd-sized categories are then handed to train in category order until
    # the global target is met, so the split is exactly half and stays stratified.
    target = len(tasks) // 2
    take = {c: len(v) // 2 for c, v in shuffled.items()}
    for c in sorted(shuffled):
        if sum(take.values()) >= target:
            break
        if len(shuffled[c]) % 2:
            take[c] += 1

    train, test = [], []
    for c in sorted(shuffled):
        train += shuffled[c][:take[c]]
        test += shuffled[c][take[c]:]
    return sorted(train, key=int), sorted(test, key=int)
