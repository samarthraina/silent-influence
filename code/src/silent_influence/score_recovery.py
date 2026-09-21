"""Post-hoc score-recovery audit for the 92 responses scaled_parsing.py could not parse.

This is deliberately a SEPARATE module from scaled_parsing.py, which is frozen: it is the
parser that actually ran during the completed behavioral experiment, validated against all
432 pilot records, and it must not change now that the run is over (changing it would mean
the parse_ok/parsed_score fields on disk no longer describe what was actually computed).
This module only ever runs against the already-frozen raw_results.jsonl, read-only, and
writes its findings to a separate adjudication file. raw_results.jsonl itself is never
touched.

Reading all 92 failures showed they fall into three kinds:

  1. A "final score" style label the scorer wrote in a language other than English --
     Spanish, Russian, Vietnamese, Japanese, French labels meaning "score", "rating",
     "evaluation", or "final score", immediately or near-immediately followed by an
     explicit "N/10". The English parser's Tier 1/Tier 2 logic (tight or lazily-tight
     label-to-number adjacency, explicit denominator, whole-text scan with last-match-wins
     so a later restated verdict beats an earlier component score) generalizes cleanly to
     these languages -- only the label vocabulary needed translating, not the mechanism.

  2. Three Gemma responses using "it scores a 9/10" -- a verb form ("scores", third person
     singular) the original Tier 3 regex's `scored?` alternation does not cover. Fixed
     narrowly by adding the missing conjugation; this is not a new pattern, it is a bug fix
     to an existing one.

  3. A handful of one-off verb-gated phrasings in Spanish, Vietnamese, French, and one
     Japanese response whose sole stated score is bare-bolded ("**6/10**が妥当です" -- "6/10
     is appropriate") rather than label-adjacent. These do not fit any general, safely
     reusable rule without risking a bare-number fallback on other data, so they are NOT
     matched by regex at all -- they are individually enumerated in MANUAL_OVERRIDES below,
     each with the exact phrase that justifies it. No override here is inferred from a
     pattern; every one was read in full by a human (this audit) before being added.

One response (a Korean answer, task arena_hard/8bf487d6bf4e4933, scorer llama, condition
no_history) is cut off mid-sentence with no score of any kind stated -- not a parsing
failure but a genuine absence of a verdict. It is intentionally NOT in MANUAL_OVERRIDES and
remains unresolved.

Nothing here ever falls back to an unrestricted bare number: every regex below requires an
explicit score-meaning label word AND an explicit "/10" denominator (English's spelled-out
"out of 10" was not observed in any non-English failure and is not extended cross-lingually
-- only the "/10" slash form, which is language-independent, is required for the new
patterns). The negative-lookahead-on-digit used in place of a word-boundary after the denominator is a
genuine fix, not a loosening: Python's Unicode-aware word-boundary does not fall between an
ASCII digit and a following CJK character (both are "word" characters), so a plain
word-boundary after "10" silently fails to match "10です" while succeeding on "10**" --
verified empirically against these exact strings before relying on it.

Markdown emphasis ("*"/"**") is stripped before matching, not encoded into every label
pattern: a label and its number are sometimes wrapped in two SEPARATE bold spans with a
space between them (e.g. "**Điểm tổng kết:** **7/10**"), and enumerating every possible
spacing/wrapping combination per language is more failure-prone than removing the purely
cosmetic markdown first. No case among the 92 uses "*" as meaningful content (a
multiplication sign, an escaped literal), so this is safe here specifically -- it is not a
general-purpose rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_NUM = r"(\d+(?:\.\d+)?)"
_DENOM = r"/\s*10(?!\d)"  # slash form only; see module docstring for why not "out of 10"

# Each label pattern: (name, compiled regex). All are whole-text scans; last match wins,
# exactly like the original Tier 1 -- so a later restated overall verdict correctly beats
# an earlier component score (observed in Russian and Vietnamese responses that give
# per-criterion scores before a final "Общая оценка"/"Điểm tổng kết" summary).
_LABEL_PATTERNS = [
    ("scores_verb_fix",
     # The original Tier 3 fix: "scored?" -> also match "scores" (3rd person singular).
     # Same verb-gated, 25-char-filler, denom-required structure as the original Tier 3.
     re.compile(rf"(?<!previously )\b(?:rate|give|gets?|scores?|scored)\b.{{0,25}}?{_NUM}\s*{_DENOM}",
                re.IGNORECASE)),
    ("spanish_label",
     # Puntuación / Puntuación final / Calificación / Calificación final
     re.compile(rf"\b(?:puntuaci[oó]n(?:\s+final)?|calificaci[oó]n(?:\s+final)?)\b"
                rf"\s*:?\s*\**\s*{_NUM}\s*{_DENOM}", re.IGNORECASE)),
    ("russian_label",
     # Оценка[ + one qualifier word]: e.g. "Оценка:", "Оценка содержания:", "Общая оценка:"
     re.compile(rf"(?:\S+\s+)?[Оо]ценк[а-я]*\s*(?:\S+\s+)?:?\s*\**\s*{_NUM}\s*{_DENOM}")),
    ("vietnamese_label",
     # Đánh giá / Điểm số / Điểm tổng kết / Tổng điểm
     re.compile(rf"\b(?:đánh giá|điểm số|điểm tổng kết|tổng điểm)\b\s*:?\s*\**\s*"
                rf"{_NUM}\s*{_DENOM}", re.IGNORECASE)),
    ("japanese_label",
     # 最終スコア / 総合評価 / 最終評価, tolerating an optional topic particle "は" or full/half
     # width colon before the number, and an optional trailing "です".
     re.compile(rf"(?:最終スコア|総合評価|最終評価)\s*(?:は|[:：])?\s*\**\s*{_NUM}\s*{_DENOM}")),
    ("french_label",
     # Évaluation / Note / Note finale
     re.compile(rf"\b(?:[EÉ]valuation|Note(?:\s+finale)?)\b\s*:?\s*\**\s*{_NUM}\s*{_DENOM}",
                re.IGNORECASE)),
    ("english_opening_clause",
     # "Evaluation of <anything, same sentence> : N/10" at the very start of the response --
     # a wider (but still start-anchored) sibling of scaled_parsing's TIER_OPENING_EVAL, for
     # a clause the original tier's 20-char lazy span doesn't reach.
     re.compile(rf"\A\s*\**\s*evaluation of\b.{{0,80}}?:\s*\**\s*{_NUM}\s*{_DENOM}",
                re.IGNORECASE)),
]

# Every one of these was read in full and manually judged to be the sole, unambiguous
# stated final score in that response -- see the module docstring. Not derived from a
# pattern; each key is a raw_results.jsonl unit_id.
MANUAL_OVERRIDES = {
    "llama__arena_hard__5b1813f617f74004__self_high_10": (
        10.0, 'Spanish verb-gated verdict: "le otorgaría un puntaje de 10/10" '
             '("I would grant it a score of 10/10") -- the only number in the response.'),
    "llama__arena_hard__d79dc091f8214898__self_low_2": (
        4.0, 'Vietnamese verb-gated verdict: "Tôi đánh giá nội dung này 4/10" '
            '("I rate this content 4/10") -- the only number in the response.'),
    "llama__arena_hard__d79dc091f8214898__other_low_2": (
        6.0, 'Vietnamese verb-gated verdict: "Tôi sẽ đánh giá nội dung này 6/10" '
            '("I will rate this content 6/10") -- the only number in the response.'),
    "llama__arena_hard__d79dc091f8214898__verbal_negative": (
        2.0, 'Vietnamese verb-gated verdict: "Tôi sẽ cho nội dung này 2/10" '
            '("I will give this content 2/10") -- the only number in the response.'),
    "llama__arena_hard__d61f684ce2b24b5b__self_high_10": (
        9.0, 'French verb-gated verdict: "Je donne une note de 9/10" '
            '("I give a rating of 9/10") -- the only number in the response.'),
    "qwen__arena_hard__d4e34b025a264179__self_low_2": (
        6.0, 'Japanese bare-bolded verdict: "**6/10**が妥当です" ("**6/10** is appropriate") '
            '-- the only number in the response, explicitly marked as the assessed value '
            'by the immediately-following judgement word (妥当 = appropriate/valid), even '
            'though no score/evaluation label word precedes it.'),
}

KNOWN_UNRESOLVED = {
    "llama__arena_hard__8bf487d6bf4e4933__no_history":
        "Korean response cut off mid-sentence (mid-word) before any verdict or score is "
        "stated. Not a parsing failure -- no score exists in the text to recover.",
}


@dataclass
class RecoveryResult:
    status: str  # "recovered_pattern" | "recovered_manual" | "unresolved"
    score: Optional[float] = None
    method: Optional[str] = None
    matched_text: Optional[str] = None
    note: Optional[str] = None


def recover_score(unit_id: str, response: Optional[str]) -> RecoveryResult:
    if unit_id in MANUAL_OVERRIDES:
        score, note = MANUAL_OVERRIDES[unit_id]
        return RecoveryResult("recovered_manual", score=score, method="manual_override",
                              note=note)
    if unit_id in KNOWN_UNRESOLVED:
        return RecoveryResult("unresolved", note=KNOWN_UNRESOLVED[unit_id])

    if not response:
        return RecoveryResult("unresolved", note="empty response")

    cleaned = response.replace("*", "")
    for name, pattern in _LABEL_PATTERNS:
        matches = list(pattern.finditer(cleaned))
        if not matches:
            continue
        m = matches[-1]
        score = float(m.group(1))
        if 0 <= score <= 10:
            return RecoveryResult("recovered_pattern", score=score, method=name,
                                  matched_text=m.group(0))

    return RecoveryResult("unresolved", note="no recognized label+score pattern found; "
                                             "not in the manual override list")
