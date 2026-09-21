"""Judge-output parsing.

Every failure mode gets its own status so attrition can be reported as an outcome rather
than a silent drop — in the legacy pipeline unparseable subscores were coerced to 0.0 and
then averaged, which moved scores without leaving a trace.

Nothing here ever returns a number it did not read.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

SCORE_MIN, SCORE_MAX = 1, 10

OK = "ok"
NO_JSON = "no_json"
MISSING_FIELDS = "missing_fields"
NON_NUMERIC = "non_numeric"
OUT_OF_RANGE = "out_of_range"
EMPTY_OUTPUT = "empty_output"


@dataclass
class ParseResult:
    status: str
    relevance: Optional[float] = None
    reasoning_quality: Optional[float] = None
    total: Optional[float] = None
    justification: Optional[str] = None
    error: Optional[str] = None
    parsed_object: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.status == OK


def _candidate_objects(raw: str) -> List[Dict]:
    """Yield every plausible JSON object in the text, most-likely first."""
    text = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
    # Reasoning traces (Qwen3 thinking mode, R1-distill) precede the JSON.
    text = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think(?:ing)?>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    m = re.search(r"[{\[]", text)
    if m:
        text = text[m.start():]
    text = text.strip()
    if not text:
        return []

    out: List[Dict] = []

    def _add(obj):
        if isinstance(obj, dict):
            out.append(obj)
        elif isinstance(obj, list):
            out.extend(o for o in obj if isinstance(o, dict))
        elif isinstance(obj, dict) and "evaluations" in obj:
            out.extend(o for o in obj["evaluations"] if isinstance(o, dict))

    for attempt in (text, re.sub(r",\s*([}\]])", r"\1", text)):
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict) and "evaluations" in parsed:
                _add(parsed["evaluations"])
            else:
                _add(parsed)
            if out:
                return out
        except json.JSONDecodeError:
            pass

    # Balanced-scan fallback for trailing prose or truncated tails.
    i = 0
    while i < len(text):
        if text[i] in "{[":
            close = "}" if text[i] == "{" else "]"
            depth = 0
            for j in range(i, len(text)):
                if text[j] == text[i]:
                    depth += 1
                elif text[j] == close:
                    depth -= 1
                    if depth == 0:
                        frag = text[i:j + 1]
                        for attempt in (frag, re.sub(r",\s*([}\]])", r"\1", frag)):
                            try:
                                _add(json.loads(attempt))
                                break
                            except json.JSONDecodeError:
                                continue
                        i = j
                        break
        i += 1
    return out


def _to_number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.match(r"\s*(-?\d+(?:\.\d+)?)", v)
        if m:
            return float(m.group(1))
    return None


def parse(raw: str, wants_justification: bool) -> ParseResult:
    if raw is None or not raw.strip():
        return ParseResult(EMPTY_OUTPUT, error="model returned no text")

    objs = _candidate_objects(raw)
    if not objs:
        return ParseResult(NO_JSON, error="no JSON object found in output")

    obj = next((o for o in objs
                if "relevance" in o and "reasoning_quality" in o), objs[0])

    if "relevance" not in obj or "reasoning_quality" not in obj:
        return ParseResult(MISSING_FIELDS, parsed_object=obj,
                           error=f"keys present: {sorted(obj)}")

    rel = _to_number(obj["relevance"])
    rq = _to_number(obj["reasoning_quality"])
    just = obj.get("justification")
    just = str(just) if isinstance(just, str) and just.strip() else None

    if rel is None or rq is None:
        return ParseResult(NON_NUMERIC, justification=just, parsed_object=obj,
                           error=f"relevance={obj['relevance']!r} "
                                 f"reasoning_quality={obj['reasoning_quality']!r}")

    bad = [n for n, v in (("relevance", rel), ("reasoning_quality", rq))
           if not (SCORE_MIN <= v <= SCORE_MAX)]
    if bad:
        return ParseResult(OUT_OF_RANGE, relevance=rel, reasoning_quality=rq,
                           justification=just, parsed_object=obj,
                           error=f"outside {SCORE_MIN}-{SCORE_MAX}: {bad}")

    if wants_justification and just is None:
        return ParseResult(MISSING_FIELDS, relevance=rel, reasoning_quality=rq,
                           parsed_object=obj,
                           error="protocol expects a justification; none present")

    return ParseResult(OK, relevance=rel, reasoning_quality=rq,
                       total=(rel + rq) / 2, justification=just, parsed_object=obj)
