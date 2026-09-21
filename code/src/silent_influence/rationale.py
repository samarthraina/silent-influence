"""Post-decision rationale continuation (Phase 1B).

The judge is never asked to evaluate the answer again. Its original scoring turn is
replayed verbatim from the completed behavioural run and a single follow-up user turn is
appended, so the score is already fixed in the context before the rationale is generated.

What this measures is a *stated explanation given after a committed score*. It is not
evidence about hidden reasoning, and the follow-up wording is deliberately neutral: it
asks for reasons, never about prior context or influence.
"""
from __future__ import annotations

from typing import Any, Dict, List

FOLLOWUP = ('Briefly explain the main reasons for the score you just assigned. '
            'Do not revise the score. Respond with valid JSON only, exactly in this '
            'form: {"rationale":"<brief explanation>"} Do not include score fields.')

# Extractor statuses. Anything other than OK means the item is unusable for annotation
# and is reported, never silently coerced into a rationale.
R_OK = "ok"
R_MALFORMED = "malformed_json"
R_MISSING = "missing_rationale"
R_EMPTY = "empty_rationale"
R_SCORE_FIELDS = "score_fields_reemitted"
R_TRUNCATED = "truncated"

_SCORE_FIELDS = {"relevance", "reasoning_quality", "score", "total"}


def extract_rationale(text, hit_cap: bool = False):
    """Accept only a JSON object carrying a non-empty string field `rationale`.

    Returns (status, rationale_or_None, detail). Truncation is checked first: a capped
    generation can yield parseable-looking output that is nonetheless cut off.
    """
    import json as _json
    import re as _re

    if hit_cap:
        return R_TRUNCATED, None, "generation hit the token cap"
    raw = (text or "").strip()
    raw = _re.sub(r"^```(?:json)?\s*", "", raw)
    raw = _re.sub(r"```\s*$", "", raw).strip()
    m = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if not m:
        return R_MALFORMED, None, "no JSON object found"
    try:
        obj = _json.loads(m.group(0))
    except Exception as e:
        return R_MALFORMED, None, f"{type(e).__name__}: {str(e)[:60]}"
    if not isinstance(obj, dict):
        return R_MALFORMED, None, f"top level is {type(obj).__name__}, not object"
    present = _SCORE_FIELDS & set(obj)
    if "rationale" not in obj:
        return (R_SCORE_FIELDS if present else R_MISSING), None,             f"keys present: {sorted(obj)}"
    if present:
        return R_SCORE_FIELDS, None, f"score fields re-emitted: {sorted(present)}"
    val = obj["rationale"]
    if not isinstance(val, str):
        return R_MISSING, None, f"rationale is {type(val).__name__}, not str"
    if not val.strip():
        return R_EMPTY, None, "rationale is an empty string"
    return R_OK, val.strip(), ""


def build_messages(record: Dict[str, Any]) -> List[Dict[str, str]]:
    """Reconstruct the original exchange, then append the follow-up.

    Every element comes from the stored behavioural record — nothing is re-rendered, so
    the judge sees byte-identical context to what produced the frozen score.
    """
    for f in ("system_prompt", "user_prompt", "raw_output"):
        if not record.get(f):
            raise ValueError(f"behavioural record is missing {f!r}; cannot reconstruct")
    return [
        {"role": "system", "content": record["system_prompt"]},
        {"role": "user", "content": record["user_prompt"]},
        {"role": "assistant", "content": record["raw_output"]},
        {"role": "user", "content": FOLLOWUP},
    ]


def frozen_score(record: Dict[str, Any]) -> Dict[str, Any]:
    """The behavioural score, carried forward unchanged for the annotation key."""
    return {
        "relevance": record.get("relevance"),
        "reasoning_quality": record.get("reasoning_quality"),
        "total": record.get("total"),
        "behavioural_raw_output": record.get("raw_output"),
        "behavioural_unit_id": record.get("unit_id"),
    }
