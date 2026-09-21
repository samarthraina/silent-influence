"""Phase 2D directional ablation and the no_history span.

The necessity claim rests on two mechanical properties: alpha=0 must leave the run
untouched bit for bit, and alpha=1 must remove the component along d at the listed
positions and nowhere else. Both are cheap to check without a real model.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from silent_influence import patching, spans                            # noqa: E402
from silent_influence.conditions import NO_HISTORY_CONDITION, score_condition  # noqa: E402
from silent_influence.render import render                              # noqa: E402

Q = "Explain why a covering index helps and when it does not."
A = "It removes the heap lookup.\n\nIt does not help when the query is not covered."


def _templated(prior):
    r = render(question=Q, candidate_response=A, prior=prior,
               rubric_variant="grounded", output_protocol="score_only")
    text = f"<|s|>{r.system}<|e|><|u|>{r.user}<|e|><|a|>\n"
    return text, [(i, i + 1) for i in range(len(text))], r.user


def test_no_history_rubric_span_matches_the_score_conditions():
    """The rubric block is byte-identical across conditions, so the span must be too."""
    t_nh, o_nh, u_nh = _templated(NO_HISTORY_CONDITION)
    sp_nh = spans.build_no_history(t_nh, o_nh, u_nh)

    t_s, o_s, u_s = _templated(score_condition(10))
    prefix = "In an earlier round, "
    anchor = t_s.find(prefix)
    dot = t_s.index(".", t_s.index("10/10", anchor))
    sp_s = spans.build(t_s, o_s, u_s, [dot], (anchor, dot + 1))

    got = "".join(t_nh[i] for i in sp_nh["rubric_instruction"])
    want = "".join(t_s[i] for i in sp_s["rubric_instruction"])
    assert got == want
    assert len(sp_nh["rubric_instruction"]) == len(sp_s["rubric_instruction"])


def test_no_history_spans_cover_everything():
    text, offs, user = _templated(NO_HISTORY_CONDITION)
    sp = spans.build_no_history(text, offs, user)
    assert sp[spans.BROAD] == list(range(len(text)))
    parts = [set(sp[k]) for k in spans.COARSE]
    assert set().union(*parts) == set(sp[spans.BROAD])


def _stub_model(torch):
    class Blk(torch.nn.Module):
        def forward(self, x):
            return x

    class Inner(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embed_tokens = Blk()
            self.layers = torch.nn.ModuleList([Blk(), Blk()])

    class M(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = Inner()

    return M()


def test_ablation_removes_the_component_only_where_asked():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(0)
    x = torch.randn(1, 6, 8)
    d = torch.randn(8); d = d / d.norm()

    with patching.ablate_direction(m, 1, [1, 3], d, alpha=1.0):
        y = m.model.layers[0](x)
    for i in (1, 3):
        assert torch.allclose(y[0, i] @ d, torch.zeros(()), atol=1e-5)
    for i in (0, 2, 4, 5):
        assert torch.equal(y[0, i], x[0, i])


def test_alpha_zero_is_a_bitwise_identity():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(1)
    x = torch.randn(1, 5, 8).to(torch.bfloat16)
    d = torch.randn(8); d = d / d.norm()
    with patching.ablate_direction(m, 1, [0, 2, 4], d, alpha=0.0):
        y = m.model.layers[0](x)
    assert torch.equal(y, x)


def test_alpha_scales_the_removal():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(2)
    x = torch.randn(1, 4, 8)
    d = torch.randn(8); d = d / d.norm()
    with patching.ablate_direction(m, 1, [2], d, alpha=0.5):
        y = m.model.layers[0](x)
    assert torch.allclose(y[0, 2] @ d, 0.5 * (x[0, 2] @ d), atol=1e-5)


def test_decode_step_is_left_alone():
    """A single-token forward is an incremental decode step and must not be modified."""
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    x = torch.randn(1, 1, 8)
    d = torch.randn(8); d = d / d.norm()
    with patching.ablate_direction(m, 1, [0], d, alpha=1.0):
        y = m.model.layers[0](x)
    assert torch.equal(y, x)


def test_positionwise_removes_a_different_direction_at_each_position():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(3)
    x = torch.randn(1, 6, 8)
    D = torch.randn(3, 8)
    D = D / D.norm(dim=-1, keepdim=True)
    pos = [1, 2, 5]
    with patching.ablate_positionwise(m, 1, pos, D, alpha=1.0):
        y = m.model.layers[0](x)
    for row, p in enumerate(pos):
        assert torch.allclose(y[0, p] @ D[row], torch.zeros(()), atol=1e-5)
        # the other positions' directions are untouched at this position
        assert not torch.allclose(y[0, p], x[0, p], atol=1e-4)
    for p in (0, 3, 4):
        assert torch.equal(y[0, p], x[0, p])


def test_positionwise_zero_row_leaves_its_position_alone():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(4)
    x = torch.randn(1, 4, 8)
    D = torch.randn(2, 8); D[1] = 0.0
    with patching.ablate_positionwise(m, 1, [0, 3], D, alpha=1.0):
        y = m.model.layers[0](x)
    assert torch.equal(y[0, 3], x[0, 3])
    assert not torch.equal(y[0, 0], x[0, 0])


def test_positionwise_rejects_a_shape_mismatch():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    with pytest.raises(ValueError):
        with patching.ablate_positionwise(m, 1, [0, 1, 2], torch.randn(2, 8)):
            pass


def test_steering_adds_beta_times_delta_only_where_asked():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(5)
    x = torch.randn(1, 6, 8)
    D = torch.randn(3, 8)
    pos = [1, 2, 5]
    with patching.add_positionwise(m, 1, pos, D, beta=0.5):
        y = m.model.layers[0](x)
    for row, p in enumerate(pos):
        assert torch.allclose(y[0, p], x[0, p] + 0.5 * D[row], atol=1e-5)
    for p in (0, 3, 4):
        assert torch.equal(y[0, p], x[0, p])


def test_steering_beta_zero_is_a_bitwise_identity():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(6)
    x = torch.randn(1, 5, 8).to(torch.bfloat16)
    D = torch.randn(3, 8)
    with patching.add_positionwise(m, 1, [0, 2, 4], D, beta=0.0):
        y = m.model.layers[0](x)
    assert torch.equal(y, x)


def test_steering_zero_vector_is_a_bitwise_identity():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(7)
    x = torch.randn(1, 5, 8).to(torch.bfloat16)
    with patching.add_positionwise(m, 1, [0, 2, 4], torch.zeros(3, 8), beta=1.0):
        y = m.model.layers[0](x)
    assert torch.equal(y, x)


def test_steering_plus_and_minus_beta_are_equal_and_opposite():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    torch.manual_seed(8)
    x = torch.randn(1, 4, 8)
    D = torch.randn(2, 8)
    with patching.add_positionwise(m, 1, [0, 1], D, beta=1.0):
        up = m.model.layers[0](x)
    with patching.add_positionwise(m, 1, [0, 1], D, beta=-1.0):
        dn = m.model.layers[0](x)
    assert torch.allclose(up[0, :2] - x[0, :2], -(dn[0, :2] - x[0, :2]), atol=1e-6)


def test_steering_rejects_a_shape_mismatch():
    torch = pytest.importorskip("torch")
    m = _stub_model(torch)
    with pytest.raises(ValueError):
        with patching.add_positionwise(m, 1, [0, 1, 2], torch.randn(2, 8)):
            pass
