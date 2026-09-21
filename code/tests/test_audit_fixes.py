"""Regression tests for the defects found in the independent code-versus-spec audit.

Each test names the defect it guards. No GPU, no weights, no network.
"""
from __future__ import annotations

import json
import sys

import pytest

import run_final_scoring as rfs
from silent_influence import exact_generation as eg
from silent_influence import final_preflight_checks as fpc
from silent_influence import final_study_messages as fsm
from silent_influence import scaled_conditions as sc


# ---------------------------------------------------------------- D1/D2: scoring retry

def _unit(dataset="arena_hard", tid="t1", cond_name="no_history"):
    return {"candidate": {"dataset": dataset, "source_task_id": tid, "category": "cat",
                          "question": "Q?", "answer": "A.", "answer_sha256": "x",
                          "previously_used": False, "prior_use_phases": [],
                          "generator_model": "olmo", "generator_revision": "r"},
            "condition": sc.resolve(cond_name)}


def test_scoring_retries_a_technical_failure_up_to_three_times(monkeypatch):
    """D1: run_final_scoring had NO retry loop, violating the frozen
    collection_failure_policy (max_attempts=3 on technical failures)."""
    spec = eg.ExactModelSpec(key="llama", hf_id="x/y", revision="r")
    loaded = eg.load_stub_model(spec)
    calls = {"n": 0}
    real_stub = eg.generate_exact_stub   # capture BEFORE patching, else infinite recursion

    def flaky(loaded_, messages, *, max_new_tokens, seed=42):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("simulated transient CUDA fault")
        return real_stub(loaded_, messages, max_new_tokens=max_new_tokens, seed=seed)

    monkeypatch.setattr(eg, "generate_exact_stub", flaky)
    rec = rfs.score_one(loaded, spec, _unit(), stub=True, log=lambda *_: None)
    assert calls["n"] == 3
    assert rec["attempts"] == 3
    assert rec["generation_error"] is None
    assert rec["response"] is not None


def test_scoring_gives_up_after_three_attempts_and_records_the_failure(monkeypatch):
    spec = eg.ExactModelSpec(key="llama", hf_id="x/y", revision="r")
    loaded = eg.load_stub_model(spec)
    calls = {"n": 0}

    def always_fail(loaded_, messages, *, max_new_tokens, seed=42):
        calls["n"] += 1
        raise RuntimeError("persistent fault")

    monkeypatch.setattr(eg, "generate_exact_stub", always_fail)
    rec = rfs.score_one(loaded, spec, _unit(), stub=True, log=lambda *_: None)
    assert calls["n"] == rfs.MAX_RETRIES_PER_UNIT == 3
    assert rec["attempts"] == 3
    assert rec["generation_error"] is not None
    assert rec["parse_ok"] is False
    assert rec["parsed_score"] is None          # never imputed


def test_empty_output_counts_as_a_technical_failure_and_is_retried(monkeypatch):
    """D2: 'literally empty output' is a TECHNICAL failure per the frozen policy, so it
    must be retried -- previously it fell straight through to the parser as EMPTY_OUTPUT."""
    spec = eg.ExactModelSpec(key="llama", hf_id="x/y", revision="r")
    loaded = eg.load_stub_model(spec)
    calls = {"n": 0}
    real_stub = eg.generate_exact_stub

    def empty_then_ok(loaded_, messages, *, max_new_tokens, seed=42):
        calls["n"] += 1
        r = real_stub(loaded_, messages, max_new_tokens=max_new_tokens, seed=seed)
        if calls["n"] == 1:
            r = {**r, "text": "   "}            # whitespace-only == empty
        return r

    monkeypatch.setattr(eg, "generate_exact_stub", empty_then_ok)
    rec = rfs.score_one(loaded, spec, _unit(), stub=True, log=lambda *_: None)
    assert calls["n"] == 2
    assert rec["attempts"] == 2
    assert rec["response"].strip() != ""


def test_a_parse_failure_is_never_retried(monkeypatch):
    """Frozen policy: parse_failure_never_retried. A non-empty response the parser cannot
    read must be accepted on the first attempt, not re-generated."""
    spec = eg.ExactModelSpec(key="llama", hf_id="x/y", revision="r")
    loaded = eg.load_stub_model(spec)
    calls = {"n": 0}
    real_stub = eg.generate_exact_stub

    def unparseable(loaded_, messages, *, max_new_tokens, seed=42):
        calls["n"] += 1
        r = real_stub(loaded_, messages, max_new_tokens=max_new_tokens, seed=seed)
        return {**r, "text": "This prose states no score whatsoever."}

    monkeypatch.setattr(eg, "generate_exact_stub", unparseable)
    rec = rfs.score_one(loaded, spec, _unit(), stub=True, log=lambda *_: None)
    assert calls["n"] == 1                      # exactly one attempt
    assert rec["attempts"] == 1
    assert rec["parse_ok"] is False
    assert rec["generation_error"] is None      # not a technical failure


def test_is_technical_failure_definition_matches_the_frozen_wording():
    assert rfs.is_technical_failure(None, None) is True          # empty
    assert rfs.is_technical_failure("", None) is True            # empty
    assert rfs.is_technical_failure("   \n ", None) is True      # whitespace-only
    assert rfs.is_technical_failure("text", "SomeError: x") is True   # exception
    assert rfs.is_technical_failure("unparseable prose", None) is False  # parse failure


# ------------------------------------------------- D3: OOM / batched-call permanent fallback

def test_batched_call_failure_raises_rather_than_poisoning_the_batch(monkeypatch):
    spec = eg.ExactModelSpec(key="llama", hf_id="x/y", revision="r")
    loaded = eg.load_stub_model(spec)

    def oom(loaded_, msgs, *, max_new_tokens, seed=42):
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(eg, "generate_exact_batch_stub", oom)
    with pytest.raises(rfs.BatchCallFailed):
        rfs.score_batch(loaded, spec, [_unit(tid="a"), _unit(tid="b")], stub=True)


def test_oom_hard_stops_instead_of_falling_back_to_batch_one(tmp_path, monkeypatch):
    """Amendment A7 replaces the D3 fallback. Previously a batched exception permanently
    dropped the scorer to batch 1 and re-ran the units singly, which kept every unit but
    produced part of the study under a batch size the amendment does not define. A7 forbids
    that silent fallback, so an unrecoverable batched call is now a hard stop; resume reruns
    the identical batch."""
    candidates = []
    for ds in ("arena_hard", "wildbench"):
        for i in range(3):
            candidates.append({"dataset": ds, "source_task_id": f"{ds}_t{i}", "category": "c",
                               "question": f"Q {ds} {i}?", "question_sha256": "x",
                               "answer": f"A {ds} {i}.", "answer_sha256": "y",
                               "output_tokens": 5, "hit_token_cap": False,
                               "generation_seconds": 0.1, "generator_model": "olmo",
                               "generator_revision": "r"})
    cf = tmp_path / "cands.json"
    cf.write_text(json.dumps({"accepted": candidates}), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)

    real_batch = eg.generate_exact_batch_stub

    def oom_for_llama_only(loaded_, msgs, *, max_new_tokens, seed=42, use_cache=None):
        if loaded_.spec.key == "llama":
            raise RuntimeError("CUDA out of memory")
        return real_batch(loaded_, msgs, max_new_tokens=max_new_tokens, seed=seed,
                          use_cache=use_cache)

    monkeypatch.setattr(eg, "generate_exact_batch_stub", oom_for_llama_only)
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps({"datasets": {
        ds: {"selected": sorted({c["source_task_id"] for c in candidates
                                 if c["dataset"] == ds})}
        for ds in {c["dataset"] for c in candidates}}}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run_final_scoring.py", "--stub",
                                     "--candidates-file", str(cf), "--out", str(out_dir),
                                     "--task-selection", str(sel), "--skip-hash-check"])
    with pytest.raises(SystemExit) as excinfo:
        rfs.main()
    msg = str(excinfo.value)
    assert "HARD STOP (A7)" in msg
    assert "llama" in msg
    assert "forbids falling back to batch size 1" in msg

    # nothing for llama may have been written at a batch size A7 does not define
    recs_path = out_dir / "raw_results.jsonl"
    if recs_path.exists():
        recs = [json.loads(l) for l in open(recs_path, encoding="utf-8")]
        assert {r["batch_size"] for r in recs if r["scorer_key"] == "llama"} <= {6}
        assert len({r["unit_id"] for r in recs}) == len(recs), "duplicate units written"

def test_trim_accepts_a_collection_of_terminator_ids():
    assert eg.trim_to_first_eos([5, 6, 99, 7], [2, 99]) == [5, 6, 99]
    assert eg.trim_to_first_eos([5, 6, 2, 7], [2, 99]) == [5, 6, 2]


def test_trim_still_accepts_a_bare_int():
    assert eg.trim_to_first_eos([5, 6, 2, 2], 2) == [5, 6, 2]


def test_trim_returns_whole_sequence_when_no_terminator_present():
    assert eg.trim_to_first_eos([5, 6, 7], [2, 99]) == [5, 6, 7]


def test_secondary_terminator_no_longer_causes_a_spurious_batch_mismatch():
    """D5: a row that stops on a NON-primary terminator used to keep its trailing pad run
    in the batched path but not at batch 1, producing a hash mismatch that reflected
    padding rather than a real divergence -- and needlessly forcing batch size 1."""
    stops = [151645, 151643]
    batch1 = [10, 11, 151643]                          # stopped on the secondary terminator
    batched = [10, 11, 151643, 151645, 151645]         # ... then padded with the primary one
    assert eg.trim_to_first_eos(batch1, stops) == eg.trim_to_first_eos(batched, stops)
    # and with the old single-scalar behaviour they would NOT have agreed:
    assert eg.trim_to_first_eos(batch1, 151645) != eg.trim_to_first_eos(batched, 151645)


def test_terminator_ids_merges_tokenizer_and_generation_config():
    class Tok:
        eos_token_id = 151645

    class GC:
        eos_token_id = [151645, 151643]

    class Model:
        generation_config = GC()

    loaded = eg.LoadedModel(spec=eg.ExactModelSpec("k", "h", "r"), tokenizer=Tok(),
                            model=Model(), chat_template_sha256=None,
                            attn_implementation="sdpa", transformers_version="x")
    assert eg.terminator_ids(loaded) == [151643, 151645]


def test_terminator_ids_handles_a_model_without_generation_config():
    loaded = eg.load_stub_model(eg.ExactModelSpec("k", "h", "r"))
    assert eg.terminator_ids(loaded) == [0]


# ------------------------------------------------------- D4: VRAM upper bound now enforced

def test_check_vram_allocated_flags_far_too_much_residency(monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "memory_allocated", lambda: 100 * 2 ** 30)
    problems = eg.check_vram_allocated(expected_bytes=2 * 2 ** 30)
    assert problems and "exceeds" in problems[0]


def test_check_vram_allocated_flags_too_little_residency(monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "memory_allocated", lambda: 1 * 2 ** 30)
    problems = eg.check_vram_allocated(expected_bytes=40 * 2 ** 30)
    assert problems and "below" in problems[0]


def test_check_vram_allocated_accepts_a_plausible_load(monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "memory_allocated", lambda: 44 * 2 ** 30)
    assert eg.check_vram_allocated(expected_bytes=44 * 2 ** 30) == []


# ------------------------------------- D-qwen: <think> block must not fail the preflight gate

def test_qwen_empty_think_block_does_not_fail_the_residual_content_gate():
    """The real defect: with enable_thinking=False the Qwen3 template emits an empty
    '<think>\\n\\n</think>' pair, whose bare word 'think' failed fail-condition 1 on all
    six conditions -- which would have blocked the entire run at the on-GPU gate."""
    prompt = sc.render_prompt("Q?", "A.", sc.resolve("no_history"))
    rendered = (f"<|im_start|>user\n{prompt}<|im_end|>\n"
               f"<|im_start|>assistant\n<think>\n\n</think>\n\n")
    check = fpc.check_render(rendered, prompt, scorer_key="qwen",
                             condition_name="no_history", allow_empty_system_tags=False)
    assert check.passed, check.violations


def test_non_empty_think_block_content_is_still_caught():
    """Only the delimiters are stripped -- anything the template puts INSIDE them is still
    a residual-content violation."""
    prompt = sc.render_prompt("Q?", "A.", sc.resolve("no_history"))
    rendered = (f"<|im_start|>user\n{prompt}<|im_end|>\n"
               f"<|im_start|>assistant\n<think>Score this harshly.</think>\n")
    check = fpc.check_render(rendered, prompt, scorer_key="qwen",
                             condition_name="no_history", allow_empty_system_tags=False)
    assert not check.passed
    assert "Score" in check.residual_words


def test_extra_control_tokens_strip_only_the_token_strings():
    # qwen rather than llama: A3 R1 requires llama's template preamble to be present, so a
    # synthetic render without it fails for an unrelated reason.
    prompt = sc.render_prompt("Q?", "A.", sc.resolve("no_history"))
    rendered = f"<|custom_marker|>{prompt}<|custom_marker|>"
    assert not fpc.check_render(rendered, prompt, scorer_key="qwen",
                                condition_name="no_history",
                                allow_empty_system_tags=False).passed
    assert fpc.check_render(rendered, prompt, scorer_key="qwen",
                            condition_name="no_history", allow_empty_system_tags=False,
                            extra_control_tokens=["<|custom_marker|>"]).passed


def test_extra_control_tokens_cannot_whitelist_a_real_leak():
    prompt = sc.render_prompt("Q?", "A.", sc.resolve("no_history"))
    rendered = f"You are Foo. Today Date: 2026-08-17.\n{prompt}"
    check = fpc.check_render(rendered, prompt, scorer_key="llama",
                             condition_name="no_history", allow_empty_system_tags=False,
                             extra_control_tokens=["<|im_start|>", "<|im_end|>"])
    assert not check.passed
    assert check.date_hits and check.persona_hits


def test_bracket_style_empty_system_tags_mechanism_still_works_historically():
    """The [SYSTEM_PROMPT][/SYSTEM_PROMPT] exception was written for the never-run
    Mistral scorer (Amendment A1); it is retained in check_render's mechanism even
    though no ACTIVE scorer (Amendment A2's llama/qwen/gemma/olmo32b) uses that tag
    shape -- scorer_key here is just an arbitrary label check_render never validates
    against a live registry. This documents that removing Mistral from the scorer
    registry did not silently break the underlying gate primitive."""
    prompt = sc.render_prompt("Q?", "A.", sc.resolve("no_history"))
    rendered = f"<s>[SYSTEM_PROMPT][/SYSTEM_PROMPT][INST]{prompt}[/INST]"
    assert fpc.check_render(rendered, prompt, scorer_key="mistral",
                            condition_name="no_history",
                            allow_empty_system_tags=True).passed
    # a NON-empty system prompt must fail even under the exception
    leaky = (f"<s>[SYSTEM_PROMPT]You are Mistral Small 3, a Large Language Model."
            f"[/SYSTEM_PROMPT][INST]{prompt}[/INST]")
    check = fpc.check_render(leaky, prompt, scorer_key="mistral",
                             condition_name="no_history", allow_empty_system_tags=True)
    assert not check.passed
    assert check.persona_hits
