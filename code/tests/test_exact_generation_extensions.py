"""Tests for the final-study extensions to exact_generation.py: determinism reset, the
residency gate, batching, and EOS trimming. No GPU, no weights -- uses the stub path and
lightweight fakes standing in for torch tensors/modules."""
from __future__ import annotations

from silent_influence import exact_generation as eg


class _FakeDevice:
    def __init__(self, type_):
        self.type = type_


class _FakeTensor:
    def __init__(self, device_type="cuda", dtype="bf16"):
        self.device = _FakeDevice(device_type)
        self.dtype = dtype


class _FakeConfig:
    quantization_config = None


class _FakeModel:
    def __init__(self, params, buffers, hf_device_map=None):
        self._params = params
        self._buffers = buffers
        self.hf_device_map = hf_device_map
        self.config = _FakeConfig()

    def named_parameters(self):
        return iter(self._params.items())

    def named_buffers(self):
        return iter(self._buffers.items())


BF16 = "torch.bfloat16"


def _import_real_bf16():
    import torch
    return torch.bfloat16


def test_check_gpu_residency_passes_when_everything_on_cuda_and_bf16():
    bf16 = _import_real_bf16()
    model = _FakeModel(
        params={"w": _FakeTensor("cuda", bf16)},
        buffers={"b": _FakeTensor("cuda", bf16)},
    )
    assert eg.check_gpu_residency(model) == []


def test_check_gpu_residency_flags_cpu_parameter():
    bf16 = _import_real_bf16()
    model = _FakeModel(params={"w": _FakeTensor("cpu", bf16)}, buffers={})
    problems = eg.check_gpu_residency(model)
    assert any("w" in p and "cpu" in p for p in problems)


def test_check_gpu_residency_flags_non_bf16_parameter():
    model = _FakeModel(params={"w": _FakeTensor("cuda", "torch.float32")}, buffers={})
    problems = eg.check_gpu_residency(model)
    assert any("dtype" in p for p in problems)


def test_check_gpu_residency_flags_offloaded_hf_device_map():
    bf16 = _import_real_bf16()
    model = _FakeModel(params={"w": _FakeTensor("cuda", bf16)}, buffers={},
                       hf_device_map={"layer.0": "cuda:0", "layer.1": "cpu"})
    problems = eg.check_gpu_residency(model)
    assert any("hf_device_map" in p for p in problems)


def test_check_gpu_residency_flags_quantization_config():
    bf16 = _import_real_bf16()
    model = _FakeModel(params={"w": _FakeTensor("cuda", bf16)}, buffers={})
    model.config.quantization_config = {"load_in_4bit": True}
    problems = eg.check_gpu_residency(model)
    assert any("quantization_config" in p for p in problems)


def test_check_gpu_residency_buffer_device_checked_even_when_dtype_exempt():
    bf16 = _import_real_bf16()
    model = _FakeModel(params={"w": _FakeTensor("cuda", bf16)},
                       buffers={"inv_freq": _FakeTensor("cpu", "torch.float32")})
    problems = eg.check_gpu_residency(model)
    assert any("buffer" in p and "inv_freq" in p for p in problems)


def test_reset_generation_config_neutralizes_shipped_sampling_defaults():
    class FakeGenConfig:
        do_sample = True
        temperature = 0.15
        top_p = 0.9
        top_k = 40

    class FakeModel:
        generation_config = FakeGenConfig()

    m = FakeModel()
    eg.reset_generation_config_for_determinism(m, log=lambda *_: None)
    assert m.generation_config.do_sample is False
    assert m.generation_config.temperature is None
    assert m.generation_config.top_p is None
    assert m.generation_config.top_k is None


def test_reset_generation_config_handles_missing_generation_config():
    class FakeModel:
        pass

    eg.reset_generation_config_for_determinism(FakeModel(), log=lambda *_: None)  # no raise


def test_trim_to_first_eos_keeps_up_to_and_including_first_eos():
    assert eg.trim_to_first_eos([5, 6, 2, 7, 2, 2], eos_token_id=2) == [5, 6, 2]


def test_trim_to_first_eos_returns_whole_sequence_when_no_eos_present():
    assert eg.trim_to_first_eos([5, 6, 7], eos_token_id=2) == [5, 6, 7]


def test_stub_batch1_and_batched_generation_agree_on_token_ids():
    """The stub is deterministic per-message, so the batching harness's comparison logic
    (which the real GPU smoke test will apply to genuine model output) should see a clean
    pass here -- this exercises the harness, not real model behavior."""
    spec = eg.ExactModelSpec(key="fake", hf_id="fake/fake", revision="x")
    loaded = eg.load_stub_model(spec)
    messages_list = [
        [{"role": "user", "content": "task A"}],
        [{"role": "user", "content": "task B"}],
        [{"role": "user", "content": "task C"}],
    ]
    batch1 = [eg.generate_exact_stub(loaded, m, max_new_tokens=16) for m in messages_list]
    batched = eg.generate_exact_batch_stub(loaded, messages_list, max_new_tokens=16)

    assert len(batched) == 3
    for r1, rb in zip(batch1, batched):
        assert r1["generated_token_ids_sha256"] == rb["generated_token_ids_sha256"]
        assert r1["text"] == rb["text"]


def test_stub_different_messages_get_different_token_ids():
    spec = eg.ExactModelSpec(key="fake", hf_id="fake/fake", revision="x")
    loaded = eg.load_stub_model(spec)
    a = eg.generate_exact_stub(loaded, [{"role": "user", "content": "alpha"}], max_new_tokens=8)
    b = eg.generate_exact_stub(loaded, [{"role": "user", "content": "beta"}], max_new_tokens=8)
    assert a["generated_token_ids_sha256"] != b["generated_token_ids_sha256"]
