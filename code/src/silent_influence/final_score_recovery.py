"""Post-hoc score-recovery rules for the final 578-task study's unparsed responses.

This is the final-study counterpart to score_recovery.py, which is FROZEN (pinned by
hash in configs/final_analysis_plan.json .measurement_and_adjudication.recovery_rules)
and must not be edited: its 90-task-specific MANUAL_OVERRIDES/KNOWN_UNRESOLVED dicts are
individually-justified, per-response judgements about six specific 90-task responses and
one specific 90-task non-response, and are meaningless for a different study's different
responses.

What genuinely generalizes -- the multilingual score-meaning-label regex patterns
(_LABEL_PATTERNS: Spanish/Russian/Vietnamese/Japanese/French/English-opening-clause,
each requiring an explicit label word AND an explicit "/10" denominator, never an
unrestricted bare number) -- is imported directly from score_recovery.py rather than
copy-pasted, so there is exactly one source of truth for that mechanism.

MANUAL_OVERRIDES and KNOWN_UNRESOLVED below start EMPTY because no data exists yet for
this study. They are populated later, after the real run produces real parse failures,
following the identical evidentiary standard as the 90-task audit: every entry read in
full by a human, added only with the exact quoted phrase that justifies it, and -- per
Amendment A1's independent_verification requirement -- confirmed by a second, independent,
blinded pass before being accepted (see scripts/build_final_adjudication_export.py and
scripts/merge_final_verifier_passes.py for that workflow).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from silent_influence.score_recovery import _LABEL_PATTERNS  # the general, reusable part

# Populated only after real human review of real final-study responses. Each value is
# (score, evidence_note) exactly like score_recovery.MANUAL_OVERRIDES; each key is a
# final-study raw_results.jsonl unit_id.
MANUAL_OVERRIDES: Dict[str, Tuple[float, str]] = {}

# unit_id -> human-readable reason a response has no recoverable score at all (e.g. cut
# off mid-sentence before any verdict). Populated only after real review.
KNOWN_UNRESOLVED: Dict[str, str] = {}


@dataclass
class RecoveryResult:
    status: str  # "recovered_pattern" | "recovered_manual" | "needs_manual_review" | "unresolved"
    score: Optional[float] = None
    method: Optional[str] = None
    matched_text: Optional[str] = None
    note: Optional[str] = None


def recover_score(unit_id: str, response: Optional[str]) -> RecoveryResult:
    """Same conservative rule as score_recovery.recover_score, with one addition: a
    response that no pattern resolves and that is not (yet) in MANUAL_OVERRIDES or
    KNOWN_UNRESOLVED comes back "needs_manual_review" rather than "unresolved" -- for
    THIS study that state is not yet a final verdict, it is a queue entry for the
    blinded two-reader process. A response only becomes genuinely "unresolved" once
    that process completes without agreement, or once a human explicitly records why no
    score exists (KNOWN_UNRESOLVED)."""
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

    return RecoveryResult("needs_manual_review",
                          note="no recognized label+score pattern found; queue for "
                               "blinded two-reader manual review")
