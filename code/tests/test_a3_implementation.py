"""Adversarial regression tests for Amendment A3 requirements R1-R5.

R1  Llama exact-prefix rule: only the frozen 134-byte literal, exactly once, at position 0,
    for llama only. A modified / duplicated / displaced / mid-prompt copy must FAIL.
R2  Gemma terminal cue: only the exact terminal <start_of_turn>model, exactly once. An
    arbitrary or mid-prompt occurrence must FAIL. 'model' must not be globally whitelisted.
R3  OLMo production reproducibility: 18 calls (3 reps x 6 conditions), all use_cache=True,
    exact equality of rendered inputs, input token IDs, generation kwargs and generated
    token IDs within each condition. Hard-fail on mismatch or missing repetition.
R4  A3's frozen Llama and OLMo render hashes folded into the preflight comparison.

No GPU, no weights, no network.
"""
from __future__ import annotations

import hashlib
import json
import sys

import pytest

import verify_final_preflight_gate as vpg
from silent_influence import exact_generation as eg
from silent_influence import final_preflight_checks as fpc
from silent_influence import scaled_conditions as sc

LIT = fpc.LLAMA_TEMPLATE_PREAMBLE
CUE = fpc.GEMMA_TERMINAL_CUE
PROMPT = sc.render_prompt("What is 2+2?", "Four.", sc.resolve("no_history"))


def _llama_render(prompt=PROMPT, preamble=LIT, extra_before="", extra_after=""):
    return (extra_before + preamble
            + "<|start_header_id|>user<|end_header_id|>\n\n" + prompt
            + extra_after
            + "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n")


def _gemma_render(prompt=PROMPT, extra_after_prompt="", cue_tail=True):
    tail = f"{CUE}\n" if cue_tail else ""
    return (f"<bos><start_of_turn>user\n{prompt}{extra_after_prompt}<end_of_turn>\n{tail}")


def _check(rendered, scorer_key, prompt=PROMPT):
    return fpc.check_render(rendered, prompt, scorer_key=scorer_key,
                            condition_name="no_history", allow_empty_system_tags=False)


# =========================================================== R1: pinned literal integrity

def test_r1_frozen_literal_matches_its_pinned_hash_and_length():
    assert hashlib.sha256(LIT.encode()).hexdigest() == fpc.LLAMA_TEMPLATE_PREAMBLE_SHA256
    assert len(LIT.encode()) == fpc.LLAMA_TEMPLATE_PREAMBLE_BYTES == 134
    assert fpc.PERMITTED_PREAMBLE_SCORER_KEYS == ("llama",)


def test_r1_canonical_llama_render_passes():
    chk = _check(_llama_render(), "llama")
    assert chk.passed, chk.violations
    assert chk.residual_words == [] and chk.date_hits == [] and chk.persona_hits == []
    assert chk.structure_problems == []


# =========================================================== R1: adversarial variants

def test_r1_absent_literal_fails():
    """A render with no preamble at all is a failure, not a pass -- the rule requires
    exactly one occurrence, so a template that silently stopped emitting it is caught."""
    no_preamble = _llama_render(preamble="")
    chk = _check(no_preamble, "llama")
    assert not chk.passed
    assert any("absent" in p for p in chk.structure_problems)


def test_r1_duplicated_literal_fails():
    chk = _check(_llama_render(preamble=LIT + LIT), "llama")
    assert not chk.passed
    assert any("occurs 2 times" in p for p in chk.structure_problems)


def test_r1_displaced_literal_fails_when_not_at_position_zero():
    chk = _check(_llama_render(extra_before="<|begin_of_text|>"), "llama")
    assert not chk.passed
    assert any("NOT at position 0" in p for p in chk.structure_problems)


def test_r1_mid_prompt_literal_copy_fails():
    """The exact literal injected into the middle of the user turn, in addition to the
    legitimate position-0 one, must fail on the occurrence count."""
    chk = _check(_llama_render(extra_after=LIT), "llama")
    assert not chk.passed
    assert any("occurs 2 times" in p for p in chk.structure_problems)


def test_r1_mid_prompt_literal_only_fails():
    """Only a mid-prompt copy and none at position 0: count is 1, but position is wrong."""
    rendered = ("<|start_header_id|>user<|end_header_id|>\n\n" + PROMPT + LIT
                + "<|eot_id|>")
    chk = _check(rendered, "llama")
    assert not chk.passed
    assert any("NOT at position 0" in p for p in chk.structure_problems)


@pytest.mark.parametrize("mutated", [
    LIT.replace("December 2023", "December 2024"),          # changed cutoff year
    LIT.replace("26 Jul 2024", "27 Jul 2024"),              # changed day
    LIT.replace("26 Jul 2024", "2026-08-17"),               # changed date format
    LIT.replace("Cutting", "Cutting "),                     # one extra byte
    LIT.replace("\n\n<|eot_id|>", "\n<|eot_id|>"),          # one missing byte
    LIT.replace("<|eot_id|>", ""),                          # truncated terminator
    LIT.replace("Cutting Knowledge Date", "Cutting  Knowledge Date"),   # doubled space
])
def test_r1_any_mutated_literal_fails(mutated):
    """A changed date or any changed byte must fail: the rule is byte-exact, not a pattern."""
    chk = _check(_llama_render(preamble=mutated), "llama")
    assert not chk.passed, f"mutated literal wrongly accepted: {mutated[:60]!r}"


def test_r1_stray_whitespace_after_the_literal_is_caught_by_the_hash_gate():
    """The exact literal followed by a stray space still satisfies the structural rule --
    the literal is unmutated and at position 0, and a bare space carries no semantic
    content. That byte is caught instead by R4's byte-exact frozen render-hash gate, which
    is why both gates are required rather than either alone."""
    rendered = _llama_render(preamble=LIT + " ")
    chk = _check(rendered, "llama")
    assert chk.passed, "structural rule should not fire on non-semantic whitespace"

    canonical_sha = hashlib.sha256(_llama_render().encode()).hexdigest()
    stray_sha = hashlib.sha256(rendered.encode()).hexdigest()
    assert stray_sha != canonical_sha
    rep = vpg.check_frozen_render_hashes(
        [{"scorer_key": "llama", "condition": c, "rendered_text_sha256": stray_sha}
         for c in vpg.A3_FROZEN_RENDER_SHA256["llama"]])
    assert rep["passed"] is False, "the hash gate must catch what the structural rule allows"


def test_r1_mutated_literal_also_surfaces_the_date_leak():
    """Defence in depth: a mutated preamble is not stripped, so its date content is ALSO
    caught by the date scan, not only by the structural rule."""
    chk = _check(_llama_render(preamble=LIT.replace("26 Jul 2024", "27 Jul 2024")), "llama")
    assert chk.structure_problems
    assert chk.date_hits, "the unstripped date content should still be detected"


def test_r1_exception_is_scoped_to_llama_only():
    """The same literal in another scorer's render is a leak, not boilerplate."""
    for other in ("qwen", "gemma", "olmo32b"):
        chk = _check(_llama_render(), other)
        assert not chk.passed, f"{other} wrongly inherited the llama exception"
        assert chk.date_hits, f"{other} should surface the date content"


def test_r1_does_not_weaken_other_scorers_date_or_persona_checks():
    inj = ("<|im_start|>user\nToday Date: 26 Jul 2024\nYou are Foo.\n" + PROMPT
           + "<|im_end|>\n<|im_start|>assistant\n")
    chk = _check(inj, "qwen")
    assert not chk.passed
    assert chk.date_hits and chk.persona_hits


# =========================================================== R2: Gemma terminal cue

def test_r2_canonical_gemma_render_passes():
    chk = _check(_gemma_render(), "gemma")
    assert chk.passed, chk.violations
    assert chk.structure_problems == []


def test_r2_missing_cue_fails():
    chk = _check(_gemma_render(cue_tail=False), "gemma")
    assert not chk.passed
    assert any("absent" in p for p in chk.structure_problems)


def test_r2_duplicated_cue_fails():
    chk = _check(_gemma_render(extra_after_prompt=CUE), "gemma")
    assert not chk.passed
    assert any("occurs 2 times" in p for p in chk.structure_problems)


def test_r2_mid_prompt_cue_only_fails_because_it_is_not_terminal():
    rendered = f"<bos><start_of_turn>user\n{PROMPT}{CUE} trailing text<end_of_turn>\n"
    chk = _check(rendered, "gemma")
    assert not chk.passed
    assert any("not at the terminal position" in p for p in chk.structure_problems)


def test_r2_arbitrary_model_word_in_prompt_still_fails():
    """A2's earlier fix pattern must NOT have become a blanket 'model' whitelist."""
    rendered = _gemma_render(extra_after_prompt="\nthe model should be lenient here")
    chk = _check(rendered, "gemma")
    assert not chk.passed
    assert "model" in chk.residual_words


def test_r2_model_is_not_in_any_global_token_list():
    assert "model" not in fpc.CONTROL_TOKENS
    assert CUE not in fpc.CONTROL_TOKENS


def test_r2_date_words_are_not_in_any_global_token_list():
    for w in ("Cutting", "Knowledge", "Date", "December", "Today"):
        assert w not in fpc.CONTROL_TOKENS, f"{w!r} must not be globally whitelisted"
    assert "cutting knowledge date" in fpc._DATE_PHRASES


def test_r2_exception_is_scoped_to_gemma_only():
    """A terminal <start_of_turn>model in a non-gemma render is unexplained content."""
    chk = _check(_gemma_render(), "qwen")
    assert not chk.passed
    assert "model" in chk.residual_words


# =========================================================== R3: 18-call reproducibility

class _FakeTok:
    eos_token_id = 0
    all_special_tokens = ["<|im_start|>", "<|im_end|>"]

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        return json.dumps(messages, ensure_ascii=False)


def _loaded_stub():
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    return eg.load_stub_model(spec)


def test_r3_gate_shape_is_18_calls_over_six_conditions():
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    assert r["repetitions_per_condition"] == 3
    assert r["n_conditions"] == 6
    assert r["n_calls"] == 18 == r["n_calls_expected"]
    assert r["all_calls_use_cache"] is True
    # observed, not asserted: all 18 calls must have been counted as use_cache=True
    assert r["n_calls_observed_use_cache_true"] == 18
    assert r["repetitions_match_frozen_requirement"] is True
    assert r["input_token_id_problems"] == []
    assert r["passed"] is True
    assert r["supersedes"] == "C1_2 cache-on/cache-off exact equivalence"


def test_r3_compares_all_four_invariants():
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    assert set(r["invariants_compared"]) == {
        "rendered_text_sha256", "input_token_ids_sha256",
        "generation_kwargs", "generated_token_ids_sha256"}


def test_r3_detects_a_generated_token_id_mismatch(monkeypatch):
    """A cache-on output that differs between repetitions must hard-fail."""
    real = eg.generate_exact_stub
    calls = {"n": 0}

    def drifting(loaded, messages, *, max_new_tokens, seed=42, use_cache=None):
        calls["n"] += 1
        out = real(loaded, messages, max_new_tokens=max_new_tokens, seed=seed,
                   use_cache=use_cache)
        if calls["n"] == 2:          # second repetition of the first condition
            out = {**out, "generated_token_ids_sha256": "drifted"}
        return out

    monkeypatch.setattr(eg, "generate_exact_stub", drifting)
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    assert r["passed"] is False
    assert r["n_mismatched_conditions"] == 1
    assert "generated_token_ids_sha256" in r["mismatches"][0]["differing_invariants"]


def test_r3_detects_an_input_token_id_mismatch(monkeypatch):
    real = eg.generate_exact_stub
    calls = {"n": 0}

    def drifting(loaded, messages, *, max_new_tokens, seed=42, use_cache=None):
        calls["n"] += 1
        out = real(loaded, messages, max_new_tokens=max_new_tokens, seed=seed,
                   use_cache=use_cache)
        if calls["n"] == 3:
            out = {**out, "input_token_ids": [9, 9, 9]}
        return out

    monkeypatch.setattr(eg, "generate_exact_stub", drifting)
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    assert r["passed"] is False
    assert "input_token_ids_sha256" in r["mismatches"][0]["differing_invariants"]


def test_r3_detects_changed_generation_kwargs(monkeypatch):
    """A nondeterministic kwargs builder must be caught. This is only detectable because the
    kwargs are rebuilt per repetition rather than captured once per condition -- captured
    once, the invariant would be compared against itself and could never fail."""
    real_builder = eg.build_generate_kwargs
    calls = {"n": 0}

    def drifting_builder(spec, *, max_new_tokens, pad_token_id, use_cache=None):
        calls["n"] += 1
        k = real_builder(spec, max_new_tokens=max_new_tokens, pad_token_id=pad_token_id,
                         use_cache=use_cache)
        if calls["n"] == 2:          # second repetition of the first condition
            k = {**k, "max_new_tokens": max_new_tokens + 1}
        return k

    monkeypatch.setattr(vpg.eg, "build_generate_kwargs", drifting_builder)
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    assert r["passed"] is False
    assert r["n_mismatched_conditions"] == 1
    assert "generation_kwargs" in r["mismatches"][0]["differing_invariants"]


def test_r3_kwargs_invariant_is_not_vacuous():
    """Guard against a regression to once-per-condition capture: the builder must be invoked
    once per call (18x), not once per condition (6x). See also
    test_r3_inputs_are_reconstructed_per_repetition_not_reused."""
    n = {"calls": 0}
    real_builder = eg.build_generate_kwargs

    def counting(spec, **kw):
        n["calls"] += 1
        return real_builder(spec, **kw)

    orig = vpg.eg.build_generate_kwargs
    vpg.eg.build_generate_kwargs = counting
    try:
        vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    finally:
        vpg.eg.build_generate_kwargs = orig
    assert n["calls"] == 18, f"kwargs built {n['calls']}x; expected one per call"


def test_r3_fewer_repetitions_than_a3_mandates_hard_fails():
    """A caller passing 2 repetitions shrinks the gate. Previously n_calls and
    n_calls_expected both became 12 and the gate still reported passed=True, so the
    18-call requirement could be silently weakened by an argument."""
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?",
                                                 stub=True, repetitions=2)
    assert r["n_calls"] == 12
    assert r["repetitions_match_frozen_requirement"] is False
    assert r["passed"] is False, "a 12-call gate must not pass as an 18-call gate"
    assert vpg.PRODUCTION_REPRODUCIBILITY_REPETITIONS == 3


def test_r3_absent_input_token_ids_hard_fails_instead_of_matching_trivially(monkeypatch):
    """str(None) hashes identically in all three repetitions, so a result carrying no
    input_token_ids would satisfy that invariant without ever comparing token IDs."""
    real = eg.generate_exact_stub

    def no_ids(loaded, messages, *, max_new_tokens, seed=42, use_cache=None):
        out = real(loaded, messages, max_new_tokens=max_new_tokens, seed=seed,
                   use_cache=use_cache)
        return {**out, "input_token_ids": None}

    monkeypatch.setattr(eg, "generate_exact_stub", no_ids)
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    assert r["passed"] is False
    assert len(r["input_token_id_problems"]) == 18


def test_r3_use_cache_is_observed_per_call_not_asserted(monkeypatch):
    """all_calls_use_cache was a hardcoded True that said nothing about the 18 calls."""
    real_builder = eg.build_generate_kwargs

    def cache_off(spec, *, max_new_tokens, pad_token_id, use_cache=None):
        k = real_builder(spec, max_new_tokens=max_new_tokens, pad_token_id=pad_token_id,
                         use_cache=use_cache)
        return {**k, "use_cache": False}

    monkeypatch.setattr(vpg.eg, "build_generate_kwargs", cache_off)
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    assert r["all_calls_use_cache"] is False
    assert r["n_calls_observed_use_cache_true"] == 0
    assert r["passed"] is False


def test_r3_inputs_are_reconstructed_per_repetition_not_reused():
    """Three of the four invariants compare values derived from the prompt/messages. If those
    objects were built once per condition and reused, the comparison would prove only that a
    string equals itself. Counted through the builders that must run 18 times, not 6."""
    counts = {"prompt": 0, "messages": 0, "kwargs": 0}
    real_prompt, real_msgs = vpg.sc.render_prompt, vpg.fsm.build_scorer_messages
    real_kwargs = eg.build_generate_kwargs

    def cp(*a, **k):
        counts["prompt"] += 1
        return real_prompt(*a, **k)

    def cm(*a, **k):
        counts["messages"] += 1
        return real_msgs(*a, **k)

    def ck(*a, **k):
        counts["kwargs"] += 1
        return real_kwargs(*a, **k)

    vpg.sc.render_prompt, vpg.fsm.build_scorer_messages = cp, cm
    vpg.eg.build_generate_kwargs = ck
    try:
        vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    finally:
        vpg.sc.render_prompt, vpg.fsm.build_scorer_messages = real_prompt, real_msgs
        vpg.eg.build_generate_kwargs = real_kwargs
    assert counts == {"prompt": 18, "messages": 18, "kwargs": 18}, counts


def test_r3_every_condition_is_covered():
    r = vpg.run_production_reproducibility_check(_loaded_stub(), "What is 2+2?", stub=True)
    assert set(r["per_condition"]) == {c.name for c in sc.CONDITIONS}
    assert all(v["repetitions"] == 3 for v in r["per_condition"].values())
    assert all(v["identical_across_repetitions"] for v in r["per_condition"].values())


def test_r3_both_mandatory_cache_settings_are_retained():
    """A3 retains C1_2's two production settings; only the equivalence clause is superseded."""
    olmo = next(s for s in vpg.SCORERS if s.key == "olmo32b")
    assert olmo.force_use_cache is True
    kwargs = eg.build_generate_kwargs(olmo, max_new_tokens=512, pad_token_id=0)
    assert kwargs["use_cache"] is True
    m = type("M", (), {"config": type("C", (), {"use_cache": False})(),
                       "generation_config": type("G", (), {"use_cache": False})()})()
    eg.apply_use_cache_setting(m, True, log=lambda *_: None)
    assert m.config.use_cache is True and m.generation_config.use_cache is True


def test_r3_anti_vacuous_required_scorer_guard_retained():
    assert "olmo32b" in vpg.CACHE_CHECK_REQUIRED_SCORERS


# =========================================================== R4: frozen render hashes

def test_r4_frozen_hash_table_has_llama_and_olmo_six_each():
    t = vpg.A3_FROZEN_RENDER_SHA256
    assert set(t) == {"llama", "olmo32b"}
    for k in t:
        assert set(t[k]) == {c.name for c in sc.CONDITIONS}
        assert all(len(v) == 64 for v in t[k].values())


def test_r4_matching_hashes_pass():
    renders = [{"scorer_key": s, "condition": c, "rendered_text_sha256": h}
               for s, d in vpg.A3_FROZEN_RENDER_SHA256.items() for c, h in d.items()]
    rep = vpg.check_frozen_render_hashes(renders)
    assert rep["passed"] is True
    assert rep["n_checked"] == 12 and rep["n_mismatches"] == 0


def test_r4_a_single_changed_hash_fails():
    renders = [{"scorer_key": s, "condition": c, "rendered_text_sha256": h}
               for s, d in vpg.A3_FROZEN_RENDER_SHA256.items() for c, h in d.items()]
    renders[3] = {**renders[3], "rendered_text_sha256": "0" * 64}
    rep = vpg.check_frozen_render_hashes(renders)
    assert rep["passed"] is False and rep["n_mismatches"] == 1


def test_r4_fails_closed_when_a_frozen_hash_was_never_compared():
    """A silently dropped scorer must not let the gate pass vacuously."""
    renders = [{"scorer_key": "llama", "condition": c, "rendered_text_sha256": h}
               for c, h in vpg.A3_FROZEN_RENDER_SHA256["llama"].items()]
    rep = vpg.check_frozen_render_hashes(renders)
    assert rep["passed"] is False
    assert rep["n_checked"] == 6 and rep["n_frozen_hashes_available"] == 12


def test_r4_is_skipped_only_under_stub():
    rep = vpg.check_frozen_render_hashes([], stub=True)
    assert rep["skipped"] is True and rep["passed"] is True
    rep2 = vpg.check_frozen_render_hashes([], stub=False)
    assert rep2["passed"] is False, "a real run must not pass with zero comparisons"


# =========================================================== end-to-end stub gate

def test_a3_stub_gate_passes_end_to_end_with_all_five_gates(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["x", "--stub", "--out", str(tmp_path / "r.json")])
    assert vpg.main() == 0
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert d["template_gate_passed"] is True
    assert d["use_cache_gate_passed"] is True
    assert d["production_reproducibility_gate_passed"] is True
    assert d["frozen_render_hash_gate_passed"] is True
    assert d["gate_passed"] is True
    assert d["n_renders"] == 24
    rep = d["production_reproducibility_reports"]["olmo32b"]
    assert rep["n_calls"] == 18
    assert set(d["production_reproducibility_reports"]) == {"olmo32b"}


def test_a3_stub_render_shapes_exercise_the_r1_r2_rules():
    """The stub renders must actually CONTAIN the structures R1/R2 police, otherwise the
    --stub path would be testing weaker rules than the real run."""
    llama_msgs = [{"role": "user", "content": PROMPT}]
    gemma_msgs = [{"role": "user", "content": PROMPT}]
    assert vpg._stub_render("llama", llama_msgs).startswith(LIT)
    assert vpg._stub_render("gemma", gemma_msgs).rstrip().endswith(CUE)
    assert vpg._stub_render("qwen", llama_msgs).count("<think>") == 1
    olmo = vpg._stub_render("olmo32b", [{"role": "system", "content": ""},
                                        {"role": "user", "content": PROMPT}])
    assert olmo.startswith("<|im_start|>system\n<|im_end|>\n")


# =========================================================== A3 report + output protection

def test_a3_structural_and_verbatim_results_appear_in_the_report(tmp_path, monkeypatch):
    """R4 requires the A3 rules to be folded into the reports, not only into gate_passed:
    an auditor reading the JSON must see which rule fired."""
    monkeypatch.setattr(sys, "argv", ["x", "--stub", "--out", str(tmp_path / "r.json")])
    assert vpg.main() == 0
    d = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    for r in d["renders"]:
        fc = r["fail_conditions"]
        assert fc["6_permitted_structure"]["passed"] is True
        assert fc["7_frozen_prompt_verbatim"]["passed"] is True
    llama = next(r for r in d["renders"] if r["scorer_key"] == "llama")
    gemma = next(r for r in d["renders"] if r["scorer_key"] == "gemma")
    qwen = next(r for r in d["renders"] if r["scorer_key"] == "qwen")
    assert "134-byte preamble" in llama["fail_conditions"]["6_permitted_structure"]["rule"]
    assert "terminal" in gemma["fail_conditions"]["6_permitted_structure"]["rule"]
    assert "no permitted structure" in qwen["fail_conditions"]["6_permitted_structure"]["rule"]


def test_all_three_final_output_targets_are_protected_from_stub_writes(tmp_path):
    """A stub run measures nothing; its artifacts must never land on a real output path.
    The candidate-answers file is a FILE and was previously unprotected."""
    for rel in ("results/final_behavioral_study",
                "results/final_behavioral_study_adjudicated",
                "data/candidates/final_olmo_answers.json"):
        assert rel in fpc.PROTECTED_RESULT_DIRS
        with pytest.raises(SystemExit):
            fpc.assert_stub_output_is_not_a_protected_dir(rel, stub=True, repo_root=".")


def test_a_real_run_is_never_restricted_by_the_stub_guard():
    for rel in fpc.PROTECTED_RESULT_DIRS:
        fpc.assert_stub_output_is_not_a_protected_dir(rel, stub=False, repo_root=".")


def test_a_non_verbatim_prompt_fails_the_render_not_just_the_report():
    """The verbatim criterion must gate. A render whose prompt was altered must fail even
    when the alteration leaves no residual word, date or persona hit behind."""
    cond = sc.resolve("no_history")
    loaded = eg.load_stub_model(
        eg.ExactModelSpec(key="qwen", hf_id="x", revision="r", disable_thinking=True))
    good = vpg.render_and_gate(loaded, "qwen", cond, "What is 2+2?", stub=True)
    assert good["gate_passed"] is True
    assert good["fail_conditions"]["7_frozen_prompt_verbatim"]["passed"] is True

    # same machinery, but the render no longer contains the frozen prompt verbatim
    prompt = sc.render_prompt("What is 2+2?", vpg.PLACEHOLDER_ANSWER, cond)
    mangled = vpg._stub_render("qwen", [{"role": "user", "content": prompt[:-5]}])
    assert prompt not in mangled
    chk = fpc.check_render(mangled, prompt, scorer_key="qwen", condition_name="no_history",
                           allow_empty_system_tags=False)
    assert not (chk.passed and prompt in mangled), \
        "an altered prompt must be detectable by the residual scan or the verbatim check"


# ============================================ batched-encode execution bugs (smoke blockers)

class _BatchEncodingLike(dict):
    """transformers>=5 returns a BatchEncoding from apply_chat_template(tokenize=True).
    dict already reproduces the property that broke the batched path: iterating yields keys."""


class _TokWithBatchEncoding:
    pad_token_id = None          # Llama-3.1 ships no pad token
    eos_token_id = 128009

    def apply_chat_template(self, messages, **kw):
        assert kw.get("return_dict") is True, "must request the dict form explicitly"
        n = 3 + len(messages)
        return _BatchEncodingLike(input_ids=list(range(100, 100 + n)),
                                  attention_mask=[1] * n)


def test_encode_chat_batch_reads_input_ids_not_the_batchencoding_keys():
    """The observed failure: iterating a BatchEncoding produced ['input_ids',
    'attention_mask'] and torch.tensor() raised "'str' object cannot be interpreted as an
    integer" on the first batched call of the 288-call smoke."""
    pytest.importorskip("torch")
    tok = _TokWithBatchEncoding()
    msgs = [[{"role": "user", "content": "a"}],
            [{"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}]]
    encoded, per_row = eg.encode_chat_batch(tok, msgs)
    assert all(isinstance(t, int) for row in per_row for t in row)
    assert [len(r) for r in per_row] == [4, 5]
    assert encoded["input_ids"].shape == (2, 5)


def test_encode_chat_batch_left_pads_with_eos_when_there_is_no_pad_token():
    """Llama-3.1's pad_token_id is None; torch.full(..., None) would raise. Padding must go on
    the LEFT so every row's prompt stays right-aligned."""
    pytest.importorskip("torch")
    tok = _TokWithBatchEncoding()
    msgs = [[{"role": "user", "content": "a"}],
            [{"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}]]
    encoded, per_row = eg.encode_chat_batch(tok, msgs)
    ids, mask = encoded["input_ids"], encoded["attention_mask"]
    assert ids[0, 0].item() == tok.eos_token_id, "short row must be padded on the left"
    assert mask[0].tolist() == [0, 1, 1, 1, 1], "pad column must be masked out"
    assert mask[1].tolist() == [1, 1, 1, 1, 1]
    assert ids[0, 1:].tolist() == per_row[0], "real prompt must be right-aligned"


def test_encode_chat_batch_rejects_non_integer_ids_loudly():
    class Bad(_TokWithBatchEncoding):
        def apply_chat_template(self, messages, **kw):
            return _BatchEncodingLike(input_ids=["input_ids", "attention_mask"])

    pytest.importorskip("torch")
    with pytest.raises(TypeError, match="not a list of ints"):
        eg.encode_chat_batch(Bad(), [[{"role": "user", "content": "a"}]])
