"""Integration: missing or unconfirmed approvals stop the calibration entry point before any
backend is constructed, any model is loaded or anything is generated. The real gates file
is never modified; the positive path uses a temporary, synthetic gates file and the mock
backend only."""
import json

import pytest

from conftest import ART, EXT
from rba import budget as B, gates as G, launch as L, runner as RN
from rba.legacy import exact_generation as eg

MANIFEST = ART / "calibration/run_manifest_v1.jsonl"
MSHA = (ART / "calibration/run_manifest_v1.sha256").read_text().split()[0]
REAL_GATES = ART / "EXECUTION_GATES_v1.json"


@pytest.fixture(autouse=True)
def forbid_real_model(monkeypatch):
    """Any attempt to load a model or tokenize/generate through the original path fails."""
    def boom(*a, **k):
        raise AssertionError("real model path reached")
    for name in ("load_exact_model", "generate_exact", "encode_chat", "generate_exact_batch"):
        monkeypatch.setattr(eg, name, boom)


class Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, model_key, auth):
        self.calls.append(model_key)
        raise AssertionError("backend must not be constructed")


def _ledger(tmp_path, prior=True, cap=10.0):
    clk = B.FakeClock()
    led = B.Ledger(tmp_path / "ledger.jsonl", clock=clk,
                   stage_caps={L.STAGE: cap} if cap else None, shutdown_margin_hours=0.0)
    if prior:
        led.record_prior_spend(0.0, "owner_reported", "SYNTHETIC test entry")
    return led, clk


def _gates(tmp_path, confirm=G.REQUIRED["calibration_run"], evidence="ref"):
    d = G.blank()
    for g in confirm:
        d["gates"][g] = {"confirmed": True, "evidence": evidence, "confirmed_by": "test"}
    p = tmp_path / "gates.json"
    p.write_text(json.dumps(d))
    return p


def _blank(tmp_path):
    p = tmp_path / "blank_gates.json"
    p.write_text(json.dumps(G.blank()))
    return p


def _launch(gates_path, ledger, factory, tmp_path):
    return L.launch_calibration(gates_path=gates_path, manifest_path=MANIFEST,
                                manifest_sha256=MSHA, store_dir=tmp_path / "store",
                                ledger=ledger, verify_identity=lambda u: [{"role": "user", "content": "x"}],
                                projected_unit_hours=1e-4, unit_timeout_s=1e9,
                                backend_factory=factory)


@pytest.mark.parametrize("make_gates", [
    lambda tmp: _blank(tmp),                                           # nothing confirmed
    lambda tmp: tmp / "missing.json",                                  # no file
    lambda tmp: _gates(tmp, evidence=None),                            # confirmed without evidence
    lambda tmp: _gates(tmp, confirm=("gpu_budget_confirmed", "release_rules_confirmed")),
])
def test_unapproved_launch_never_constructs_a_backend(tmp_path, make_gates):
    led, _ = _ledger(tmp_path)
    before = list(led.events)
    spy = Spy()
    with pytest.raises(B.GateFailure):
        _launch(make_gates(tmp_path), led, spy, tmp_path)
    assert spy.calls == []
    assert led.events == before and not led.open_allocations()
    assert not (tmp_path / "store").exists()


def test_real_gates_keep_inclusion_and_annotation_blocked():
    rec = json.loads(REAL_GATES.read_text())
    for g in ("release_rules_confirmed", "annotators_confirmed"):
        assert rec["gates"][g]["confirmed"] is False
    for action in ("results_inclusion", "annotation_distribution"):
        with pytest.raises(B.GateFailure):
            G.require(REAL_GATES, action)
    assert "release_rules_confirmed" not in G.REQUIRED["calibration_run"]


@pytest.mark.parametrize("prior,cap", [(False, 10.0), (True, None), (True, 0.001)])
def test_approved_gates_still_blocked_by_ledger_before_backend(tmp_path, prior, cap):
    led, _ = _ledger(tmp_path, prior=prior, cap=cap)
    spy = Spy()
    with pytest.raises((B.GateFailure, B.BudgetExhausted)):
        _launch(_gates(tmp_path), led, spy, tmp_path)
    assert spy.calls == []


def test_default_factory_with_unapproved_gates_never_reaches_hf(tmp_path, monkeypatch):
    inits = []
    real_init = RN.HFBackend.__init__
    monkeypatch.setattr(RN.HFBackend, "__init__",
                        lambda self, *a, **k: (inits.append(1), real_init(self, *a, **k)))
    led, _ = _ledger(tmp_path)
    with pytest.raises(B.GateFailure):
        L.launch_calibration(gates_path=_blank(tmp_path), manifest_path=MANIFEST, manifest_sha256=MSHA,
                             store_dir=tmp_path / "s", ledger=led, verify_identity=lambda u: [],
                             projected_unit_hours=1e-4, unit_timeout_s=1e9)
    assert inits == []


@pytest.mark.parametrize("auth", [None, "approved", object()])
def test_hf_backend_refuses_without_genuine_authorization(auth):
    with pytest.raises(B.GateFailure):
        RN.HFBackend("llama", "meta-llama/Llama-3.1-8B-Instruct", "rev", False, authorization=auth)


def test_authorization_cannot_be_forged_or_reused_for_another_action(tmp_path):
    with pytest.raises(B.GateFailure):
        G.Authorization("calibration_run", "x", ("me",))
    d = G.blank()
    for g in G.REQUIRED["annotation_distribution"]:
        d["gates"][g] = {"confirmed": True, "evidence": "ref", "confirmed_by": "test"}
    p = tmp_path / "g.json"
    p.write_text(json.dumps(d))
    ann_auth = G.require(p, "annotation_distribution")
    with pytest.raises(B.GateFailure, match="not 'calibration_run'"):
        RN.HFBackend("llama", "m", "r", False, authorization=ann_auth)


def test_hf_backend_load_rechecks_authorization(tmp_path):
    auth = G.require(_gates(tmp_path), "calibration_run")
    be = RN.HFBackend("llama", "meta-llama/Llama-3.1-8B-Instruct", "rev", False, authorization=auth)
    object.__setattr__(be, "authorization", None)
    with pytest.raises(B.GateFailure):
        be.load()


def test_cli_entry_point_blocked_before_any_import(tmp_path, capsys, monkeypatch):
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("run_calibration_cli",
                                                  EXT / "scripts/run_calibration.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.delitem(sys.modules, "rba.launch", raising=False)
    monkeypatch.setattr(cli, "GATES", _blank(tmp_path))
    rc = cli.main(["--ledger", str(tmp_path / "l.jsonl"), "--store", str(tmp_path / "s"),
                   "--stage-cap-hours", "1", "--projected-unit-seconds", "10",
                   "--unit-timeout-seconds", "60"])
    assert rc == 2 and "BLOCKED" in capsys.readouterr().err
    assert not (tmp_path / "l.jsonl").exists() and not (tmp_path / "s").exists()
    assert "rba.launch" not in sys.modules


def test_synthetic_mock_path_runs_only_with_temporary_approval(tmp_path):
    led, clk = _ledger(tmp_path)
    seen = []

    def factory(model_key, auth):
        G.check_authorization(auth, "calibration_run")
        seen.append(model_key)
        return RN.MockBackend(clock=clk, seconds_per_call=1)
    aid = led.open(L.STAGE, 1, "synthetic")
    out = _launch(_gates(tmp_path), led, factory, tmp_path)
    led.close(aid, "test")
    assert seen == ["llama", "qwen"]
    assert out["llama"]["accepted"] == 180 and out["qwen"]["accepted"] == 180


def test_backend_accepts_patching_study_authorization_but_not_annotation(tmp_path):
    d = G.blank()
    for g in G.GATES:
        d["gates"][g] = {"confirmed": True, "evidence": "ref", "confirmed_by": "test"}
    p = tmp_path / "all.json"
    p.write_text(json.dumps(d))
    for action in ("mhp_study_run", "mhp_qwen_study_run", "calibration_run", "engineering_preflight"):
        RN.HFBackend("llama", "m", "r", False, authorization=G.require(p, action))
    for action in ("annotation_distribution", "results_inclusion"):
        with pytest.raises(B.GateFailure):
            RN.HFBackend("llama", "m", "r", False, authorization=G.require(p, action))
