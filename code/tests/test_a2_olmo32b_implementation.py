"""Amendment A2 / Clarification C1 implementation tests not already covered by the
per-script test files: use_cache control plumbing in exact_generation.py, the
cache-on/cache-off equivalence primitive and its wiring into the preflight gate, the
memory-preflight primitive, and weight-shard hash verification. No GPU, no weights, no
network -- everything here either uses lightweight fakes or the deterministic stub path.
"""
from __future__ import annotations

import hashlib
import json
import sys

import pytest

import verify_final_preflight_gate as vpg
import verify_olmo32b_weight_shards as vws
from silent_influence import exact_generation as eg


# ---------------------------------------------------------------- ExactModelSpec fields ---

def test_exact_model_spec_new_fields_default_false():
    spec = eg.ExactModelSpec(key="x", hf_id="x/y", revision="r")
    assert spec.force_use_cache is False
    assert spec.requires_memory_preflight is False


def test_olmo32b_spec_in_run_final_scoring_has_both_flags_set():
    import run_final_scoring as rfs
    olmo = next(s for s in rfs.SCORERS if s.key == "olmo32b")
    assert olmo.force_use_cache is True
    assert olmo.requires_memory_preflight is True


@pytest.mark.parametrize("key", ["llama", "qwen", "gemma"])
def test_other_scorers_do_not_force_use_cache(key):
    import run_final_scoring as rfs
    spec = next(s for s in rfs.SCORERS if s.key == key)
    assert spec.force_use_cache is False
    assert spec.requires_memory_preflight is False


# ------------------------------------------------------------- build_generate_kwargs -----

def test_build_generate_kwargs_omits_use_cache_by_default_for_a_normal_scorer():
    spec = eg.ExactModelSpec(key="llama", hf_id="x", revision="r")
    kwargs = eg.build_generate_kwargs(spec, max_new_tokens=512, pad_token_id=0)
    assert "use_cache" not in kwargs
    assert kwargs["do_sample"] is False
    assert kwargs["max_new_tokens"] == 512
    assert kwargs["pad_token_id"] == 0


def test_build_generate_kwargs_auto_injects_use_cache_true_for_force_use_cache_spec():
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    kwargs = eg.build_generate_kwargs(spec, max_new_tokens=512, pad_token_id=0)
    assert kwargs["use_cache"] is True


def test_build_generate_kwargs_explicit_override_wins_over_spec_default():
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    kwargs_off = eg.build_generate_kwargs(spec, max_new_tokens=512, pad_token_id=0,
                                          use_cache=False)
    assert kwargs_off["use_cache"] is False  # explicit False beats spec.force_use_cache=True

    normal_spec = eg.ExactModelSpec(key="llama", hf_id="x", revision="r")
    kwargs_on = eg.build_generate_kwargs(normal_spec, max_new_tokens=512, pad_token_id=0,
                                         use_cache=True)
    assert kwargs_on["use_cache"] is True  # explicit True works even without force_use_cache


def test_build_generate_kwargs_never_touches_deterministic_kwargs():
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    kwargs = eg.build_generate_kwargs(spec, max_new_tokens=999, pad_token_id=42,
                                      use_cache=False)
    assert kwargs["do_sample"] is False
    assert kwargs["max_new_tokens"] == 999
    assert kwargs["pad_token_id"] == 42


# ------------------------------------------------------------- apply_use_cache_setting ---

class _FakeGenerationConfig:
    use_cache = False


class _FakeConfig:
    use_cache = False


class _FakeModelForCache:
    def __init__(self):
        self.config = _FakeConfig()
        self.generation_config = _FakeGenerationConfig()


def test_apply_use_cache_setting_sets_both_config_and_generation_config():
    m = _FakeModelForCache()
    eg.apply_use_cache_setting(m, True, log=lambda *_: None)
    assert m.config.use_cache is True
    assert m.generation_config.use_cache is True


def test_apply_use_cache_setting_handles_missing_generation_config():
    class BareModel:
        config = _FakeConfig()

    m = BareModel()
    eg.apply_use_cache_setting(m, True, log=lambda *_: None)  # must not raise
    assert m.config.use_cache is True


# ---------------------------------------------------------------- check_cache_equivalence -

def _fake_result(sha):
    return {"generated_token_ids_sha256": sha, "text": "x"}


def test_check_cache_equivalence_passes_when_all_shas_match():
    on = [_fake_result("a"), _fake_result("b"), _fake_result("c")]
    off = [_fake_result("a"), _fake_result("b"), _fake_result("c")]
    result = eg.check_cache_equivalence(on, off)
    assert result.passed
    assert result.n_mismatches == 0
    assert result.n_units == 3


def test_check_cache_equivalence_detects_a_single_mismatch():
    on = [_fake_result("a"), _fake_result("b"), _fake_result("c")]
    off = [_fake_result("a"), _fake_result("DIFFERENT"), _fake_result("c")]
    result = eg.check_cache_equivalence(on, off)
    assert not result.passed
    assert result.n_mismatches == 1
    assert result.mismatched_indices == [1]


def test_check_cache_equivalence_detects_all_mismatched():
    on = [_fake_result("a"), _fake_result("b")]
    off = [_fake_result("x"), _fake_result("y")]
    result = eg.check_cache_equivalence(on, off)
    assert result.n_mismatches == 2
    assert result.mismatched_indices == [0, 1]


def test_check_cache_equivalence_raises_on_length_mismatch():
    with pytest.raises(ValueError):
        eg.check_cache_equivalence([_fake_result("a")], [])


# -------------------------------------------------------------------- memory_preflight_ok -

def test_memory_preflight_fails_closed_without_cuda(monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    ok, details = eg.memory_preflight_ok()
    assert ok is False
    assert "not available" in details["reason"]


def test_memory_preflight_passes_when_peak_within_safety_fraction(monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 10 * 2**30)

    class FakeProps:
        total_memory = 80 * 2**30

    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda i: FakeProps())
    ok, details = eg.memory_preflight_ok(safety_fraction=0.90)
    assert ok is True
    assert details["peak_gib"] == pytest.approx(10.0)


def test_memory_preflight_fails_when_peak_exceeds_safety_fraction(monkeypatch):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda: 75 * 2**30)

    class FakeProps:
        total_memory = 80 * 2**30

    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda i: FakeProps())
    ok, details = eg.memory_preflight_ok(safety_fraction=0.90)  # threshold = 72 GiB
    assert ok is False
    assert details["safe"] is False


# ----------------------------------------------------------- preflight gate: cache checks -

def test_production_reproducibility_check_makes_18_calls_over_6_conditions():
    """Amendment A3 F2 supersedes C1_2's 12-call cache-on/off comparison with 3 cache-on
    repetitions per condition. Detailed adversarial coverage lives in test_a3_implementation."""
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    loaded = eg.load_stub_model(spec)
    result = vpg.run_production_reproducibility_check(loaded, "What is 2+2?", stub=True)
    assert result["n_calls"] == 18
    assert result["n_conditions"] == 6
    assert result["repetitions_per_condition"] == 3
    assert result["n_mismatched_conditions"] == 0
    assert result["passed"] is True


def test_production_reproducibility_check_catches_an_injected_mismatch(monkeypatch):
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    loaded = eg.load_stub_model(spec)
    real_stub = eg.generate_exact_stub
    calls = {"n": 0}

    def flaky(loaded_, messages, *, max_new_tokens, seed=42, use_cache=None):
        calls["n"] += 1
        r = real_stub(loaded_, messages, max_new_tokens=max_new_tokens, seed=seed,
                      use_cache=use_cache)
        if calls["n"] == 2:
            r = {**r, "generated_token_ids_sha256": "corrupted"}
        return r

    monkeypatch.setattr(eg, "generate_exact_stub", flaky)
    result = vpg.run_production_reproducibility_check(loaded, "What is 2+2?", stub=True)
    assert result["n_mismatched_conditions"] >= 1
    assert result["passed"] is False


def test_check_use_cache_assertion_skips_under_stub():
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    loaded = eg.load_stub_model(spec)
    report = vpg.check_use_cache_assertion(loaded, stub=True)
    assert report["skipped"] is True


def test_check_use_cache_assertion_passes_when_both_flags_are_true():
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    loaded = eg.LoadedModel(spec=spec, tokenizer=None, model=_FakeModelForCache(),
                            chat_template_sha256="x", attn_implementation="sdpa",
                            transformers_version="x")
    loaded.model.config.use_cache = True
    loaded.model.generation_config.use_cache = True
    report = vpg.check_use_cache_assertion(loaded, stub=False)
    assert report["passed"] is True


def test_check_use_cache_assertion_fails_when_config_use_cache_is_false():
    spec = eg.ExactModelSpec(key="olmo32b", hf_id="x", revision="r", force_use_cache=True)
    loaded = eg.LoadedModel(spec=spec, tokenizer=None, model=_FakeModelForCache(),
                            chat_template_sha256="x", attn_implementation="sdpa",
                            transformers_version="x")
    loaded.model.config.use_cache = False  # shipped default never got overridden
    loaded.model.generation_config.use_cache = True
    report = vpg.check_use_cache_assertion(loaded, stub=False)
    assert report["passed"] is False
    assert report["model_config_use_cache"] is False


def test_preflight_gate_reports_use_cache_and_reproducibility_only_for_olmo32b(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["verify_final_preflight_gate.py", "--stub",
                                     "--out", str(tmp_path / "report.json")])
    assert vpg.main() == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert set(report["use_cache_reports"].keys()) == {"olmo32b"}
    assert set(report["production_reproducibility_reports"].keys()) == {"olmo32b"}
    assert report["production_reproducibility_reports"]["olmo32b"]["n_calls"] == 18
    assert report["use_cache_gate_passed"] is True
    assert report["production_reproducibility_gate_passed"] is True


# --------------------------------------------------------- weight-shard hash verification -

def test_verify_weight_shard_hashes_passes_for_byte_exact_files(tmp_path):
    (tmp_path / "shard1.bin").write_bytes(b"A" * 1000)
    (tmp_path / "shard2.bin").write_bytes(b"B" * 2000)
    expected = {"shard1.bin": hashlib.sha256(b"A" * 1000).hexdigest(),
               "shard2.bin": hashlib.sha256(b"B" * 2000).hexdigest()}
    assert eg.verify_weight_shard_hashes(tmp_path, expected) == []


def test_verify_weight_shard_hashes_flags_a_mismatch(tmp_path):
    (tmp_path / "shard1.bin").write_bytes(b"A" * 1000)
    expected = {"shard1.bin": "0" * 64}
    problems = eg.verify_weight_shard_hashes(tmp_path, expected)
    assert len(problems) == 1
    assert "mismatch" in problems[0]


def test_verify_weight_shard_hashes_flags_a_missing_file(tmp_path):
    expected = {"shard_never_downloaded.bin": "0" * 64}
    problems = eg.verify_weight_shard_hashes(tmp_path, expected)
    assert len(problems) == 1
    assert "missing" in problems[0]


def test_verify_weight_shard_hashes_streams_large_files_without_reading_whole(tmp_path):
    """Regression guard: must not call Path.read_bytes() on shard files (which would try
    to load an entire ~5 GiB real shard into memory at once)."""
    big = tmp_path / "big.bin"
    content = b"Z" * (10 * 1024 * 1024)  # 10 MiB, enough to prove chunked streaming works
    big.write_bytes(content)
    expected = {"big.bin": hashlib.sha256(content).hexdigest()}
    assert eg.verify_weight_shard_hashes(tmp_path, expected) == []


def test_verify_olmo32b_weight_shards_cli_end_to_end_pass(tmp_path):
    shard_dir = tmp_path / "shards"
    shard_dir.mkdir()
    (shard_dir / "s1.bin").write_bytes(b"X" * 500)
    h = hashlib.sha256(b"X" * 500).hexdigest()
    pin = tmp_path / "fake_pin.json"
    pin.write_text(json.dumps({"weight_shard_lfs_sha256_for_later_verification":
                              {"note": "x", "s1.bin": h}}), encoding="utf-8")

    expected = vws.load_expected_shard_hashes(pin, skip_hash_check=True)
    assert expected == {"s1.bin": h}  # "note" key filtered out
    problems = eg.verify_weight_shard_hashes(shard_dir, expected)
    assert problems == []


def test_verify_olmo32b_weight_shards_pin_file_hash_gate_rejects_tampering(tmp_path):
    tampered = tmp_path / "tampered_pin.json"
    tampered.write_text('{"weight_shard_lfs_sha256_for_later_verification": {}}',
                        encoding="utf-8")
    with pytest.raises(SystemExit):
        vws.load_expected_shard_hashes(tampered, skip_hash_check=False)


def test_real_olmo32b_pin_file_shard_hashes_are_well_formed():
    """No network, no weights -- just checks the frozen pin file's recorded shard-hash
    map has the expected shape (14 shards, each a 64-hex-char sha256)."""
    from _bootstrap import REPO
    pin = json.loads((REPO / "configs/scorer_olmo3_1_32b_pin.json")
                     .read_text(encoding="utf-8"))
    shards = {k: v for k, v in
             pin["weight_shard_lfs_sha256_for_later_verification"].items() if k != "note"}
    assert len(shards) == 14
    for name, sha in shards.items():
        assert name.startswith("model-") and name.endswith(".safetensors")
        assert len(sha) == 64
        int(sha, 16)  # raises if not valid hex
