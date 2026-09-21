"""Tests for scripts/analyze_final_study.py against synthetic records (no GPU, no real
study data -- none exists yet). Checks the frozen design constants and that every
required estimand/report structure is actually produced and internally consistent."""
from __future__ import annotations

import json
import random
import sys

import pytest

import analyze_final_study as afs

SCORERS = afs.SCORERS
CONDITIONS = ["no_history", "self_low_2", "other_low_2", "unrelated_low_2",
             "verbal_negative", "self_high_10"]
COND_BUMP = {"no_history": 0, "self_low_2": -1.0, "other_low_2": -0.3,
            "unrelated_low_2": -0.1, "verbal_negative": -0.7, "self_high_10": 0.2}


def _synthetic_records(seed=0, per_dataset=(6, 8, 8), parse_fail_rate=0.03):
    rng = random.Random(seed)
    datasets = dict(zip(["mtbench", "arena_hard", "wildbench"], per_dataset))
    records = []
    for ds, n in datasets.items():
        for i in range(n):
            tid = f"{ds}_t{i}"
            prev_used = ds == "mtbench" and i < 4
            for scorer in SCORERS:
                base = rng.uniform(4, 8)
                for cond in CONDITIONS:
                    score = max(0, min(10, base + COND_BUMP[cond] + rng.gauss(0, 0.3)))
                    ok = rng.random() > parse_fail_rate
                    records.append({
                        "unit_id": f"{scorer}__{ds}__{tid}__{cond}", "dataset": ds,
                        "source_task_id": tid, "category": "cat", "question": "q",
                        "candidate_answer": "a", "candidate_answer_sha256": "x",
                        "generator_model": "olmo", "generator_revision": "r",
                        "scorer_key": scorer, "scorer_model_id": scorer, "scorer_revision": "r",
                        "condition": cond, "added_context": None, "prompt": "p",
                        "response": f"Final Score: {score:.1f}/10" if ok else "no score",
                        "parse_status": "ok" if ok else "no_marker", "parse_tier": 1 if ok else None,
                        "parsed_score": round(score, 2) if ok else None, "parse_ok": ok,
                        "flagged_for_review": not ok, "parse_error": None,
                        "generation_error": None, "previously_used": prev_used,
                        "prior_use_phases": ["90task"] if prev_used else [],
                        "batch_size": 1, "generation_seconds": 0.1,
                        "completed_at_utc": "2026-01-01T00:00:00Z",
                    })
    return records


def test_design_constants_are_frozen_as_specified():
    assert afs.N_CELLS_PRIMARY == 8
    assert afs.N_CELLS_SECONDARY == 12
    assert afs.HELDOUT_DATASETS == ["arena_hard", "wildbench"]
    assert afs.FULL_DATASETS == ["mtbench", "arena_hard", "wildbench"]
    assert len(afs.SCORERS) == 4
    assert afs.PRIMARY == ("no_history", "self_low_2")
    assert len(afs.DIAGNOSTIC_CONTRASTS) == 7
    assert len(afs.ALL_CONTRASTS) == 8
    assert afs.BOOTSTRAP_SEED == 20260818
    assert afs.TRIM_FRACTION == 0.10
    assert ("no_history", "other_low_2") in afs.DIAGNOSTIC_CONTRASTS  # not in the 90-task list


def test_no_history_minus_other_low_2_is_not_the_same_as_the_90task_contrast_set():
    """The final plan's 7th diagnostic differs from the 90-task run's 7th contrast
    (unrelated_low_2 vs self_low_2, which is diagnostic #2 here, not #7) -- this guards
    against silently reusing the old, slightly different contrast list."""
    names = {afs.contrast_name(a, b) for a, b in afs.ALL_CONTRASTS}
    assert "no_history_minus_other_low_2" in names


def test_trimmed_mean_matches_plain_mean_when_nothing_is_trimmed():
    vals = [5.0, 5.0, 5.0]
    assert afs.trimmed_mean(vals) == pytest.approx(5.0)


def test_trimmed_mean_drops_extremes():
    vals = [0.0] + [5.0] * 8 + [100.0]  # 10 values, 10% trim drops 1 from each end
    assert afs.trimmed_mean(vals, frac=0.10) == pytest.approx(5.0)


def test_macro_average_excludes_and_counts_empty_cells():
    cells = {("arena_hard", "llama"): [1.0, 2.0], ("arena_hard", "qwen"): []}
    required = [("arena_hard", "llama"), ("arena_hard", "qwen")]
    result = afs.macro_average(cells, required)
    assert result["n_empty_cells"] == 1
    assert result["macro_average"] == pytest.approx(1.5)


def test_analysis_end_to_end_on_synthetic_data_produces_sane_estimands():
    records = _synthetic_records()
    result = afs.analyze_one_basis(records, "complete_case", n_bootstrap=50)

    assert result["primary"]["n_cells"] == 8
    assert result["secondary"]["n_cells"] == 12
    assert result["primary"]["ci_95"]["ci_low"] <= result["primary"]["macro_average"] \
        <= result["primary"]["ci_95"]["ci_high"]
    # positive because self_low_2 is constructed to score below no_history
    assert result["primary"]["macro_average"] > 0
    assert result["primary"]["n_empty_cell_replicates"] == 0

    for scope in ("heldout_500", "full_578"):
        dist = result["task_level_distribution"][scope]["overall"]
        assert dist["min"] <= dist["p25"] <= dist["median"] <= dist["p75"] <= dist["max"]
        assert 0.0 <= dist["fraction_gt_0"] <= 1.0

    diag = result["diagnostics"]["point"]
    assert set(diag.keys()) == {afs.contrast_name(a, b) for a, b in afs.ALL_CONTRASTS}

    r1 = result["robustness"]["R1_trimmed_mean"]
    assert r1["primary_8_cell"]["macro_average"] is not None
    r2p = result["robustness"]["R2_leave_one_task_out"]["primary_500"]
    assert r2p["n_recomputations"] == 16  # 8+8 tasks in the synthetic heldout population
    assert len(r2p["ten_most_influential"]) <= 10

    r4 = result["robustness"]["R4_prior_use_descriptive"]
    assert r4["previously_used"]["n"] == 4
    assert r4["CONFOUNDED_WITH_DATASET"] is True


def test_empty_cell_is_excluded_from_macro_average_and_counted():
    records = _synthetic_records(per_dataset=(2, 2, 2))
    # remove every gemma record so the gemma cells are empty everywhere
    records = [r for r in records if r["scorer_key"] != "gemma"]
    result = afs.analyze_one_basis(records, "complete_case", n_bootstrap=20)
    assert result["primary"]["n_empty_cells"] == 2  # (arena_hard,gemma) and (wildbench,gemma)
    assert result["primary"]["macro_average"] is not None  # still computed from the other 6


def test_main_writes_both_bases_when_both_files_exist(tmp_path, monkeypatch):
    records = _synthetic_records(seed=1, per_dataset=(2, 3, 3))
    complete_case = tmp_path / "raw_results.jsonl"
    adjudicated = tmp_path / "raw_results_adjudicated.jsonl"
    with open(complete_case, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    # adjudicated: patch every failure to a fixed score, simulating full recovery
    patched = []
    for r in records:
        r = dict(r)
        if not r["parse_ok"]:
            r["parse_ok"], r["parsed_score"] = True, 5.0
        patched.append(r)
    with open(adjudicated, "w", encoding="utf-8") as f:
        for r in patched:
            f.write(json.dumps(r) + "\n")

    out_dir = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["analyze_final_study.py",
                                     "--records-complete-case", str(complete_case),
                                     "--records-adjudicated", str(adjudicated),
                                     "--out", str(out_dir), "--n-bootstrap", "20",
                                     "--skip-figures"])
    assert afs.main() == 0
    output = json.loads((out_dir / "final_analysis_results.json").read_text(encoding="utf-8"))
    assert set(output.keys()) >= {"complete_case", "adjudicated", "primary_measurement_basis"}
    assert output["primary_measurement_basis"] == "adjudicated"
    for name in ("results.csv", "task_level_effects_heldout_500.csv",
                "task_level_effects_full_578.csv", "task_level_effects.csv",
                "parse_failure_audit.csv", "parse_failure_report.md", "full_responses.txt",
                "condition_summary.csv", "contrast_summary.csv",
                "primary_heldout_500_analysis.json", "secondary_full_578_analysis.json",
                "bootstrap_config.json"):
        assert (out_dir / name).exists(), f"missing deliverable: {name}"


def test_main_raises_clearly_when_neither_input_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["analyze_final_study.py",
                                     "--records-complete-case", str(tmp_path / "nope1.jsonl"),
                                     "--records-adjudicated", str(tmp_path / "nope2.jsonl"),
                                     "--out", str(tmp_path / "out"), "--skip-figures"])
    with pytest.raises(SystemExit):
        afs.main()


# ---------------------------------------------------------------- Amendment A2 / S1 -------

def test_scorer_panel_is_olmo32b_not_mistral():
    """Amendment A2: the fourth scorer is allenai/Olmo-3.1-32B-Instruct, replacing the
    never-run mistralai/Mistral-Small-24B-Instruct-2501."""
    assert afs.SCORERS == ["llama", "qwen", "gemma", "olmo32b"]
    assert "mistral" not in afs.SCORERS


def test_s1_scorers_and_weights_match_frozen_clarification_c1():
    assert afs.S1_SCORERS == ["llama", "qwen", "gemma"]
    assert "olmo32b" not in afs.S1_SCORERS
    assert afs.S1_N_CELLS_PRIMARY == 6
    assert afs.S1_N_CELLS_SECONDARY == 9
    assert afs.S1_CELL_WEIGHT_PRIMARY == pytest.approx(1 / 6)
    assert afs.S1_CELL_WEIGHT_SECONDARY == pytest.approx(1 / 9)


def test_required_cells_restricts_to_the_given_scorers():
    all_cells = afs.required_cells(["arena_hard", "wildbench"])
    assert len(all_cells) == 2 * 4  # default: all 4 scorers

    s1_cells = afs.required_cells(["arena_hard", "wildbench"], afs.S1_SCORERS)
    assert len(s1_cells) == 2 * 3
    assert all(scorer in afs.S1_SCORERS for _, scorer in s1_cells)
    assert not any(scorer == "olmo32b" for _, scorer in s1_cells)


def test_fourth_scorer_cell_means_reports_olmo32b_only():
    cells = {("arena_hard", "llama"): [1.0], ("arena_hard", "olmo32b"): [2.0, 4.0],
            ("wildbench", "olmo32b"): []}
    out = afs.fourth_scorer_cell_means(cells, ["arena_hard", "wildbench"], "olmo32b")
    assert out["arena_hard"] == {"mean": pytest.approx(3.0), "n": 2}
    assert out["wildbench"] == {"mean": None, "n": 0}
    assert "llama" not in str(out)  # only the fourth scorer's own cells, nothing else


def test_s1_end_to_end_on_synthetic_data_is_present_and_non_confirmatory():
    records = _synthetic_records(seed=3)
    result = afs.analyze_one_basis(records, "complete_case", n_bootstrap=50)
    s1 = result["S1_three_scorer_sensitivity"]

    assert s1["confirmatory"] is False
    assert s1["decision_rule"] == "NONE"
    assert s1["scorers"] == ["llama", "qwen", "gemma"]
    assert s1["primary"]["n_cells"] == 6
    assert s1["primary"]["cell_weight"] == pytest.approx(1 / 6)
    assert s1["secondary"]["n_cells"] == 9
    assert s1["secondary"]["cell_weight"] == pytest.approx(1 / 9)
    assert s1["primary"]["macro_average"] is not None
    assert s1["primary"]["ci_95"]["ci_low"] <= s1["primary"]["macro_average"] \
        <= s1["primary"]["ci_95"]["ci_high"]
    assert "difference_from_four_scorer_primary" in s1["primary"]
    assert "heldout_500" in s1["fourth_scorer_cell_means"]
    assert "full_578" in s1["fourth_scorer_cell_means"]


def test_s1_never_appears_under_primary_or_secondary_and_leaves_them_unchanged():
    records = _synthetic_records(seed=4)
    result = afs.analyze_one_basis(records, "complete_case", n_bootstrap=20)
    assert "S1_three_scorer_sensitivity" not in result["primary"]
    assert "S1_three_scorer_sensitivity" not in result["secondary"]
    # the four-scorer primary/secondary keep their own frozen shape regardless of S1
    assert result["primary"]["n_cells"] == 8
    assert result["primary"]["cell_weight"] == pytest.approx(0.125)
    assert result["secondary"]["n_cells"] == 12
    assert result["secondary"]["cell_weight"] == pytest.approx(1 / 12)


def test_s1_rides_the_shared_bootstrap_draws_not_a_new_resampling():
    """bootstrap_replicates is called exactly once per measurement basis in
    analyze_one_basis; S1's replicate series (s1_primary_macro/s1_secondary_macro) must
    come from that SAME call's output dict, not a second bootstrap invocation."""
    records = _synthetic_records(seed=5, per_dataset=(4, 4, 4))
    rows_by_task, task_ids_by_dataset, task_category, _ = afs.build_index(records)
    replicate_stats, _, _ = afs.bootstrap_replicates(rows_by_task, task_ids_by_dataset,
                                                     task_category, n_reps=30)
    assert "s1_primary_macro" in replicate_stats
    assert "s1_secondary_macro" in replicate_stats
    assert len(replicate_stats["s1_primary_macro"]) <= 30
    assert len(replicate_stats["s1_primary_macro"]) > 0


def test_s1_diverges_from_four_scorer_primary_when_fourth_scorer_behaves_differently():
    """If the OLMo scorer shows a much smaller manipulation effect than the other three,
    S1 (which excludes it) should differ materially from the four-scorer primary."""
    rng = random.Random(9)
    records = []
    for ds, n in {"mtbench": 4, "arena_hard": 6, "wildbench": 6}.items():
        for i in range(n):
            tid = f"{ds}_t{i}"
            for scorer in afs.SCORERS:
                base = rng.uniform(4, 8)
                for cond in CONDITIONS:
                    bump = COND_BUMP[cond]
                    if scorer == "olmo32b":
                        bump = 0.0  # no manipulation effect at all for the fourth scorer
                    score = max(0, min(10, base + bump + rng.gauss(0, 0.2)))
                    records.append({
                        "unit_id": f"{scorer}__{ds}__{tid}__{cond}", "dataset": ds,
                        "source_task_id": tid, "category": "cat", "question": "q",
                        "candidate_answer": "a", "candidate_answer_sha256": "x",
                        "generator_model": "olmo", "generator_revision": "r",
                        "scorer_key": scorer, "scorer_model_id": scorer, "scorer_revision": "r",
                        "condition": cond, "added_context": None, "prompt": "p",
                        "response": f"Final Score: {score:.1f}/10",
                        "parse_status": "ok", "parse_tier": 1, "parsed_score": round(score, 2),
                        "parse_ok": True, "flagged_for_review": False, "parse_error": None,
                        "generation_error": None, "previously_used": False,
                        "prior_use_phases": [], "batch_size": 1, "generation_seconds": 0.1,
                        "completed_at_utc": "2026-01-01T00:00:00Z",
                    })
    result = afs.analyze_one_basis(records, "complete_case", n_bootstrap=50)
    p4 = result["primary"]["macro_average"]
    s1 = result["S1_three_scorer_sensitivity"]["primary"]["macro_average"]
    # excluding a scorer with no effect at all must push S1 meaningfully above the
    # four-scorer average that still includes it
    assert s1 > p4
