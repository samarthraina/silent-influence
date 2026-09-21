"""Candidate-answer generation (Model X).

Model X is not a behavioural subject. Its only job is to produce one competent answer per
task, which is then frozen and scored identically by every judge under every condition.

Two things this module exists to guarantee:

1. An explicit system message is always sent. OLMo-3's chat template injects
   "You are a helpful function-calling AI assistant. You do not currently have access to
   any functions. <functions></functions>" whenever no system turn is supplied — an
   unrelated persona that would end up shaping every candidate answer.

2. The instruction asks for the user-facing answer only. Substantive explanation is
   wanted (the rubric scores reasoning quality); planning notes, self-commentary,
   grading, and self-identification are not.
"""
from __future__ import annotations

from typing import Dict, List

ANSWER_SYSTEM_PROMPT = (
    "You are producing the response that will be shown to a user. Answer the task "
    "directly and completely. Return only the final user-facing answer."
)

ANSWER_INSTRUCTION = (
    "Do not include scratch work, self-corrections, hidden reasoning, planning notes, "
    "or commentary about your reasoning process. Explanations that are naturally "
    "required as part of the final answer are allowed."
)


def build_answer_messages(question: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": f"{ANSWER_SYSTEM_PROMPT} {ANSWER_INSTRUCTION}"},
        {"role": "user", "content": question},
    ]


def candidate_record(*, dataset: str, prompt_id: str, candidate_response_id: str,
                     evaluated_model: str, text: str) -> Dict:
    """The five fields candidates.load_candidates reads. Metadata is added alongside."""
    return {
        "dataset": dataset,
        "prompt_id": prompt_id,
        "candidate_response_id": candidate_response_id,
        "evaluated_model": evaluated_model,
        "text": text,
    }
