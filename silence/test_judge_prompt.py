"""Targeted tests for the silence-run prompt and parser only. New code, so tested; nothing
else is re-run."""
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from judge_prompt import (CONTEXT, GUIDE, LABELS, build_messages, consistency_flag,
                          parse_judge_output)


# ---- blinding: the prompt must leak nothing about the design -------------------------
@pytest.mark.parametrize("forbidden", [
    "no_history", "self_low_2", "self_high_10", "unrelated_low_2", "verbal_negative",
    "llama", "qwen", "gemma", "olmo", "silent influence", "condition", "contrast",
    "hypothesis", "bias", "lower", "higher", "2/10", "10/10",
])
def test_prompt_does_not_leak_design(forbidden):
    assert forbidden.lower() not in GUIDE.lower()


def test_prompt_contains_only_the_rationale_and_the_guide():
    msgs = build_messages("SOME RATIONALE")
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    body = msgs[0]["content"]
    assert "SOME RATIONALE" in body
    assert body.count("BEGIN EVALUATION TEXT") == 1


def test_prompt_demands_explicit_only_judgement():
    g = GUIDE.lower()
    assert "only what is written" in g
    assert "hidden motives" in g
    assert "tone is not evidence" in g


# ---- parser: strict, and fails loudly ------------------------------------------------
def test_parses_a_clean_object():
    r, s = parse_judge_output('{"acknowledgment_label":"A","context_mentioned":"yes",'
                              '"evidence":"the earlier rating"}')
    assert s == "ok" and r["acknowledgment_label"] == "A"
    assert r["context_mentioned"] == "yes" and r["evidence"] == "the earlier rating"


def test_parses_object_embedded_in_prose():
    r, s = parse_judge_output('Sure!\n{"acknowledgment_label":"N",'
                              '"context_mentioned":"no","evidence":""}\nDone.')
    assert s == "ok" and r["acknowledgment_label"] == "N"


def test_normalises_case_but_not_meaning():
    r, s = parse_judge_output('{"acknowledgment_label":"d","context_mentioned":"YES",'
                              '"evidence":"x"}')
    assert s == "ok" and r["acknowledgment_label"] == "D" and r["context_mentioned"] == "yes"


@pytest.mark.parametrize("bad,status", [
    (None, "empty"),
    ("", "empty"),
    ("no json here", "no_json_object"),
    ('{"acknowledgment_label": }', "bad_json"),
    ('{"acknowledgment_label":"MAYBE","context_mentioned":"yes","evidence":""}', "bad_label"),
    ('{"acknowledgment_label":"A","context_mentioned":"probably","evidence":""}',
     "bad_context_flag"),
    ('{"acknowledgment_label":"A","context_mentioned":"yes","evidence":123}', "bad_evidence"),
    ('{"context_mentioned":"yes","evidence":""}', "bad_label"),
])
def test_malformed_output_is_reported_not_coerced(bad, status):
    r, s = parse_judge_output(bad)
    assert r is None and s == status


def test_missing_evidence_key_defaults_to_empty():
    r, s = parse_judge_output('{"acknowledgment_label":"N","context_mentioned":"no"}')
    assert s == "ok" and r["evidence"] == ""


def test_every_declared_label_round_trips():
    for lab in LABELS:
        ctx = "yes" if lab in ("A", "D") else "no"
        r, s = parse_judge_output(json.dumps({"acknowledgment_label": lab,
                                              "context_mentioned": ctx, "evidence": ""}))
        assert s == "ok" and r["acknowledgment_label"] == lab


def test_evidence_is_truncated_not_dropped():
    r, s = parse_judge_output(json.dumps({"acknowledgment_label": "A",
                                          "context_mentioned": "yes",
                                          "evidence": "w " * 500}))
    assert s == "ok" and 0 < len(r["evidence"]) <= 400


# ---- internal consistency ------------------------------------------------------------
def test_flags_label_context_contradiction():
    assert consistency_flag({"acknowledgment_label": "A", "context_mentioned": "no"})
    assert consistency_flag({"acknowledgment_label": "D", "context_mentioned": "no"})


def test_allows_consistent_combinations():
    for lab, ctx in (("A", "yes"), ("D", "yes"), ("N", "no"), ("U", "yes"), ("U", "no")):
        assert consistency_flag({"acknowledgment_label": lab,
                                 "context_mentioned": ctx}) is None


# ---- the blinded item files really are blind -----------------------------------------
def test_blinded_item_files_carry_only_id_and_text():
    for j in ("J1", "J2"):
        p = HERE / f"blinded_items_{j}.jsonl"
        rows = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
        assert len(rows) == 1872
        for r in rows[:200]:
            assert set(r) == {"item_id", "rationale_text"}


def test_both_judges_share_the_id_space_in_different_order():
    a = [json.loads(l)["item_id"] for l in
         (HERE / "blinded_items_J1.jsonl").open(encoding="utf-8") if l.strip()]
    b = [json.loads(l)["item_id"] for l in
         (HERE / "blinded_items_J2.jsonl").open(encoding="utf-8") if l.strip()]
    assert sorted(a) == sorted(b)
    assert a != b
