"""The single prompt composer.

One function builds every prompt in the study. Nothing else in the codebase may assemble
prompt text — that is what makes prompt invariance checkable in one place.

Invariance contract: for two score conditions differing only in value,
    render(v).user == render_canonical().user.replace(SENTINEL, str(v))
holds byte-for-byte. `assert_score_invariance` proves it rather than trusting it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import protocols, rubrics, templates
from .conditions import PriorContext

# Constant in every condition. Carries no judge identity: the legacy pipeline put the
# judge's own name here only in manipulated arms, which made it a second manipulation.
SYSTEM_PROMPT = (
    "You are a careful evaluator. Respond with valid JSON only - "
    "no markdown fences, no prose outside the JSON."
)

INSTRUCTION = "Score the following answer to the question using the rubric below."

# Constant across all conditions, so the answer label can never leak identity or condition.
ANSWER_LABEL = "Response A"


@dataclass(frozen=True)
class RenderedPrompt:
    system: str
    user: str


def render(
    *,
    question: str,
    candidate_response: str,
    prior: PriorContext,
    rubric_variant: str,
    output_protocol: str,
    history_template: str = templates.DEFAULT,
    evaluated_label: Optional[str] = None,
    score_sentinel: bool = False,
) -> RenderedPrompt:
    """Render one judging prompt.

    score_sentinel=True substitutes a placeholder for the numeral, giving the
    condition-independent skeleton used by the invariance proof.
    """
    blocks = []

    if prior.has_history:
        tmpl = templates.resolve(history_template)
        score_text = templates.SCORE_SENTINEL if score_sentinel else str(prior.score)
        if "{evaluated_label}" in tmpl and evaluated_label is None:
            raise ValueError(f"template {history_template!r} needs evaluated_label")
        blocks.append(tmpl.format(score=score_text, evaluated_label=evaluated_label))

    blocks.append(INSTRUCTION)
    blocks.append(f"QUESTION:\n{question}")
    blocks.append(f"ANSWER:\n**{ANSWER_LABEL}:**\n{candidate_response}")
    blocks.append(rubrics.resolve(rubric_variant))
    blocks.append(protocols.resolve(output_protocol).schema_block())

    return RenderedPrompt(system=SYSTEM_PROMPT, user="\n\n".join(blocks))


def assert_score_invariance(values=None, **kwargs) -> None:
    """Prove that score conditions differ only in the numeral. Raises on violation.

    `values` defaults to the frozen 1-10 sweep. Pass an explicit sequence to check an
    exploratory extension (e.g. including 0) without altering what the frozen check means.
    """
    from .conditions import SCORE_MAX, SCORE_MIN, score_condition

    kwargs.pop("prior", None)
    kwargs.pop("score_sentinel", None)
    if values is None:
        values = range(SCORE_MIN, SCORE_MAX + 1)

    skeleton = render(prior=score_condition(SCORE_MIN), score_sentinel=True, **kwargs)
    for v in values:
        got = render(prior=score_condition(v), **kwargs)
        want = skeleton.user.replace(templates.SCORE_SENTINEL, str(v))
        if got.user != want:
            raise AssertionError(
                f"score_{v} prompt is not the skeleton with {v} substituted; "
                f"the condition changed something other than the prior score")
        if got.system != skeleton.system:
            raise AssertionError(f"score_{v} changed the system prompt")
        if got.user.count(f"{v}/10") < 1:
            raise AssertionError(f"score_{v} does not contain the injected value")
