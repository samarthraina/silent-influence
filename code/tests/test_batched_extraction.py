"""Batched decoder-only generation: extraction correctness with UNEQUAL-length inputs.

For left-padded decoder-only batching, generated tokens start at the common padded input
width for every row -- `batch_input_ids.shape[1]` -- not at each row's own non-padding length.
Slicing per row is the classic error: it makes short rows appear to have generated the tail of
their own prompt padding, which shows up downstream as a batch-vs-single mismatch on exactly
the padded rows while the single longest (unpadded) row still matches.

These tests use inputs of deliberately different lengths so that per-row slicing cannot pass
them, and they assert exact equivalence -- nothing here relaxes it.
"""
from __future__ import annotations

import pytest

from silent_influence import exact_generation as eg

torch = pytest.importorskip("torch")

EOS = 99
PAD = EOS  # the production path passes pad_token_id=tokenizer.eos_token_id


class _Tok:
    """Tokenizes each conversation to a length driven by its content, so a batch built from
    different messages is genuinely ragged."""
    eos_token_id = EOS
    pad_token_id = None          # like Llama-3.1; encode_chat_batch must fall back to eos
    all_special_tokens = []

    def apply_chat_template(self, messages, **kw):
        n = len(messages[0]["content"])
        return {"input_ids": list(range(1000, 1000 + n)), "attention_mask": [1] * n}

    def decode(self, ids, skip_special_tokens=True, clean_up_tokenization_spaces=False):
        ids = [int(t) for t in (ids.tolist() if hasattr(ids, "tolist") else ids)]
        if skip_special_tokens:
            ids = [t for t in ids if t != EOS]
        return "".join(chr(65 + (t % 26)) for t in ids)


class _FakeGen:
    """Stands in for model.generate(). Echoes the padded input then appends a per-row
    continuation that depends ONLY on that row's real (non-padding) tokens, terminated by EOS
    and then pad-filled -- exactly the shape HF returns for a finished row in a batch that is
    still generating for other rows."""

    def __init__(self, tok):
        self.tok = tok
        self.config = type("C", (), {"use_cache": True})()
        self.generation_config = type("G", (), {"use_cache": True, "eos_token_id": EOS})()

    def parameters(self):
        yield torch.zeros(1)

    def generate(self, input_ids=None, attention_mask=None, **kw):
        max_new = kw["max_new_tokens"]
        rows = []
        for i in range(input_ids.shape[0]):
            real = [int(t) for t, m in zip(input_ids[i].tolist(),
                                           attention_mask[i].tolist()) if m == 1]
            # continuation length varies per row; always terminates before the ceiling
            k = 2 + (len(real) % 3)
            cont = [500 + (real[-1] % 7) + j for j in range(k)] + [EOS]
            cont += [PAD] * (max_new - len(cont))
            rows.append(input_ids[i].tolist() + cont)
        return torch.tensor(rows, dtype=torch.long)


def _loaded():
    spec = eg.ExactModelSpec(key="llama", hf_id="x", revision="r")
    tok = _Tok()
    return eg.LoadedModel(spec=spec, tokenizer=tok, model=_FakeGen(tok),
                          chat_template_sha256="x", attn_implementation="sdpa",
                          transformers_version="5.15.0")


def _msgs(*lengths):
    return [[{"role": "user", "content": "q" * n}] for n in lengths]


# ------------------------------------------------------------------ tokenization / masks

def test_batch_is_left_padded_with_mask_marking_only_real_tokens():
    tok = _Tok()
    msgs = _msgs(3, 7, 5)
    encoded, per_row = eg.encode_chat_batch(tok, msgs)
    ids, mask = encoded["input_ids"], encoded["attention_mask"]
    assert [len(r) for r in per_row] == [3, 7, 5]
    assert ids.shape == (3, 7), "padded width must be the longest row"
    for i, n in enumerate([3, 7, 5]):
        assert mask[i].tolist() == [0] * (7 - n) + [1] * n, f"row {i} not left-padded"
        assert ids[i, 7 - n:].tolist() == per_row[i], "real tokens must be right-aligned"
        assert all(t == tok.eos_token_id for t in ids[i, :7 - n].tolist())


def test_each_rows_non_padding_input_matches_its_batch_1_input():
    """The per-row comparison the investigation calls for: strip padding, compare to single."""
    tok = _Tok()
    msgs = _msgs(3, 7, 5)
    encoded, per_row = eg.encode_chat_batch(tok, msgs)
    for i, m in enumerate(msgs):
        single = eg.encode_chat_batch(tok, [m])[1][0]
        assert per_row[i] == single, f"row {i} non-padding input differs from batch-1"


# ------------------------------------------------------------------ generated-token slicing

def test_generated_tokens_start_at_the_common_padded_width_for_every_row():
    """The core correctness property. Under per-row slicing the short rows would carry a
    prefix of their own prompt tokens into 'generated', which this asserts against."""
    loaded = _loaded()
    msgs = _msgs(3, 7, 5)
    out = eg.generate_exact_batch(loaded, msgs, max_new_tokens=16)
    assert len(out) == 3
    for i, r in enumerate(out):
        gen = r["generated_token_ids_raw"]
        # nothing from the prompt may appear in the generated span
        assert all(t < 1000 for t in gen), f"row {i} leaked prompt tokens into generated: {gen}"
        # and the first generated token is a continuation token, not a prompt or pad token
        assert 500 <= gen[0] < 600, f"row {i} first generated token wrong: {gen[0]}"


def test_batched_generation_is_token_identical_to_batch_1_on_ragged_input():
    loaded = _loaded()
    msgs = _msgs(3, 7, 5, 4)
    batched = eg.generate_exact_batch(loaded, msgs, max_new_tokens=16)
    for i, m in enumerate(msgs):
        single = eg.generate_exact_batch(loaded, [m], max_new_tokens=16)[0]
        assert batched[i]["generated_token_ids_trimmed"] == \
            single["generated_token_ids_trimmed"], f"row {i} token mismatch"
        assert batched[i]["generated_token_ids_sha256"] == single["generated_token_ids_sha256"]
        assert batched[i]["text"] == single["text"], f"row {i} text mismatch"


def test_per_row_slicing_would_fail_this_suite():
    """Guards the guard: demonstrates that the incorrect slicing this suite is designed to
    catch really does produce a mismatch, so a future regression cannot pass silently."""
    loaded = _loaded()
    msgs = _msgs(3, 7, 5)
    encoded, per_row = eg.encode_chat_batch(loaded.tokenizer, msgs)
    generated = loaded.model.generate(input_ids=encoded["input_ids"],
                                      attention_mask=encoded["attention_mask"],
                                      max_new_tokens=16)
    padded_w = encoded["input_ids"].shape[1]
    correct = [generated[i, padded_w:].tolist() for i in range(len(per_row))]
    wrong = [generated[i, len(per_row[i]):].tolist() for i in range(len(per_row))]
    # the longest row is unpadded, so correct and wrong agree there and nowhere else --
    # precisely the "one row matches, the rest differ" signature seen in the 288-call smoke
    agree = [c == w for c, w in zip(correct, wrong)]
    assert agree == [False, True, False], agree
    assert sum(agree) == 1, "exactly the unpadded row should coincide under bad slicing"


# ------------------------------------------------------------------ EOS / trailing pad

def test_tokens_are_retained_through_the_first_eos_and_padding_after_it_is_dropped():
    loaded = _loaded()
    out = eg.generate_exact_batch(loaded, _msgs(3, 7), max_new_tokens=16)
    for r in out:
        trimmed = r["generated_token_ids_trimmed"]
        assert trimmed[-1] == EOS, "the terminator itself must be retained"
        assert trimmed.count(EOS) == 1, "only the first terminator, nothing after it"
        assert len(trimmed) < len(r["generated_token_ids_raw"]), "trailing pad must be dropped"
        assert r["output_tokens"] == len(trimmed)


def test_a_row_that_never_terminates_keeps_its_full_generation():
    class _NoStop(_FakeGen):
        def generate(self, input_ids=None, attention_mask=None, **kw):
            max_new = kw["max_new_tokens"]
            rows = [input_ids[i].tolist() + [700 + j for j in range(max_new)]
                    for i in range(input_ids.shape[0])]
            return torch.tensor(rows, dtype=torch.long)

    loaded = _loaded()
    loaded.model.__class__ = _NoStop
    out = eg.generate_exact_batch(loaded, _msgs(3, 7), max_new_tokens=8)
    for r in out:
        assert r["generated_token_ids_trimmed"] == r["generated_token_ids_raw"]
        assert len(r["generated_token_ids_raw"]) == 8


# ------------------------------------------------------------------ A5 interaction

def test_a5_validity_is_reported_on_the_batched_path():
    """Regression: emitted_terminator referenced an out-of-scope name, so every batched call
    raised NameError. No stub test reached this code."""
    loaded = _loaded()
    out = eg.generate_exact_batch(loaded, _msgs(3, 7, 5), max_new_tokens=16)
    for r in out:
        assert r["emitted_terminator"] is True
        assert r["hit_token_cap"] is False


def test_a5_marks_a_non_terminating_batched_row_capped_incomplete():
    from silent_influence import output_validity as ov

    class _NoStop(_FakeGen):
        def generate(self, input_ids=None, attention_mask=None, **kw):
            max_new = kw["max_new_tokens"]
            rows = [input_ids[i].tolist() + [700 + j for j in range(max_new)]
                    for i in range(input_ids.shape[0])]
            return torch.tensor(rows, dtype=torch.long)

    loaded = _loaded()
    loaded.model.__class__ = _NoStop
    out = eg.generate_exact_batch(loaded, _msgs(3, 7), max_new_tokens=8)
    for r in out:
        assert r["emitted_terminator"] is False
        rec = {**r, "parse_ok": True, "parsed_score": 7.0, "parse_status": "ok"}
        assert ov.is_capped_incomplete(rec) is True
        assert ov.is_valid(rec) is False
        assert ov.analysis_score(rec) is None, "A5 must hold on the batched path too"
