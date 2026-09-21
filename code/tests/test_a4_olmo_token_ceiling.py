"""Behavioural tests for Amendment A4: max_new_tokens 512 -> 2048 for olmo32b ONLY.

These assert what the execution paths actually do with the ceiling, not merely that a
constant holds a number. Every scorer other than olmo32b must still be handed 512, and the
answer generator's own 2048 must be untouched.
"""
from __future__ import annotations

import sys

import pytest

import generate_final_candidates as gfc
import run_batching_equivalence_smoke as smoke
import run_final_scoring as rfs
import verify_final_preflight_gate as vpg
from silent_influence import exact_generation as eg
from silent_influence import final_study_messages as fsm
from silent_influence import scaled_conditions as sc

REGISTRIES = {"run_final_scoring": rfs, "preflight_gate": vpg, "batching_smoke": smoke}
EXPECTED = {"llama": 512, "qwen": 512, "gemma": 512, "olmo32b": 2048}


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_every_registry_carries_the_a4_ceilings(name):
    got = {s.key: s.max_new_tokens for s in REGISTRIES[name].SCORERS}
    assert got == EXPECTED, f"{name}: {got}"


@pytest.mark.parametrize("name", sorted(REGISTRIES))
def test_only_olmo32b_moved_off_512(name):
    non_olmo = [s for s in REGISTRIES[name].SCORERS if s.key != "olmo32b"]
    assert len(non_olmo) == 3
    assert all(s.max_new_tokens == 512 for s in non_olmo), \
        [(s.key, s.max_new_tokens) for s in non_olmo]
    olmo = next(s for s in REGISTRIES[name].SCORERS if s.key == "olmo32b")
    assert olmo.max_new_tokens == 2048


def test_the_three_registries_agree_exactly():
    """A ceiling that drifted between the gate and the study would make the preflight
    unrepresentative of production."""
    seen = [tuple(sorted((s.key, s.max_new_tokens) for s in m.SCORERS))
            for m in REGISTRIES.values()]
    assert len(set(seen)) == 1, seen


def test_spec_default_is_still_512():
    """A newly declared scorer must inherit 512, not OLMo's raised ceiling."""
    assert eg.ExactModelSpec(key="new", hf_id="x", revision="r").max_new_tokens == 512


def test_answer_generation_ceiling_is_untouched_by_a4():
    assert gfc.MAX_NEW_TOKENS == 2048
    assert gfc.GENERATOR_SPEC.hf_id == "allenai/Olmo-3-7B-Instruct"


# ------------------------------------------------------- what actually reaches generate()

class _Recorder:
    """Captures the max_new_tokens each call is given, delegating to the real stub. Holds the
    original so patching eg.generate_exact_stub with this does not recurse."""

    def __init__(self):
        self.calls = []
        self._real = eg.generate_exact_stub

    def __call__(self, loaded, messages, *, max_new_tokens, seed=42, use_cache=None):
        self.calls.append((loaded.spec.key, max_new_tokens))
        return self._real(loaded, messages, max_new_tokens=max_new_tokens, seed=seed,
                          use_cache=use_cache)


def test_preflight_gate_hands_each_scorer_its_own_ceiling(tmp_path, monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(eg, "generate_exact_stub", rec)
    monkeypatch.setattr(sys, "argv", ["x", "--stub", "--out", str(tmp_path / "r.json")])
    assert vpg.main() == 0
    # The 24-render template audit deliberately generates 1 token (it inspects the rendered
    # input, not the output); the ceiling under test is the one used by the real generation
    # calls, so those single-token render probes are excluded.
    by_scorer = {}
    for key, mnt in rec.calls:
        if mnt == 1:
            continue
        by_scorer.setdefault(key, set()).add(mnt)
    assert by_scorer, "no generation calls were observed"
    # only olmo32b runs the 18-call reproducibility gate, so it is the one scorer with
    # non-render generation calls in the gate; every one of them must carry 2048.
    assert by_scorer == {"olmo32b": {2048}}, by_scorer
    assert sum(1 for k, m in rec.calls if k == "olmo32b" and m == 2048) == 18


def test_reproducibility_gate_uses_olmos_raised_ceiling():
    spec = next(s for s in vpg.SCORERS if s.key == "olmo32b")
    assert spec.max_new_tokens == 2048
    kwargs = eg.build_generate_kwargs(spec, max_new_tokens=spec.max_new_tokens,
                                      pad_token_id=0)
    assert kwargs["max_new_tokens"] == 2048
    assert kwargs["do_sample"] is False
    assert kwargs["use_cache"] is True, "A4 must not disturb C1_2's mandatory use_cache"


def test_a_raised_ceiling_does_not_change_any_other_generation_parameter():
    """A4 changes exactly one field. Everything else the builder emits must match a 512 spec."""
    olmo = next(s for s in rfs.SCORERS if s.key == "olmo32b")
    at_2048 = eg.build_generate_kwargs(olmo, max_new_tokens=2048, pad_token_id=7)
    at_512 = eg.build_generate_kwargs(olmo, max_new_tokens=512, pad_token_id=7)
    assert at_2048.pop("max_new_tokens") == 2048
    assert at_512.pop("max_new_tokens") == 512
    assert at_2048 == at_512, "only max_new_tokens may differ"


def test_a4_leaves_prompts_and_rendering_untouched():
    """The ceiling is a decoding bound; it must not appear anywhere in prompt construction."""
    prompt = sc.render_prompt("Q?", "A.", sc.resolve("no_history"))
    for key in EXPECTED:
        msgs = fsm.build_scorer_messages(key, prompt)
        blob = "".join(m["content"] for m in msgs)
        assert "2048" not in blob and "512" not in blob
        assert prompt in blob


def test_a4_does_not_alter_the_frozen_study_shape():
    assert [s.key for s in rfs.SCORERS] == ["llama", "qwen", "gemma", "olmo32b"]
    assert len(sc.CONDITIONS) == 6
    olmo = next(s for s in rfs.SCORERS if s.key == "olmo32b")
    assert olmo.revision == "ac0587e4a7744a551c059d8cd17ba220bc940dae"
    assert olmo.force_use_cache is True
    assert olmo.requires_memory_preflight is True


def test_production_scoring_path_hands_each_scorer_its_own_ceiling(monkeypatch):
    """score_one is the production single-call path. Each scorer must be generated with its
    own ceiling -- this is the assertion that actually protects the study, since the
    registries could be right while a call site still passed a study-wide constant."""
    rec = _Recorder()
    monkeypatch.setattr(eg, "generate_exact_stub", rec)
    cand = {"dataset": "arena_hard", "source_task_id": "t1", "category": "math",
            "question": "Q?", "question_sha256": "x",
            "answer": "A.", "answer_sha256": "y",
            "output_tokens": 10, "hit_token_cap": False, "generation_seconds": 0.1,
            "generator_model": "olmo", "generator_revision": "r"}
    unit = {"candidate": cand, "condition": sc.resolve("no_history")}
    for spec in rfs.SCORERS:
        loaded = eg.load_stub_model(spec)
        rfs.score_one(loaded, spec, unit, stub=True, log=lambda *_: None)
    assert dict(rec.calls) == EXPECTED, rec.calls
    assert [m for _, m in rec.calls] == [512, 512, 512, 2048]
