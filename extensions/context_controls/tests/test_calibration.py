"""Calibration prompts, exact treatment invariance and the 360-unit manifest."""
import hashlib
import itertools
import json
import re
from collections import Counter

import pytest

from conftest import ART, EXT
from rba import calib as C, inputs as I, units as U


def test_manifest_is_full_factorial_with_unique_ids(calib_units, sample):
    assert len(calib_units) == 360
    assert len({u["unit_id"] for u in calib_units}) == 360
    cells = Counter((u["model_key"], u["rubric_id"], u["context"]) for u in calib_units)
    assert set(cells) == set(itertools.product(C.MODELS, C.RUBRICS, C.CONTEXTS))
    assert set(cells.values()) == {30}
    assert {u["base_task_id"] for u in calib_units} == {r["base_task_id"] for r in sample["selected"]}
    for u in calib_units:
        U.check_planned(u)
        assert all(u[k] is None for k in U.PENDING_RUNTIME_FIELDS)


def test_manifest_hash_file_matches():
    body = (ART / "calibration/run_manifest_v1.jsonl").read_bytes()
    rec = (ART / "calibration/run_manifest_v1.sha256").read_text().split()[0]
    assert hashlib.sha256(body).hexdigest() == rec


def test_original_prompts_identical_to_frozen_original_prompts(calib_units, tasks, frozen_by_unit):
    n = 0
    for u in calib_units:
        if u["rubric_id"] != "original":
            continue
        t = tasks[u["base_task_id"]]
        p = C.render(t["question"], t["answer"], u["context"], "original")["prompt"]
        h = frozen_by_unit[u["provenance"]["historical_unit_id"]]
        assert p == h["prompt"] and C.messages(u["model_key"], p) == h["messages"]
        assert C.sha256_text(p) == u["prompt_sha256"]
        n += 1
    assert n == 180


def test_explicit_arm_changes_only_the_rubric_block(sample, tasks):
    for r in sample["selected"]:
        t = tasks[r["base_task_id"]]
        C.assert_invariance(t["question"], t["answer"])
        for ctx in C.CONTEXTS:
            o = C.render(t["question"], t["answer"], ctx, "original")
            e = C.render(t["question"], t["answer"], ctx, "explicit_v1")
            assert e["prompt"].startswith(o["prompt"][:e["rubric_span"][0]])
            assert e["prompt"].endswith(o["prompt"][e["rubric_span"][0]:])
            assert C.messages("llama", e["prompt"])[0]["role"] == "user"
            assert len(C.messages("qwen", e["prompt"])) == 1


def test_invariance_check_detects_tampering(monkeypatch):
    real = C.render

    def bad(q, a, ctx, rub):
        r = real(q, a, ctx, rub)
        if rub == "explicit_v1":
            r = dict(r, prompt=r["prompt"].replace("QUESTION:", "QUESTION :"))
        return r
    monkeypatch.setattr(C, "render", bad)
    with pytest.raises(AssertionError):
        C.assert_invariance("q?", "a.")


def test_rubric_defines_standards_without_hypothesis_or_ignore_instructions():
    text = C.EXPLICIT_RUBRIC.lower()
    for w in ("prior", "previous", "earlier", "history", "feedback", "ignore", "disregard",
              "bias", "anchor", "other model", "your answer", "regardless", "only on",
              "based only", "solely", "exclusively"):
        assert w not in text, w
    for anchor in ("10:", "8-9:", "6-7:", "4-5:", "2-3:", "0-1:"):
        assert anchor in C.EXPLICIT_RUBRIC
    assert "accuracy" in text and "completeness" in text


def test_matched_units_share_everything_but_the_varied_factor(calib_units):
    by = {(u["model_key"], u["base_task_id"], u["rubric_id"], u["context"]): u for u in calib_units}
    fixed = ("model_revision", "decoding_sha256", "parser_sha256", "validity_policy_sha256",
             "generation_code_sha256", "attn_implementation", "precision", "readout")
    for (m, t, r, c), u in by.items():
        for r2, c2 in itertools.product(C.RUBRICS, C.CONTEXTS):
            v = by[(m, t, r2, c2)]
            assert all(u[k] == v[k] for k in fixed)
    assert all(u["decoding"]["max_new_tokens"] == 512 and u["decoding"]["seed"] == 42
               and u["decoding"]["batch_size"] == 1 for u in calib_units)
    assert {u["decoding"]["enable_thinking"] for u in calib_units if u["model_key"] == "qwen"} == {False}


def test_legacy_files_vendored_byte_identically():
    pk = I.root() / I.PKG / "code/src/silent_influence"
    for n in ("scaled_conditions.py", "scaled_parsing.py", "output_validity.py",
              "exact_generation.py", "final_study_messages.py"):
        assert I.sha256_file(EXT / "src/rba/legacy" / n) == I.sha256_file(pk / n)


def test_inputs_fail_closed_on_tampering(tmp_path, monkeypatch):
    rel = I.INPUTS["a9_tasks"]
    dst = tmp_path / rel
    dst.parent.mkdir(parents=True)
    dst.write_text((I.root() / rel).read_text() + " ")
    monkeypatch.setenv("RBA_INPUT_ROOT", str(tmp_path))
    with pytest.raises(I.InputIntegrityError):
        I.load_json("a9_tasks")
