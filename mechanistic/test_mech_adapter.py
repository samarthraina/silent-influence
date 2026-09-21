"""Targeted tests for the two compatibility fixes only.

Behavioural, against real frozen records -- not mocks. Each test would fail if the fix were
wrong, rather than restating the implementation.
"""
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent / "code"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import mech_adapter as MA
from silent_influence import scaled_parsing as parsing

RECORDS = HERE.parent / "results/behavioral/per_scorer_llama.jsonl.gz"


@pytest.fixture(scope="module")
def recs():
    import gzip
    op = gzip.open if RECORDS.suffix == ".gz" else open
    with op(RECORDS, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ---- fix 1: the record adapter --------------------------------------------------------

def test_adapter_supplies_every_field_the_trace_code_reads(recs):
    """The exact field list run_trace.py / run_jlens.py index into."""
    needed = {"judge_model", "parse_status", "prompt_id", "prior_context_condition",
              "system_prompt", "user_prompt", "prior_score_value"}
    out = MA.to_trace_record(recs[0])
    assert needed <= set(out), needed - set(out)


def test_raw_records_lack_those_fields(recs):
    """Guards the premise: without the adapter the trace code cannot run at all."""
    raw = set(recs[0])
    assert "judge_model" not in raw and "prompt_id" not in raw
    assert "prior_context_condition" not in raw and "prior_score_value" not in raw


def test_prompt_id_is_unique_across_datasets(recs):
    """MT-Bench ids are bare integers and collide with nothing else only once the dataset
    qualifies them. A collision here would silently merge two different tasks."""
    nh = [r for r in recs if r["condition"] == "no_history"]
    ids = [MA.to_trace_record(r)["prompt_id"] for r in nh]
    assert len(ids) == len(set(ids)) == len(nh)


def test_prior_score_value_matches_the_injected_numeral(recs):
    """The value must be the numeral actually present in the rendered context, because
    locate_positions searches for f'{value}/10'. Checked against the record's own text."""
    seen = set()
    for r in recs:
        out = MA.to_trace_record(r)
        v, ctx = out["prior_score_value"], (r.get("added_context") or "")
        seen.add(r["condition"])
        if v is None:
            assert f"/10" not in ctx or not ctx, (r["condition"], ctx)
        else:
            assert f"{v}/10" in ctx, (r["condition"], v, ctx)
    assert {"no_history", "self_low_2"} <= seen


def test_user_prompt_is_the_frozen_prompt_verbatim(recs):
    """The adapter must not re-render: the user turn has to come back byte-identical."""
    for r in recs[:50]:
        out = MA.to_trace_record(r)
        joined = "".join(m["content"] for m in r["messages"] if m["role"] == "user")
        assert out["user_prompt"] == joined
        assert out["system_prompt"] == ""      # Llama frozen wrapping: no system turn


def test_adapter_does_not_mutate_the_input(recs):
    before = json.dumps(recs[0], sort_keys=True)
    MA.to_trace_record(recs[0])
    assert json.dumps(recs[0], sort_keys=True) == before


def test_unknown_condition_raises(recs):
    bad = dict(recs[0]); bad["condition"] = "not_a_condition"
    with pytest.raises(KeyError):
        MA.to_trace_record(bad)


def test_missing_user_turn_raises(recs):
    bad = dict(recs[0]); bad["messages"] = [{"role": "system", "content": "x"}]
    with pytest.raises(ValueError):
        MA.to_trace_record(bad)


# ---- fix 2: the parser call -----------------------------------------------------------

def test_obsolete_parser_api_is_genuinely_absent():
    """Justifies the fix: .parse() is what the old scripts call and it does not exist."""
    assert not hasattr(parsing, "parse")
    assert hasattr(parsing, "parse_final_score")


def test_parse_result_has_score_not_total(recs):
    pr = parsing.parse_final_score(recs[0]["response"])
    assert hasattr(pr, "score") and not hasattr(pr, "total")


def test_score_of_reproduces_the_frozen_parsed_score(recs):
    """The strong check: re-parsing the stored response must return the score the frozen
    behavioural run recorded, for every parse_ok record."""
    n = 0
    for r in recs:
        if r["parse_status"] != "ok":
            continue
        s, st = MA.score_of(r["response"])
        assert st == "ok" and s == r["parsed_score"], r["unit_id"]
        n += 1
    assert n > 1000, n


def test_score_of_reports_failure_rather_than_raising(recs):
    for bad in (None, "", "no score at all here"):
        s, st = MA.score_of(bad)
        assert s is None and st != "ok"
