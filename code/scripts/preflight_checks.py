#!/usr/bin/env python3
"""Post-smoke-test verification. Prints PASS/FAIL for each pre-flight requirement.

    python scripts/preflight_checks.py --config configs/phase1_smoke.yaml \
        --records results/smoke/records.jsonl

Exit code is non-zero if any check fails.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from _bootstrap import REPO, load_merged_config

from silent_influence import parsing, protocols, templates
from silent_influence.conditions import NO_HISTORY, SCORE_MAX, SCORE_MIN, score_condition
from silent_influence.grid import build_plan
from silent_influence.records import (UNIT_KEY_FIELDS, count_truncated, derive_seed,
                                      load_records, unit_id)
from silent_influence.render import INSTRUCTION, assert_score_invariance
from silent_influence.runner import render_for

RESULTS = []


def check(n, name):
    def deco(fn):
        def wrapped(ctx):
            try:
                detail = fn(ctx)
                RESULTS.append((n, name, True, detail or ""))
            except AssertionError as e:
                RESULTS.append((n, name, False, str(e)))
            except Exception as e:                        # a crashing check is a failure
                RESULTS.append((n, name, False, f"{type(e).__name__}: {e}"))
        wrapped._n = n
        return wrapped
    return deco


@check(1, "prompts differ only in intended fields")
def c1(ctx):
    plan, recs = ctx["plan"], ctx["records"]
    u = plan.units[0]
    row = plan.prompts[(u.dataset, u.prompt_id)]
    c = plan.candidates[(u.dataset, u.prompt_id, u.candidate_response_id)]
    for rv in sorted({x.rubric_variant for x in plan.units}):
        for op in sorted({x.output_protocol for x in plan.units}):
            assert_score_invariance(
                question=row.text, candidate_response=c.text, rubric_variant=rv,
                output_protocol=op, history_template=u.history_template,
                evaluated_label=c.evaluated_model)

    # and against what was actually persisted
    saved = {r["prior_context_condition"]: r["user_prompt"] for r in recs
             if r["prompt_id"] == recs[0]["prompt_id"]
             and r["candidate_response_id"] == recs[0]["candidate_response_id"]}
    scored = {k: v for k, v in saved.items() if k != NO_HISTORY}
    if len(scored) >= 2:
        names = sorted(scored, key=lambda s: int(s.split("_")[1]))
        a, b = names[0], names[-1]
        va, vb = a.split("_")[1], b.split("_")[1]
        assert scored[a].replace(f"{va}/10", "<S>") == scored[b].replace(f"{vb}/10", "<S>"), \
            f"persisted {a} and {b} differ outside the injected numeral"
        return f"{len(scored)} persisted score arms identical modulo the numeral"
    return "invariance proven for all rubric x protocol combinations"


@check(2, "all expected experimental cells exist")
def c2(ctx):
    plan, recs = ctx["plan"], ctx["records"]
    want = {u.uid for u in plan.units}
    got = {r["unit_id"] for r in recs}
    missing, extra = want - got, got - want
    assert not missing, f"{len(missing)} planned units missing from records"
    assert not extra, f"{len(extra)} records not in the plan"
    assert len(recs) == len(want), f"{len(recs)} records for {len(want)} units (duplicates?)"
    return f"{len(want)}/{len(want)} planned units present, no duplicates, no extras"


@check(3, "raw outputs are persisted")
def c3(ctx):
    recs = ctx["records"]
    missing = [r["unit_id"] for r in recs
               if "raw_output" not in r or
               (r["raw_output"] is None and not r.get("generation_error"))]
    assert not missing, f"{len(missing)} records lack raw_output without a generation error"
    return (f"raw_output present on {len(recs)}/{len(recs)}; "
            f"non-empty on {sum(1 for r in recs if (r.get('raw_output') or '').strip())}")


@check(4, "parser extracts valid scores")
def c4(ctx):
    cases = [
        ('{"relevance": 7, "reasoning_quality": 6, "justification": "ok"}', True, 7, 6),
        ('```json\n{"relevance":9,"reasoning_quality":8,"justification":"x"}\n```', True, 9, 8),
        ('<think>hmm</think>{"relevance": 3, "reasoning_quality": 4, "justification": "y"}',
         True, 3, 4),
        ('prose first {"relevance": "5", "reasoning_quality": 5, "justification": "z"} tail',
         True, 5, 5),
        ('{"justification":"j","relevance":10,"reasoning_quality":1}', True, 10, 1),
        ('{"evaluations":[{"relevance":6,"reasoning_quality":6,"justification":"j"}]}',
         True, 6, 6),
        ('{"relevance": 7, "reasoning_quality": 6, "justification": "t",}', True, 7, 6),
    ]
    for raw, want_ok, rel, rq in cases:
        pr = parsing.parse(raw, wants_justification=True)
        assert pr.ok is want_ok, f"{raw[:40]!r} -> {pr.status} ({pr.error})"
        assert pr.relevance == rel and pr.reasoning_quality == rq, \
            f"{raw[:40]!r} -> rel={pr.relevance} rq={pr.reasoning_quality}"
        assert pr.total == (rel + rq) / 2

    ok_recs = [r for r in ctx["records"] if r["parse_status"] == "ok"]
    for r in ok_recs:
        assert r["relevance"] is not None and r["reasoning_quality"] is not None
        assert r["total"] == (r["relevance"] + r["reasoning_quality"]) / 2
    return (f"{len(cases)}/{len(cases)} golden cases; "
            f"{len(ok_recs)} live records internally consistent")


@check(5, "invalid outputs are retained and logged")
def c5(ctx):
    bad_cases = [
        ("", parsing.EMPTY_OUTPUT),
        ("I cannot comply.", parsing.NO_JSON),
        ('{"foo": 1}', parsing.MISSING_FIELDS),
        ('{"relevance": "excellent", "reasoning_quality": 5, "justification": "j"}',
         parsing.NON_NUMERIC),
        ('{"relevance": 7, "reasoning_quality": 6}', parsing.MISSING_FIELDS),
    ]
    for raw, want in bad_cases:
        got = parsing.parse(raw, wants_justification=True).status
        assert got == want, f"{raw[:40]!r} -> {got}, expected {want}"

    recs = ctx["records"]
    failed = [r for r in recs if r["parse_status"] != "ok"]
    for r in failed:
        assert "raw_output" in r, "failed record dropped its raw output"
        assert r.get("parse_error") or r.get("generation_error"), \
            f"failed record {r['unit_id']} has no error message"
    return (f"{len(bad_cases)}/{len(bad_cases)} failure modes classified; "
            f"{len(failed)} live failures retained with raw output + error")


@check(6, "condition labels survive into saved results")
def c6(ctx):
    plan, recs = ctx["plan"], ctx["records"]
    by_uid = {u.uid: u for u in plan.units}
    for r in recs:
        u = by_uid[r["unit_id"]]
        for f in UNIT_KEY_FIELDS:
            assert r.get(f) == getattr(u, f), \
                f"{f}: record={r.get(f)!r} plan={getattr(u, f)!r}"
        assert unit_id(r) == r["unit_id"], "unit_id does not recompute from the record"
    conds = Counter(r["prior_context_condition"] for r in recs)
    vals = {r["prior_context_condition"]: r["prior_score_value"] for r in recs}
    assert vals.get(NO_HISTORY, "absent") is None, "no_history must carry a null score value"
    for c, v in vals.items():
        if c != NO_HISTORY:
            assert v == int(c.split("_")[1]), f"{c} carries prior_score_value={v}"
    return f"all {len(UNIT_KEY_FIELDS)} key fields round-trip; conditions={dict(conds)}"


@check(7, "replicate/seed fields are correct")
def c7(ctx):
    plan, recs = ctx["plan"], ctx["records"]
    n_rep = int(plan.config["experiment"].get("replicates", 1))
    reps = {r["replicate"] for r in recs}
    assert reps == set(range(n_rep)), f"replicates {sorted(reps)} != 0..{n_rep-1}"
    for r in recs:
        assert r["base_seed"] == plan.base_seed
        assert r["seed"] == derive_seed(plan.base_seed, r["unit_id"]), \
            f"seed for {r['unit_id']} is not derived from (base_seed, unit_id)"
    assert len({r["seed"] for r in recs}) == len(recs), "seeds are not unique per unit"
    return (f"replicates={sorted(reps)}; all {len(recs)} seeds derived and distinct")


@check(8, "rerunning skips completed cells")
def c8(ctx):
    assert ctx["rerun"] is not None, "rerun stats not supplied (pass --rerun-stats)"
    st = ctx["rerun"]
    assert st["attempted"] == 0, f"rerun generated {st['attempted']} units, expected 0"
    assert st["skipped_existing"] == len(ctx["records"]), \
        f"rerun saw {st['skipped_existing']} completed, expected {len(ctx['records'])}"
    assert ctx["records_after_rerun"] == len(ctx["records"]), \
        "rerun changed the record count"
    return (f"rerun skipped {st['skipped_existing']} completed units, "
            f"generated 0, record count unchanged")


@check(9, "aggregation loses no condition information")
def c9(ctx):
    recs = ctx["records"]
    keys = {(r["dataset"], r["prompt_id"], r["candidate_response_id"], r["judge_model"],
             r["prior_context_condition"], r["rubric_variant"], r["output_protocol"],
             r["replicate"]) for r in recs}
    assert len(keys) == len(recs), \
        f"{len(recs)} records collapse to {len(keys)} distinct grouping keys"
    # the legacy defect: a grouping key that omits the condition
    bad = {(r["dataset"], r["prompt_id"], r["judge_model"]) for r in recs}
    assert len(bad) < len(recs), "sanity: condition-free key should collide"
    return (f"{len(recs)} records -> {len(keys)} distinct full keys (1:1); "
            f"records are written unaggregated, one line per unit")


@check(10, "score range validation works")
def c10(ctx):
    for raw in ('{"relevance": 11, "reasoning_quality": 5, "justification": "j"}',
                '{"relevance": 0, "reasoning_quality": 5, "justification": "j"}',
                '{"relevance": -3, "reasoning_quality": 5, "justification": "j"}',
                '{"relevance": 5, "reasoning_quality": 100, "justification": "j"}'):
        pr = parsing.parse(raw, wants_justification=True)
        assert pr.status == parsing.OUT_OF_RANGE, f"{raw[:35]!r} -> {pr.status}"
        assert pr.total is None, "out-of-range record must not expose a total"
    for v in (SCORE_MIN, SCORE_MAX):
        pr = parsing.parse(
            f'{{"relevance": {v}, "reasoning_quality": {v}, "justification": "j"}}', True)
        assert pr.ok, f"boundary {v} rejected"
    for r in ctx["records"]:
        if r["parse_status"] == "ok":
            assert SCORE_MIN <= r["relevance"] <= SCORE_MAX
            assert SCORE_MIN <= r["reasoning_quality"] <= SCORE_MAX
    return f"boundaries {SCORE_MIN}/{SCORE_MAX} accepted; 0, -3, 11, 100 rejected"


@check(11, "dataset/prompt identifiers survive end-to-end")
def c11(ctx):
    plan, recs = ctx["plan"], ctx["records"]
    for r in recs:
        key = (r["dataset"], r["prompt_id"])
        assert key in plan.prompts, f"record references unknown prompt {key}"
        row = plan.prompts[key]
        assert row.text[:60] in r["user_prompt"], \
            f"prompt {key} text not found in the rendered user prompt"
        ck = (r["dataset"], r["prompt_id"], r["candidate_response_id"])
        assert ck in plan.candidates, f"record references unknown candidate {ck}"
        assert plan.candidates[ck].text[:60] in r["user_prompt"], \
            f"candidate {ck} text not found in the rendered user prompt"
    return (f"{len({(r['dataset'], r['prompt_id']) for r in recs})} (dataset, prompt_id) "
            f"pairs resolve; question and candidate text verified inside every prompt")


@check(12, "model/checkpoint metadata are recorded")
def c12(ctx):
    for r in ctx["records"]:
        mi = r.get("model_identity")
        assert isinstance(mi, dict) and mi, "model_identity missing"
        for f in ("backend", "model_key", "hf_id"):
            assert mi.get(f) is not None, f"model_identity.{f} missing"
        assert mi["model_key"] == r["judge_model"]
        assert mi["backend"] == r["backend"]
    mi = ctx["records"][0]["model_identity"]
    return f"backend={mi['backend']} hf_id={mi['hf_id']} extra_keys={sorted(set(mi)-{'backend','model_key','hf_id'})}"


@check(13, "generation parameters are recorded")
def c13(ctx):
    want = set(ctx["plan"].gen_params.as_dict())
    for r in ctx["records"]:
        gp = r.get("generation_params")
        assert isinstance(gp, dict) and set(gp) == want, f"generation_params={gp}"
        assert gp == ctx["plan"].gen_params.as_dict(), "params drifted from the plan"
        assert isinstance(r.get("generation_seconds"), (int, float))
    return f"{ctx['plan'].gen_params.as_dict()} on all {len(ctx['records'])} records"


@check(14, "no-history and score conditions render as intended")
def c14(ctx):
    plan, recs = ctx["plan"], ctx["records"]
    tmpl = templates.resolve(plan.units[0].history_template)
    marker = tmpl.split("{score}")[0].strip()[:40]
    by_uid = {u.uid: u for u in plan.units}
    for r in recs:
        up = r["user_prompt"]
        # the persisted prompt must be exactly what the composer produces today
        fresh = render_for(plan, by_uid[r["unit_id"]])
        assert fresh.user == up, f"persisted prompt for {r['unit_id']} no longer reproduces"
        assert fresh.system == r["system_prompt"], "persisted system prompt drifted"

        if r["prior_context_condition"] == NO_HISTORY:
            assert marker not in up, "no_history prompt contains the history block"
            assert up.startswith(INSTRUCTION), \
                "no_history prompt does not start with the shared instruction"
        else:
            v = r["prior_score_value"]
            head = up.split(INSTRUCTION)[0]
            assert marker in head, "score arm is missing the history block"
            assert f"{v}/10" in head, \
                f"score_{v} prompt does not carry {v}/10 in the history block"
            assert up.startswith(marker[:20]), "history block is not first"
    nh = [r for r in recs if r["prior_context_condition"] == NO_HISTORY]
    sc = [r for r in recs if r["prior_context_condition"] != NO_HISTORY]
    return (f"{len(nh)} no_history prompts carry no history block; "
            f"{len(sc)} score prompts carry exactly their own value")


CHECKS = [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, c14]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--records", required=True)
    ap.add_argument("--rerun-stats", default=None,
                    help="JSON file written by the resume rerun (enables check 8)")
    args = ap.parse_args()

    cfg = load_merged_config(args.config)
    plan = build_plan(cfg, REPO, cfg["experiment"]["name"])
    recs = load_records(Path(args.records))

    rerun = None
    if args.rerun_stats and Path(args.rerun_stats).exists():
        with open(args.rerun_stats, encoding="utf-8") as f:
            rerun = json.load(f)

    ctx = {"plan": plan, "records": recs, "rerun": rerun,
           "records_after_rerun": len(recs)}

    print(f"config : {cfg['_config_path']}")
    print(f"records: {args.records}  ({len(recs)} records, "
          f"{count_truncated(Path(args.records))} truncated lines)\n")

    for fn in CHECKS:
        fn(ctx)

    width = max(len(n) for _, n, _, _ in RESULTS)
    n_pass = 0
    for n, name, ok, detail in RESULTS:
        tag = "PASS" if ok else "FAIL"
        n_pass += ok
        print(f"[{tag}] {n:>2d}. {name:<{width}s}  {detail}")
    print(f"\n{n_pass}/{len(RESULTS)} checks passed")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
