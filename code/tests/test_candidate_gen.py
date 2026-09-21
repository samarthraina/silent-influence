"""Model X answer-generation prompt.

Model X supplies the stimulus, not behaviour. The prompt must ask for a user-facing
answer and must not leak the evaluation framing, the judging rubric, or any identity —
otherwise the candidate text itself would carry part of the manipulation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from silent_influence.candidate_gen import (ANSWER_INSTRUCTION,  # noqa: E402
                                            ANSWER_SYSTEM_PROMPT,
                                            build_answer_messages, candidate_record)

Q = "Write a function that reverses a linked list and explain the invariant."


def test_messages_carry_an_explicit_system_turn():
    """OLMo-3 injects a function-calling persona when no system turn is supplied."""
    msgs = build_answer_messages(Q)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"].strip()
    assert msgs[1]["content"] == Q


def test_prompt_does_not_leak_the_evaluation_framing():
    text = " ".join(m["content"] for m in build_answer_messages(Q)).lower()
    for leak in ["rubric", "relevance", "reasoning_quality", "score", "/10",
                 "judge", "evaluator", "prior", "json", "earlier round"]:
        assert leak not in text, f"answer prompt leaks evaluation framing: {leak!r}"


def test_prompt_forbids_meta_content_but_allows_explanation():
    instr = ANSWER_INSTRUCTION.lower()
    for forbidden in ["scratch work", "self-correction", "hidden reasoning",
                      "planning notes", "commentary about your reasoning process"]:
        assert forbidden in instr
    # substantive explanation must remain permitted - the rubric scores reasoning
    assert "naturally required as part of the final answer are allowed" in instr


def test_prompt_names_no_model_or_vendor():
    text = " ".join(m["content"] for m in build_answer_messages(Q)).lower()
    for name in ["olmo", "allenai", "gemma", "llama", "qwen", "mistral", "gpt", "claude"]:
        assert name not in text, f"answer prompt names a model: {name!r}"


def test_question_is_passed_through_verbatim():
    weird = 'Q with "quotes", {braces}, \\backslash and\nnewline'
    assert build_answer_messages(weird)[1]["content"] == weird


def test_candidate_record_has_the_fields_the_loader_reads():
    r = candidate_record(dataset="d", prompt_id="1", candidate_response_id="c",
                         evaluated_model="m", text="t")
    assert set(r) == {"dataset", "prompt_id", "candidate_response_id",
                      "evaluated_model", "text"}


def test_system_prompt_is_a_single_stable_string():
    a = build_answer_messages(Q)[0]["content"]
    b = build_answer_messages("other")[0]["content"]
    assert a == b == f"{ANSWER_SYSTEM_PROMPT} {ANSWER_INSTRUCTION}"


def test_truncation_is_judged_on_true_generated_length():
    """Re-encoding the decoded string undercounts, which made a capped generation look
    like it stopped naturally (prompt 3 read 1022 against a 1024 cap)."""
    import types
    import torch
    from silent_influence.backends import GenParams, HFBackend

    class Tok:
        pad_token_id = 0
        def apply_chat_template(self, *a, **k): return "P"
        def __call__(self, t, return_tensors=None):
            return {"input_ids": torch.zeros((1, 7), dtype=torch.long)}
        def decode(self, g, skip_special_tokens=True): return "x" * 10

    class Model:
        device = "cpu"
        def generate(self, **kw):
            n = kw["max_new_tokens"]
            return torch.zeros((1, 7 + n), dtype=torch.long)

    sn = types.SimpleNamespace(spec=types.SimpleNamespace(chat_template_kwargs={}),
                               tokenizer=Tok(), model=Model(), _torch=torch)
    sn._apply_template = lambda s, u: HFBackend._apply_template(sn, s, u)
    sn._decode_from_text = lambda t, p, s: HFBackend._decode_from_text(sn, t, p, s)
    HFBackend.generate(sn, "S", "U", GenParams(max_new_tokens=1024, do_sample=False), 1)
    assert sn.last_new_tokens == 1024
    assert sn.last_prompt_tokens == 7
    assert sn.last_hit_cap is True, "a generation that ran to the cap must be flagged"


def test_rationale_replays_the_exchange_verbatim_and_asks_neutrally():
    """Phase 1B: the follow-up must not mention prior context, scores or influence,
    and the replayed turns must be the stored bytes, not re-rendered text."""
    from silent_influence.rationale import FOLLOWUP, build_messages, frozen_score

    rec = {"system_prompt": "SYS", "user_prompt": "USER-JUDGING-PROMPT",
           "raw_output": '{"relevance": 4, "reasoning_quality": 5}',
           "relevance": 4, "reasoning_quality": 5, "total": 4.5, "unit_id": "abc"}
    m = build_messages(rec)
    assert [x["role"] for x in m] == ["system", "user", "assistant", "user"]
    assert m[0]["content"] == rec["system_prompt"]
    assert m[1]["content"] == rec["user_prompt"]
    assert m[2]["content"] == rec["raw_output"]      # the committed score, verbatim
    assert m[3]["content"] == FOLLOWUP

    low = FOLLOWUP.lower()
    for leak in ["prior", "previous", "history", "influence", "affect", "bias",
                 "earlier round", "/10", "context", "other model"]:
        assert leak not in low, f"follow-up leaks the construct: {leak!r}"

    assert frozen_score(rec)["total"] == 4.5


def test_rationale_refuses_an_incomplete_record():
    import pytest as _pytest

    from silent_influence.rationale import build_messages
    for missing in ("system_prompt", "user_prompt", "raw_output"):
        rec = {"system_prompt": "s", "user_prompt": "u", "raw_output": "o"}
        rec[missing] = ""
        with _pytest.raises(ValueError):
            build_messages(rec)


def test_rationale_extractor_accepts_only_a_valid_rationale_object():
    from silent_influence.rationale import (R_EMPTY, R_MALFORMED, R_MISSING, R_OK,
                                            R_SCORE_FIELDS, R_TRUNCATED,
                                            extract_rationale)
    ok, val, _ = extract_rationale('{"rationale": "It answers fully."}')
    assert (ok, val) == (R_OK, "It answers fully.")
    assert extract_rationale('```json\n{"rationale": "x y z"}\n```')[0] == R_OK
    assert extract_rationale('prose {"rationale": "abc"} tail')[0] == R_OK

    assert extract_rationale('{"relevance": 8, "reasoning_quality": 7}')[0] == R_SCORE_FIELDS
    assert extract_rationale('{"rationale": "a", "relevance": 8}')[0] == R_SCORE_FIELDS
    assert extract_rationale('{"explanation": "a"}')[0] == R_MISSING
    assert extract_rationale('{"rationale": ""}')[0] == R_EMPTY
    assert extract_rationale('{"rationale": "   "}')[0] == R_EMPTY
    assert extract_rationale('{"rationale": 5}')[0] == R_MISSING
    assert extract_rationale("no json at all")[0] == R_MALFORMED
    assert extract_rationale('{"rationale": "unterminated')[0] == R_MALFORMED
    assert extract_rationale("")[0] == R_MALFORMED
    assert extract_rationale('{"rationale": "fine"}', hit_cap=True)[0] == R_TRUNCATED
    # a failing status must never hand back text to annotate
    for bad in ('{"relevance": 8}', '{"rationale": ""}', "junk"):
        assert extract_rationale(bad)[1] is None


def test_revised_followup_requests_json_without_cueing_the_construct():
    from silent_influence.rationale import FOLLOWUP
    low = FOLLOWUP.lower()
    assert '{"rationale"' in FOLLOWUP and "json" in low
    for leak in ["prior", "previous", "history", "influence", "affect", "bias",
                 "earlier round", "/10", "context", "other model"]:
        assert leak not in low, f"follow-up leaks the construct: {leak!r}"


def test_activation_span_location_handles_multitoken_numerals():
    from silent_influence.activations import locate_positions
    # a fake offset mapping: "... them 10/10." with the numeral split across two tokens
    text = "In an earlier round, X scored them 10/10. Now score this."
    ns = text.index("10/10")
    offsets = [(0, 3), (3, 20), (20, 35), (ns, ns + 1), (ns + 1, ns + 2),
               (ns + 2, ns + 5), (ns + 5, ns + 6), (ns + 6, len(text))]
    sp = locate_positions(text, offsets, "In an earlier round, X scored them ", 10)
    assert sp["score_span"].text == "10"
    assert sp["score_span"].token_indices == [3, 4], "must cover BOTH numeral tokens"
    assert sp["history_end"].token_indices == [6]
    assert sp["final_input"].token_indices == [len(offsets) - 1]


def test_activation_no_history_has_only_the_final_position():
    from silent_influence.activations import locate_positions
    sp = locate_positions("no history here.", [(0, 2), (2, 16)], None, None)
    assert sp["score_span"].token_indices == []
    assert sp["history_end"].token_indices == []
    assert sp["final_input"].token_indices == [1]


def test_read_split_is_deterministic_stratified_and_disjoint():
    from silent_influence.activations import stratified_split
    tasks = [("1", "coding"), ("2", "coding"), ("3", "math"), ("4", "math"),
             ("5", "creative"), ("6", "creative"), ("7", "coding"), ("8", "math")]
    a, b = stratified_split(tasks, seed=42)
    assert stratified_split(tasks, seed=42) == (a, b)          # deterministic
    assert not set(a) & set(b)                                  # disjoint
    assert sorted(a + b, key=int) == sorted([t for t, _ in tasks], key=int)
    assert len(a) == len(b) == len(tasks) // 2, "split must be exact halves"

    # the real Phase 2A shape: 6 coding, 5 math, 7 creative -> must be 9/9
    real = ([("%d" % i, "coding") for i in range(1, 7)]
            + [("%d" % i, "math") for i in range(7, 12)]
            + [("%d" % i, "creative_writing") for i in range(12, 19)])
    x, y = stratified_split(real, seed=42)
    assert len(x) == len(y) == 9, f"expected 9/9, got {len(x)}/{len(y)}"
    assert not set(x) & set(y)


def test_patch_hook_targets_the_same_state_phase2a_read():
    """L>=1 must hook layers[L-1] (post-block) so patching writes hidden_states[L]."""
    import types
    from silent_influence.patching import _module_for_layer
    m = types.SimpleNamespace(model=types.SimpleNamespace(
        embed_tokens="EMB", layers=[f"block{i}" for i in range(4)]))
    assert _module_for_layer(m, 0) == "EMB"
    assert _module_for_layer(m, 1) == "block0"
    assert _module_for_layer(m, 4) == "block3"


def test_patch_hook_skips_incremental_decoding_steps():
    """During generation the block sees one token; patching there would corrupt the
    generated text rather than the prompt."""
    import torch
    from silent_influence.patching import patch_positions

    class Blk(torch.nn.Module):
        def forward(self, x): return (x,)

    class M(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = types_ns(embed_tokens=Blk(), layers=[Blk()])

    import types as _t
    def types_ns(**kw): return _t.SimpleNamespace(**kw)

    m = M()
    vals = torch.full((2, 4), 9.0)
    prompt = torch.zeros(1, 6, 4)
    step = torch.zeros(1, 1, 4)
    with patch_positions(m, 1, [1, 2], vals):
        out_prompt = m.model.layers[0](prompt)[0]
        out_step = m.model.layers[0](step)[0]
    assert (out_prompt[0, [1, 2]] == 9.0).all(), "prompt positions must be patched"
    assert (out_prompt[0, [0, 3, 4, 5]] == 0.0).all(), "other positions must be untouched"
    assert (out_step == 0.0).all(), "single-token decode step must be untouched"
