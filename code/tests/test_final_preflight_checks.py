"""Tests for the preflight template-audit fail-condition logic (pure text, no GPU)."""
from __future__ import annotations

from silent_influence import final_preflight_checks as fpc
from silent_influence import final_study_messages as fsm
from silent_influence import scaled_conditions as sc


def _render_user_only(prompt: str) -> str:
    return f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|>"


def _render_olmo32b_empty_system(prompt: str) -> str:
    """The real Olmo-3.1-32B-Instruct chat template's shape for an explicit empty system
    turn (Amendment A2 E8, verified against the pinned chat_template.jinja)."""
    return (f"<|im_start|>system\n<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n"
           f"<|im_start|>assistant\n")


def test_clean_user_only_render_passes():
    """qwen, not llama: Amendment A3 R1 makes the 134-byte template preamble MANDATORY for
    llama (its absence is a failure), so llama is no longer a valid stand-in for a bare
    user-only envelope. Llama's own shape is covered in test_a3_implementation.py."""
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = _render_user_only(prompt)
    check = fpc.check_render(rendered, prompt, scorer_key="qwen", condition_name="no_history",
                             allow_empty_system_tags=False)
    assert check.passed, check.violations


def test_olmo32b_empty_system_render_passes():
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = _render_olmo32b_empty_system(prompt)
    check = fpc.check_render(rendered, prompt, scorer_key="olmo32b", condition_name="no_history",
                             allow_empty_system_tags=False)
    assert check.passed, check.violations


def test_mistral_style_empty_system_tags_are_still_the_permitted_exception():
    """The [SYSTEM_PROMPT][/SYSTEM_PROMPT] exception was written for the never-run Mistral
    scorer and is retained in CONTROL_TOKENS/the allow_empty_system_tags path even though
    no active scorer uses it -- this documents that removing Mistral from the scorer
    registry did not silently break the underlying gate mechanism."""
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = f"<s>[SYSTEM_PROMPT][/SYSTEM_PROMPT][INST]{prompt}[/INST]"
    check = fpc.check_render(rendered, prompt, scorer_key="mistral", condition_name="no_history",
                             allow_empty_system_tags=True)
    assert check.passed, check.violations


def test_bare_empty_system_tags_carry_no_residual_words_for_any_scorer():
    """An EMPTY [SYSTEM_PROMPT][/SYSTEM_PROMPT] pair contributes no alphabetic content for
    anyone, because the tags themselves are control tokens. The allow_empty_system_tags
    flag therefore only documents the sanctioned exception -- it is not what does the
    work, and the gate must not depend on the caller getting that flag right. What the
    gate really relies on is that any CONTENT inside the tags still surfaces (next test)."""
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = f"<s>[SYSTEM_PROMPT][/SYSTEM_PROMPT][INST]{prompt}[/INST]"
    for scorer_key, allow in (("qwen", False), ("olmo32b", True)):
        check = fpc.check_render(rendered, prompt, scorer_key=scorer_key,
                                 condition_name="no_history", allow_empty_system_tags=allow)
        assert check.passed, (scorer_key, check.violations)


def test_non_empty_system_prompt_is_caught_even_with_the_exception_enabled():
    """The sanctioned exception covers an EMPTY tag pair only. A populated system block --
    the exact failure mode E1/E8 exists to prevent -- must still fail the gate."""
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = ("<s>[SYSTEM_PROMPT]You are Mistral Small 3, a Large Language Model (LLM) "
               f"created by Mistral AI. The current date is 2026-08-17."
               f"[/SYSTEM_PROMPT][INST]{prompt}[/INST]")
    check = fpc.check_render(rendered, prompt, scorer_key="olmo32b",
                             condition_name="no_history", allow_empty_system_tags=True)
    assert not check.passed
    assert check.residual_words and check.persona_hits and check.date_hits


def test_olmo32b_default_persona_leak_under_user_only_is_caught():
    """Reproduces (as a fixture, not a live fetch) the actual default system block
    allenai/Olmo-3.1-32B-Instruct's template injects when no system turn is supplied --
    the exact leak Amendment A2 E8 exists to prevent. Verified against the real pinned
    chat_template.jinja; see configs/scorer_olmo3_1_32b_pin.json
    .chat_template.BLOCKING_PROPERTY_RESOLVED_IN_A2 for the frozen record of this text."""
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    default_system = ("You are Olmo, a helpful AI assistant built by Ai2. Your date "
                      "cutoff is December 2024, and your model weights are available at "
                      "https://huggingface.co/allenai. You do not currently have access "
                      "to any functions. <functions></functions>")
    rendered = (f"<|im_start|>system\n{default_system}<|im_end|>\n<|im_start|>user\n"
               f"{prompt}<|im_end|>\n<|im_start|>assistant\n")
    check = fpc.check_render(rendered, prompt, scorer_key="olmo32b",
                             condition_name="no_history", allow_empty_system_tags=False)
    assert not check.passed
    assert check.residual_words
    assert check.date_hits  # "date cutoff"
    assert check.persona_hits  # "You are Olmo"


def test_date_leak_is_flagged():
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = f"The current date is 2026-08-17.\n{prompt}"
    check = fpc.check_render(rendered, prompt, scorer_key="olmo32b", condition_name="no_history",
                             allow_empty_system_tags=True)
    assert not check.passed
    assert check.date_hits


def test_persona_leak_is_flagged():
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = ("You are Olmo, a helpful AI assistant built by Ai2.\n" + prompt)
    check = fpc.check_render(rendered, prompt, scorer_key="olmo32b", condition_name="no_history",
                             allow_empty_system_tags=True)
    assert not check.passed
    assert check.persona_hits


def test_stray_instruction_word_is_flagged_as_residual_content():
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = f"Please be extra harsh when scoring.\n{prompt}"
    check = fpc.check_render(rendered, prompt, scorer_key="llama", condition_name="no_history",
                             allow_empty_system_tags=False)
    assert not check.passed
    assert check.residual_words


def test_control_tokens_alone_do_not_trigger_residual_content():
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = _render_user_only(prompt)
    check = fpc.check_render(rendered, prompt, scorer_key="qwen", condition_name="no_history",
                             allow_empty_system_tags=False)
    assert not check.residual_words


def test_olmo32b_im_start_control_tokens_alone_do_not_trigger_residual_content():
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))
    rendered = _render_olmo32b_empty_system(prompt)
    check = fpc.check_render(rendered, prompt, scorer_key="olmo32b", condition_name="no_history",
                             allow_empty_system_tags=False)
    assert not check.residual_words


def test_olmo32b_messages_render_matches_expected_shape_for_gate():
    prompt = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("self_low_2"))
    msgs = fsm.build_scorer_messages("olmo32b", prompt)
    assert msgs[0] == {"role": "system", "content": ""}
    assert msgs[1] == {"role": "user", "content": prompt}
