"""Phase 2F — a differentiable expected score read off the model's own logits.

The behavioural pipeline scores by parsing greedily decoded JSON, which is not
differentiable. This builds the continuous counterpart without changing the scoring
semantics: the same `score_only` schema, the same two fields, and the same rubric-valid
values 1..10.

Tokenizer audit (Llama-3.1, run by `audit_value_tokens` and asserted before use): in the
frozen output format

    {\\n  "relevance": V,\\n  "reasoning_quality": W\\n}

every value 1..10 is a **single token**, and the preceding space is its own token, so all
ten candidates compete at exactly the same sequence position:

    1..9 -> ids 16..24        10 -> id 605

That makes the expected value an exact restricted softmax over ten classes rather than an
approximation. If a future tokenizer or format splits any value across tokens, the audit
fails loudly instead of silently degrading:

    E[field] = sum_v v * softmax(logits[pos, VALUE_IDS])_v
    ExpectedTotalScore = (E[relevance] + E[reasoning_quality]) / 2

which mirrors the frozen `total` field exactly. Probabilities are computed in float32
even though the activations are bfloat16.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

VALUES = tuple(range(1, 11))
FIELDS = ("relevance", "reasoning_quality")


@dataclass(frozen=True)
class ValueVocab:
    """One token id per valid serialized score value, in `VALUES` order."""
    ids: List[int]
    values: List[int]


def audit_value_tokens(tokenizer, template: str = None) -> ValueVocab:
    """Check that every valid value is one token in situ, and return the ids.

    Raises rather than approximating: a multi-token value would make the single-position
    softmax wrong, and silently treating it as a class is exactly the failure this guards.
    """
    template = template or '{\n  "relevance": %s,\n  "reasoning_quality": 5\n}'
    marker = '"relevance": '
    ids, bad = [], []
    for v in VALUES:
        s = template % v
        enc = tokenizer(s, add_special_tokens=False, return_offsets_mapping=True)
        lo = s.index(marker) + len(marker)
        hi = lo + len(str(v))
        idx = [i for i, (a, b) in enumerate(enc["offset_mapping"])
               if b > a and a < hi and b > lo]
        if len(idx) != 1:
            bad.append((v, [tokenizer.decode([enc["input_ids"][i]]) for i in idx]))
        else:
            ids.append(int(enc["input_ids"][idx[0]]))
    if bad:
        raise ValueError(
            "score values are not single tokens in the frozen output format: "
            f"{bad}. A restricted single-position softmax would change the scoring "
            "semantics; implement sequence-level candidate scoring instead.")
    if len(set(ids)) != len(VALUES):
        raise ValueError(f"value token ids are not distinct: {ids}")
    return ValueVocab(ids=ids, values=list(VALUES))


def locate_value_tokens(tokenizer, raw_output: str) -> Dict[str, int]:
    """Index, within the output token sequence, of each field's value token."""
    enc = tokenizer(raw_output, add_special_tokens=False, return_offsets_mapping=True)
    out = {}
    for f in FIELDS:
        marker = f'"{f}": '
        lo = raw_output.index(marker) + len(marker)
        hi = lo
        while hi < len(raw_output) and raw_output[hi].isdigit():
            hi += 1
        idx = [i for i, (a, b) in enumerate(enc["offset_mapping"])
               if b > a and a < hi and b > lo]
        if len(idx) != 1:
            raise ValueError(f"field {f!r} value is not a single token in this output")
        out[f] = idx[0]
    return out


def expected_scores(logits, vocab: ValueVocab):
    """[n_fields, vocab] logits at the value positions -> per-field expectations.

    `logits` rows must be ordered as `FIELDS`. Returns (per_field, total), both
    differentiable, computed in float32.
    """
    import torch

    lg = logits.float()
    idx = torch.as_tensor(vocab.ids, device=lg.device, dtype=torch.long)
    p = torch.softmax(lg.index_select(-1, idx), dim=-1)
    vals = torch.as_tensor(vocab.values, device=lg.device, dtype=p.dtype)
    per_field = (p * vals).sum(-1)
    return per_field, per_field.mean()


def restricted_mass(logits, vocab: ValueVocab):
    """Share of the full next-token distribution sitting on the ten valid values.

    Reported, not corrected for: if it is high, the restriction discards nothing, and the
    continuous objective is measuring the same decision the parser reads.
    """
    import torch

    lg = logits.float()
    idx = torch.as_tensor(vocab.ids, device=lg.device, dtype=torch.long)
    return torch.softmax(lg, dim=-1).index_select(-1, idx).sum(-1)
