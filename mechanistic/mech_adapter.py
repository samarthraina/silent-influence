"""Narrow adapter: final-study records -> the existing trace/jlens interface.

Two compatibility fixes only, both established by the compatibility smoke:

  1. run_trace.py / run_jlens.py read the Phase-1B record schema (judge_model, prompt_id,
     prior_context_condition, system_prompt, user_prompt, prior_score_value). Final-study
     records carry the same information under different names. to_trace_record() renames;
     it does not rewrite, reinterpret or recompute anything, and the raw records are never
     modified on disk.

  2. Those scripts call scaled_parsing.parse(...).total, which does not exist. The frozen
     behavioural parser is parse_final_score(...) returning .score. score_of() is the single
     place that call is made.

Nothing else about the activation or patching modules is touched.
"""
from __future__ import annotations

from typing import Optional, Tuple

from silent_influence import scaled_parsing as parsing

# The numeral each condition injects. no_history injects none; that is what makes its
# score_span and history_end empty, which the smoke confirmed is by design.
PRIOR_SCORE_VALUE = {
    "no_history": None, "self_low_2": 2, "other_low_2": 2, "unrelated_low_2": 2,
    "verbal_negative": None, "self_high_10": 10,
}


def split_messages(messages) -> Tuple[str, str]:
    """(system_prompt, user_prompt) from a frozen message list.

    Llama's frozen wrapping is a single user turn and no system turn (Amendment A2 E8), so
    the system half is empty. Returning "" rather than None keeps the downstream template
    call total.
    """
    system = "".join(m["content"] for m in messages if m["role"] == "system")
    user = "".join(m["content"] for m in messages if m["role"] == "user")
    if not user:
        raise ValueError("no user turn in messages")
    return system, user


def to_trace_record(rec: dict) -> dict:
    """One final-study record -> the field names the trace/jlens code expects.

    prompt_id is dataset-qualified because final-study task ids repeat across datasets
    (MT-Bench uses bare integers); the Phase-1B code assumed a globally unique id.
    """
    system, user = split_messages(rec["messages"])
    cond = rec["condition"]
    if cond not in PRIOR_SCORE_VALUE:
        raise KeyError(f"unknown condition {cond!r}")
    return {
        "judge_model": rec["scorer_key"],
        "prompt_id": f"{rec['dataset']}/{rec['source_task_id']}",
        "dataset": rec["dataset"],
        "source_task_id": rec["source_task_id"],
        "prior_context_condition": cond,
        "prior_score_value": PRIOR_SCORE_VALUE[cond],
        "system_prompt": system,
        "user_prompt": user,
        "parse_status": rec["parse_status"],
        "frozen_parsed_score": rec.get("parsed_score"),
        "analysis_valid": rec.get("analysis_valid"),
    }


def score_of(text: Optional[str]) -> Tuple[Optional[float], str]:
    """Frozen behavioural parser. Replaces the obsolete parse(...).total access."""
    pr = parsing.parse_final_score(text)
    return (float(pr.score) if pr.ok else None), pr.status
