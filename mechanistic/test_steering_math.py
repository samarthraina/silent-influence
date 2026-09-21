"""Targeted tests for the steering / ablation arms only.

These exercise the real hooks in silent_influence.patching against a tiny stub module that
presents the same .model.layers interface, so the arithmetic is genuinely executed rather
than asserted about. No weights, no GPU.
"""
import pathlib
import sys

import pytest
import torch
import torch.nn as nn

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent / "code"
sys.path.insert(0, str(REPO / "src"))
from silent_influence import patching

HID, SEQ = 8, 5
POS = [4]


class _Block(nn.Module):
    def forward(self, x):
        return x


class _Inner(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed_tokens = _Block()
        self.layers = nn.ModuleList([_Block() for _ in range(4)])


class _Model(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = _Inner()

    def run(self, x, layer):
        return self.model.layers[layer - 1](x)


@pytest.fixture
def m():
    return _Model()


@pytest.fixture
def hs():
    torch.manual_seed(0)
    return torch.randn(1, SEQ, HID)


def test_beta_zero_steering_is_exact_identity(m, hs):
    d = torch.randn(1, HID)
    with patching.add_positionwise(m, 2, POS, d, beta=0.0):
        out = m.run(hs.clone(), 2)
    assert torch.equal(out, hs)


def test_alpha_zero_ablation_is_exact_identity(m, hs):
    d = torch.randn(HID)
    with patching.ablate_direction(m, 2, POS, d, alpha=0.0):
        out = m.run(hs.clone(), 2)
    assert torch.equal(out, hs)


def test_steering_adds_beta_times_delta_at_the_listed_position(m, hs):
    d = torch.randn(1, HID)
    beta = 1.5
    with patching.add_positionwise(m, 2, POS, d, beta=beta):
        out = m.run(hs.clone(), 2)
    expected = hs[0, POS[0], :] + beta * d[0]
    assert torch.allclose(out[0, POS[0], :], expected, atol=1e-5)


def test_steering_touches_no_other_position(m, hs):
    d = torch.randn(1, HID)
    with patching.add_positionwise(m, 2, POS, d, beta=2.0):
        out = m.run(hs.clone(), 2)
    others = [i for i in range(SEQ) if i not in POS]
    assert torch.equal(out[0, others, :], hs[0, others, :])


def test_full_ablation_removes_the_component_along_the_direction(m, hs):
    d = torch.randn(HID)
    with patching.ablate_direction(m, 2, POS, d, alpha=1.0):
        out = m.run(hs.clone(), 2)
    u = d / d.norm()
    residual = float(out[0, POS[0], :].float() @ u)
    assert abs(residual) < 1e-4, residual


def test_ablation_is_scale_invariant_in_the_direction(m, hs):
    d = torch.randn(HID)
    with patching.ablate_direction(m, 2, POS, d, alpha=1.0):
        a = m.run(hs.clone(), 2)
    with patching.ablate_direction(m, 2, POS, d * 7.3, alpha=1.0):
        b = m.run(hs.clone(), 2)
    assert torch.allclose(a, b, atol=1e-5)


def test_hooks_are_removed_after_the_context_exits(m, hs):
    d = torch.randn(1, HID)
    with patching.add_positionwise(m, 2, POS, d, beta=3.0):
        pass
    assert torch.equal(m.run(hs.clone(), 2), hs)


def test_decode_step_is_left_untouched(m):
    """seq len 1 is an incremental decode step; the hooks must not fire there, otherwise
    the intervention would be re-applied at every generated token."""
    one = torch.randn(1, 1, HID)
    d = torch.randn(1, HID)
    with patching.add_positionwise(m, 2, [0], d, beta=5.0):
        assert torch.equal(m.run(one.clone(), 2), one)


# ---- the norm-matched random control --------------------------------------------------

def _random_like(D, seed):
    g = torch.Generator(device="cpu").manual_seed(seed)
    R = torch.randn(D.shape, generator=g)
    return R / R.norm() * D.norm()


def test_random_control_is_norm_matched_and_deterministic():
    D = torch.randn(HID) * 3.7
    a, b = _random_like(D, 20260818), _random_like(D, 20260818)
    assert torch.equal(a, b)                                  # fixed seed reproduces
    assert abs(float(a.norm() - D.norm())) < 1e-5             # norm matched
    assert abs(float(torch.nn.functional.cosine_similarity(a, D, dim=0))) < 0.95


def test_direction_is_the_mean_of_endpoint_differences():
    torch.manual_seed(1)
    lo = [torch.randn(HID) for _ in range(12)]
    hi = [torch.randn(HID) for _ in range(12)]
    D = torch.stack([h - l for h, l in zip(hi, lo)]).mean(0)
    assert torch.allclose(D, torch.stack(hi).mean(0) - torch.stack(lo).mean(0), atol=1e-6)
