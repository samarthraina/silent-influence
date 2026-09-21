"""Behavioural tests for Amendment A5: cap-aware output validity.

The property under test is that a capped-incomplete response cannot become an analysis
observation by any route -- not through the parser, not through human recovery, not through
adjudication, and not through resume. Its raw text and numeric matches are still retained.
"""
from __future__ import annotations

import json

import pytest

import analyze_final_study as afs
import run_final_scoring as rfs
from silent_influence import output_validity as ov
from silent_influence import scaled_conditions as sc


def rec(**kw):
    """A scoring record with the fields A5 reads. Defaults describe a clean, complete,
    parsed response."""
    base = {
        "unit_id": "llama__arena_hard__t1__no_history",
        "scorer_key": "llama", "dataset": "arena_hard", "source_task_id": "t1",
        "condition": "no_history",
        "response": "Evaluation: solid answer. Final score: 7/10",
        "parse_ok": True, "parsed_score": 7.0, "parse_status": "ok",
        "parse_matched_text": "Final score: 7/10",
        "output_tokens": 120, "max_new_tokens": 512,
        "hit_token_cap": False, "emitted_terminator": True,
        "generation_error": None,
    }
    base.update(kw)
    return base


# ------------------------------------------------- 1. capped + numeric marker => INVALID

def test_capped_response_with_a_numeric_marker_is_still_invalid():
    """The finding that motivated A5: at the 512 ceiling four responses parsed and gave
    scores that moved by up to 8.5 points once the same generation was completed."""
    r = rec(hit_token_cap=True, emitted_terminator=False, output_tokens=512,
            parse_ok=True, parsed_score=1.0,
            response="... interim: the content scores 1 on clarity so far, and")
    v = ov.classify(r)
    assert v["capped_incomplete"] is True
    assert v["analysis_validity"] == ov.CAPPED_INCOMPLETE
    assert v["analysis_valid"] is False
    assert v["analysis_score"] is None, "a mid-evaluation number must not become a score"
    assert ov.is_valid(r) is False
    assert ov.analysis_score(r) is None


def test_capped_invalidity_does_not_depend_on_the_parser_verdict():
    for parse_ok, parsed in ((True, 9.5), (True, 0.0), (False, None)):
        r = rec(hit_token_cap=True, emitted_terminator=False,
                parse_ok=parse_ok, parsed_score=parsed)
        assert ov.is_valid(r) is False
        assert ov.analysis_score(r) is None


# ------------------------------------------------- 2. uncapped strict-parser pass => VALID

def test_uncapped_parsed_response_remains_valid():
    r = rec()
    v = ov.classify(r)
    assert v["analysis_validity"] == ov.VALID
    assert v["analysis_valid"] is True
    assert v["analysis_score"] == 7.0
    assert v["capped_incomplete"] is False


def test_uncapped_parser_failure_is_invalid_but_recoverable():
    """A5 point 5: recovery is unchanged for uncapped parser failures."""
    r = rec(parse_ok=False, parsed_score=None, parse_status="no_marker")
    v = ov.classify(r)
    assert v["analysis_valid"] is False
    assert v["analysis_validity"] == ov.PARSE_FAILED
    assert v["eligible_for_human_recovery"] is True
    assert ov.eligible_for_human_recovery(r) is True


def test_capped_incomplete_is_never_sent_to_human_recovery():
    """A5 point 4: an explicitly final score cannot be inferred from an unfinished
    generation, so there is nothing for a human reader to recover."""
    r = rec(hit_token_cap=True, emitted_terminator=False, parse_ok=False, parsed_score=None)
    assert ov.eligible_for_human_recovery(r) is False
    r2 = rec(hit_token_cap=True, emitted_terminator=False, parse_ok=True, parsed_score=3.0)
    assert ov.eligible_for_human_recovery(r2) is False


# ------------------------------------------------- 3. terminated ON the boundary => VALID

def test_response_terminating_exactly_at_the_ceiling_is_not_falsely_invalidated():
    """output_tokens == max_new_tokens AND a terminator was emitted: the model finished on
    the boundary. trim_to_first_eos is inclusive, so length comparison cannot tell this from
    a truncation -- terminator presence is what decides."""
    r = rec(output_tokens=512, max_new_tokens=512, hit_token_cap=True,
            emitted_terminator=True)
    v = ov.classify(r)
    assert v["capped_incomplete"] is False
    assert v["analysis_valid"] is True
    assert v["analysis_score"] == 7.0


def test_unknown_terminator_evidence_on_a_capped_record_fails_closed():
    """A record that hit the ceiling but carries no terminator field must be treated as
    unfinished, not admitted on the benefit of the doubt."""
    r = rec(hit_token_cap=True, parsed_score=5.0)
    r.pop("emitted_terminator")
    assert ov.is_capped_incomplete(r) is True
    assert ov.is_valid(r) is False


def test_uncapped_record_with_no_terminator_field_is_still_valid():
    r = rec()
    r.pop("emitted_terminator")
    assert ov.is_capped_incomplete(r) is False
    assert ov.is_valid(r) is True


# ------------------------------------------------- 4. raw capped output is RETAINED

def test_raw_capped_output_and_numeric_matches_are_retained():
    """A5 point 3: invalid for analysis, but fully preserved for auditing."""
    raw = "long unfinished evaluation ... the content scores 1 on clarity so far, and"
    r = rec(hit_token_cap=True, emitted_terminator=False, output_tokens=512,
            parse_ok=True, parsed_score=1.0, parse_matched_text="scores 1",
            response=raw)
    a = ov.annotate(r)
    assert a["response"] == raw, "raw response must survive"
    assert a["retained_parsed_score"] == 1.0
    assert a["retained_matched_text"] == "scores 1"
    assert a["retained_parse_status"] == "ok"
    assert a["output_tokens"] == 512
    assert a["hit_token_cap"] is True
    assert a["emitted_terminator"] is False
    assert a["max_new_tokens"] == 512
    # and the original fields are not rewritten
    assert a["parse_ok"] is True and a["parsed_score"] == 1.0
    # but the analysis value is missing
    assert a["analysis_score"] is None and a["analysis_valid"] is False


def test_annotate_does_not_mutate_the_input():
    r = rec(hit_token_cap=True, emitted_terminator=False)
    before = json.dumps(r, sort_keys=True)
    ov.annotate(r)
    assert json.dumps(r, sort_keys=True) == before


# ------------------------------------- 5. capped cannot enter means or paired contrasts

def _pair(scorer, dataset, task, a_valid, b_valid):
    def one(cond, valid):
        if valid:
            return rec(scorer_key=scorer, dataset=dataset, source_task_id=task,
                       condition=cond, parsed_score=8.0)
        return rec(scorer_key=scorer, dataset=dataset, source_task_id=task, condition=cond,
                   hit_token_cap=True, emitted_terminator=False,
                   parse_ok=True, parsed_score=2.0)     # score-shaped but capped
    return [one("no_history", a_valid), one("self_low_2", b_valid)]


def test_capped_observations_cannot_enter_condition_means():
    records = _pair("llama", "arena_hard", "t1", True, False)
    buckets = {}
    for r in records:
        if ov.is_valid(r):
            buckets.setdefault(r["condition"], []).append(ov.analysis_score(r))
    assert buckets == {"no_history": [8.0]}, buckets
    assert 2.0 not in [v for vs in buckets.values() for v in vs]


def test_capped_observation_breaks_the_paired_contrast_for_that_task():
    """The frozen paired complete-case rule: a task contributes only when BOTH condition
    scores are valid."""
    records = (_pair("llama", "arena_hard", "t1", True, True)
               + _pair("llama", "arena_hard", "t2", True, False)
               + _pair("llama", "wildbench", "t3", False, False))
    rp = ov.retained_pairs(records, "no_history", "self_low_2")
    cells = {(c["scorer_key"], c["dataset"]): c for c in rp["cells"]}
    assert cells[("llama", "arena_hard")]["n_tasks"] == 2
    assert cells[("llama", "arena_hard")]["n_retained"] == 1
    assert cells[("llama", "wildbench")]["n_retained"] == 0
    assert rp["n_tasks"] == 3 and rp["n_retained"] == 1


def test_missingness_is_reported_by_scorer_dataset_condition_with_reasons():
    records = (_pair("llama", "arena_hard", "t1", True, False)
               + [rec(scorer_key="qwen", dataset="wildbench", source_task_id="t9",
                      condition="no_history", parse_ok=False, parsed_score=None,
                      parse_status="no_marker")])
    m = ov.missingness_report(records)
    by = {(c["scorer_key"], c["dataset"], c["condition"]): c for c in m["cells"]}
    assert by[("llama", "arena_hard", "self_low_2")]["n_capped_incomplete"] == 1
    assert by[("llama", "arena_hard", "self_low_2")]["n_valid"] == 0
    assert by[("qwen", "wildbench", "no_history")]["n_parse_failed"] == 1
    assert m["n_total"] == 3 and m["n_valid"] == 1
    assert m["n_capped_incomplete"] == 1 and m["n_parse_failed"] == 1


def test_the_analysis_admits_observations_only_through_a5():
    """Guards against a regression to raw parse_ok/parsed_score admission."""
    src = (afs.__file__).replace(".pyc", ".py")
    text = open(src, encoding="utf-8").read()
    assert 'not r["parse_ok"]' not in text
    assert 'append(r["parsed_score"])' not in text
    assert "ov.is_valid(r)" in text and "ov.analysis_score(r)" in text


# ------------------------------------- 6. resume / recovery preserve the same rule

def test_a_stored_verdict_is_honoured_rather_than_re_derived():
    """Resume reads records back from disk. A stored invalid verdict must stay invalid even
    if the fields it was derived from were later re-interpreted."""
    a = ov.annotate(rec(hit_token_cap=True, emitted_terminator=False, parsed_score=4.0))
    round_tripped = json.loads(json.dumps(a))
    assert ov.is_valid(round_tripped) is False
    assert ov.analysis_score(round_tripped) is None
    assert ov.eligible_for_human_recovery(round_tripped) is False


def test_annotating_twice_cannot_upgrade_an_invalid_observation():
    once = ov.annotate(rec(hit_token_cap=True, emitted_terminator=False, parsed_score=4.0))
    twice = ov.annotate(once)
    assert twice["analysis_valid"] is False
    assert twice["analysis_score"] is None
    assert twice["analysis_validity"] == ov.CAPPED_INCOMPLETE


def test_the_production_scoring_path_stamps_the_verdict_onto_every_record():
    """score_one must emit an A5-annotated record, so resume and analysis read a stored
    verdict rather than each deriving their own."""
    from silent_influence import exact_generation as eg
    cand = {"dataset": "arena_hard", "source_task_id": "t1", "category": "math",
            "question": "Q?", "question_sha256": "x", "answer": "A.", "answer_sha256": "y",
            "output_tokens": 10, "hit_token_cap": False, "generation_seconds": 0.1,
            "generator_model": "olmo", "generator_revision": "r"}
    unit = {"candidate": cand, "condition": sc.resolve("no_history")}
    spec = next(s for s in rfs.SCORERS if s.key == "olmo32b")
    loaded = eg.load_stub_model(spec)
    out = rfs.score_one(loaded, spec, unit, stub=True, log=lambda *_: None)
    for field in ("analysis_validity", "analysis_valid", "analysis_score",
                  "capped_incomplete", "hit_token_cap", "emitted_terminator",
                  "max_new_tokens", "output_tokens", "eligible_for_human_recovery"):
        assert field in out, f"{field} missing from the production record"
    assert out["max_new_tokens"] == 2048, "A4 ceiling must be recorded per scorer"
    assert out["capped_incomplete"] is False


def test_recovery_routing_excludes_capped_and_keeps_uncapped():
    import audit_final_score_recovery as afr
    src = open(afr.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert "ov.eligible_for_human_recovery(r)" in src
    assert "n_capped_incomplete_excluded_from_recovery" in src


def test_adjudication_cannot_promote_a_capped_record():
    import build_final_adjudicated_records as bfa
    src = open(bfa.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert "ov.is_capped_incomplete(r)" in src


# ------------------------------------- A5 leaves the frozen design alone

def test_a5_changes_no_ceiling_and_no_study_shape():
    assert {s.key: s.max_new_tokens for s in rfs.SCORERS} == {
        "llama": 512, "qwen": 512, "gemma": 512, "olmo32b": 2048}
    assert afs.SCORERS == ["llama", "qwen", "gemma", "olmo32b"]
    assert afs.S1_SCORERS == ["llama", "qwen", "gemma"]
    assert (afs.S1_N_CELLS_PRIMARY, afs.S1_N_CELLS_SECONDARY) == (6, 9)
    assert len(sc.CONDITIONS) == 6


def test_a5_does_not_touch_the_frozen_parser_or_recovery_modules():
    from silent_influence import scaled_parsing, score_recovery
    for mod in (scaled_parsing, score_recovery):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "output_validity" not in src
        assert "capped_incomplete" not in src


def test_stub_generator_cannot_write_the_protected_candidates_file():
    """A stub run of generate_final_candidates once filled the frozen candidates file with 578
    'stub response <hash>' answers. The guard must fail closed before any model is loaded."""
    from silent_influence import final_preflight_checks as fpc
    with pytest.raises(SystemExit):
        fpc.assert_stub_output_is_not_a_protected_dir(
            "data/candidates/final_olmo_answers.json", stub=True, repo_root=".")
    # a real run is never restricted
    fpc.assert_stub_output_is_not_a_protected_dir(
        "data/candidates/final_olmo_answers.json", stub=False, repo_root=".")


def test_generator_calls_the_stub_guard_before_loading_a_model():
    import generate_final_candidates as gfc
    src = open(gfc.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    guard = src.find("assert_stub_output_is_not_a_protected_dir")
    load = src.find("load_exact_model")
    assert guard > 0, "generator must call the stub guard"
    assert guard < load, "the guard must run before any model is loaded"
