"""Strict result identity, store integrity, resume without re-execution, budget/gate stops."""
import copy
import json

import pytest

from rba import budget as B, runner as RN, units as U


def _units(calib_units, n=6):
    return [copy.deepcopy(u) for u in calib_units[:n]]


def _ledger(tmp_path, clk, caps=None, prior=0.0, status="owner_reported", margin=0.0):
    led = B.Ledger(tmp_path / "ledger.jsonl", clock=clk,
                   stage_caps=caps if caps is not None else {"s": 10.0},
                   shutdown_margin_hours=margin)
    if status is not None:
        led.record_prior_spend(prior, status, "test")
    return led


def _exe(u, **rt):
    base = {"input_token_ids_sha256": "t", "chat_template_sha256": "c",
            "transformers_version": "5.15.0", "torch_version": "x", "device_name": "d",
            "run_manifest_sha256": "m"}
    base.update(rt)
    return U.resolve(u, base)


# ---- identity --------------------------------------------------------------------------------

def test_unknown_schema_and_fields_rejected(calib_units):
    u = copy.deepcopy(calib_units[0])
    u["unit_schema"] = "rba-calib-unit-v0"
    with pytest.raises(U.SchemaError):
        U.check_planned(u)
    u = copy.deepcopy(calib_units[0])
    u["rubirc_id"] = "x"
    with pytest.raises(U.SchemaError):
        U.check_planned(u)
    u = copy.deepcopy(calib_units[0])
    u["decoding"]["max_new_tokens"] = 1024          # hash no longer matches
    with pytest.raises(U.SchemaError):
        U.check_planned(u)


def test_resolve_rejects_unresolved_and_overwrites(calib_units):
    u = calib_units[0]
    with pytest.raises(U.SchemaError):
        U.resolve(u, {"input_token_ids_sha256": "t"})
    with pytest.raises(U.SchemaError):
        _exe(u, model_revision="other")
    with pytest.raises(U.SchemaError):
        U.result_key(dict(u))


@pytest.mark.parametrize("field,value", [
    ("readout", "constrained_label_probability"), ("rubric_id", "explicit_v1"),
    ("model_revision", "deadbeef"), ("parser_sha256", "0" * 64),
    ("attn_implementation", "eager"), ("context", "unrelated_low_2")])
def test_result_key_binds_scientific_fields(calib_units, field, value):
    u = calib_units[0]
    k0 = U.result_key(_exe(u))
    e = _exe(u)
    e[field] = value
    assert U.result_key(e) != k0


def test_result_key_binds_cap_and_runtime_fields(calib_units):
    u = copy.deepcopy(calib_units[0])
    k0 = U.result_key(_exe(u))
    u["decoding"]["max_new_tokens"] = 1024
    u["decoding_sha256"] = U.sha256_obj(u["decoding"])
    assert U.result_key(_exe(u)) != k0
    assert U.result_key(_exe(calib_units[0], device_name="mock-cpu")) != k0
    assert U.result_key(_exe(calib_units[0], input_token_ids_sha256="other")) != k0


# ---- store -----------------------------------------------------------------------------------

def test_store_detects_payload_tampering_and_bad_attempt_ids(tmp_path, calib_units):
    s = U.Store(tmp_path)
    s.append(_exe(calib_units[0]), "accepted", {"text": "a", "analysis_valid": True})
    s.close()
    seg = tmp_path / "attempts.0000.jsonl"
    rec = json.loads(seg.read_text())
    bad = dict(rec, payload={"text": "b", "analysis_valid": True})
    seg.write_text(json.dumps(bad) + "\n")
    with pytest.raises(U.SchemaError, match="payload"):
        U.load(tmp_path)
    seg.write_text(json.dumps(dict(rec, attempt_index=1)) + "\n")
    with pytest.raises(U.SchemaError, match="attempt_id"):
        U.load(tmp_path)
    seg.write_text(json.dumps(dict(rec, schema="rba-calib-result-v0")) + "\n")
    with pytest.raises(U.SchemaError):
        U.load(tmp_path)


def test_store_partial_tail_preserved_interior_corruption_rejected(tmp_path, calib_units):
    s = U.Store(tmp_path)
    s.append(_exe(calib_units[0]), "accepted", {"text": "a"})
    s.close()
    seg = tmp_path / "attempts.0000.jsonl"
    with open(seg, "ab") as f:
        f.write(b'{"schema": "rba-calib-res')
    before = seg.read_bytes()
    rep = U.load(tmp_path)
    assert len(rep.attempts) == 1 and len(rep.partial_tails) == 1
    s2 = U.Store(tmp_path)
    s2.append(_exe(calib_units[1]), "accepted", {"text": "b"})
    s2.close()
    assert seg.read_bytes() == before
    seg.write_bytes(before + b"\n" + (tmp_path / "attempts.0001.jsonl").read_bytes())
    (tmp_path / "attempts.0001.jsonl").unlink()
    with pytest.raises(U.InteriorCorruption):
        U.load(tmp_path)


def test_no_attempt_after_final(tmp_path, calib_units):
    s = U.Store(tmp_path)
    e = _exe(calib_units[0])
    s.append(e, "accepted", {"text": "a"})
    with pytest.raises(U.ConflictError):
        s.append(e, "accepted", {"text": "b"})
    s.close()


# ---- runner ----------------------------------------------------------------------------------

def _verify(u):
    return [{"role": "user", "content": "x"}]


def _run(units, tmp_path, led, be, **kw):
    store = U.Store(tmp_path / "store")
    try:
        return RN.run(units, manifest_sha256="m", backend=be, store=store, ledger=led, stage="s",
                      verify_identity=kw.pop("verify", _verify),
                      projected_unit_hours=kw.pop("proj", 0.001),
                      unit_timeout_s=kw.pop("timeout", 1e9))
    finally:
        store.close()


def test_resume_never_reexecutes(tmp_path, calib_units):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk)
    us = _units(calib_units)
    be = RN.MockBackend(clock=clk, seconds_per_call=1)
    assert _run(us, tmp_path, led, be)["accepted"] == 6
    be2 = RN.MockBackend(clock=clk, seconds_per_call=1)
    st = _run(us, tmp_path, led, be2)
    assert be2.calls == [] and st["skipped_final"] == 6


def test_duplicate_unit_in_call_rejected_before_second_execution(tmp_path, calib_units):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk)
    u = _units(calib_units, 1)
    be = RN.MockBackend(clock=clk)
    with pytest.raises(B.GateFailure, match="duplicate"):
        _run(u + u, tmp_path, led, be)
    assert len(be.calls) == 1


def test_manifest_load_rejects_duplicates_and_hash_mismatch(tmp_path, calib_units):
    p = tmp_path / "m.jsonl"
    body = "".join(json.dumps(u) + "\n" for u in [calib_units[0], calib_units[0]])
    p.write_text(body)
    import hashlib
    with pytest.raises(B.GateFailure, match="duplicate"):
        RN.load_manifest(p, hashlib.sha256(body.encode()).hexdigest())
    with pytest.raises(B.GateFailure, match="hash"):
        RN.load_manifest(p, "0" * 64)


def test_budget_exhaustion_stops_immediately_without_further_calls(tmp_path, calib_units):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk, caps={"s": 1.0})
    aid = led.open("s", 1)
    be = RN.MockBackend(clock=clk, seconds_per_call=1500)     # 0.4167 h per call
    with pytest.raises(B.BudgetExhausted):
        _run(_units(calib_units), tmp_path, led, be, proj=1500 / 3600)
    assert len(be.calls) == 2                                  # third would exceed the cap
    assert any(e["type"] == "stop" for e in led.events)
    led.close(aid, "test")


def test_backend_budget_signal_propagates(tmp_path, calib_units):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk)
    us = _units(calib_units, 3)
    be = RN.MockBackend(clock=clk, raise_budget_on=us[1]["unit_id"])
    with pytest.raises(B.BudgetExhausted):
        _run(us, tmp_path, led, be)
    assert be.calls == [us[0]["unit_id"], us[1]["unit_id"]]


def test_technical_failures_retried_then_permanent_parse_failure_not_retried(tmp_path, calib_units):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk)
    us = _units(calib_units, 2)
    be = RN.MockBackend(clock=clk, fail_ids=[us[0]["unit_id"]], empty_ids=[])
    st = _run(us, tmp_path, led, be)
    assert be.calls.count(us[0]["unit_id"]) == 3 and st["permanent_failure"] == 1
    rep = U.load(tmp_path / "store")
    statuses = [r["status"] for r in rep.attempts if r["unit_id"] == us[0]["unit_id"]]
    assert statuses == ["technical_failure", "technical_failure", "permanent_failure"]
    p = RN.payload_from_generation({"text": "No score given.", "hit_token_cap": False,
                                    "emitted_terminator": True, "output_tokens": 5}, None, 512)
    assert p["analysis_valid"] is False and p["analysis_validity"] == "parse_failed"


def test_capped_parseable_output_is_invalid(tmp_path, calib_units):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk)
    us = _units(calib_units, 1)
    be = RN.MockBackend(clock=clk, capped_ids=[us[0]["unit_id"]])
    _run(us, tmp_path, led, be)
    p = U.load(tmp_path / "store").attempts[0]["payload"]
    assert p["parse_ok"] is True and p["parsed_score"] is not None
    assert p["analysis_valid"] is False and p["analysis_validity"] == "capped_incomplete"
    assert p["analysis_score"] is None


def test_prompt_identity_failure_stops_before_any_call(tmp_path, calib_units):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk)
    be = RN.MockBackend(clock=clk)

    def bad(u):
        raise B.GateFailure("prompt identity mismatch")
    with pytest.raises(B.GateFailure):
        _run(_units(calib_units), tmp_path, led, be, verify=bad)
    assert be.calls == []


def test_watchdog_stops_after_slow_unit(tmp_path, calib_units):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk)
    be = RN.MockBackend(clock=clk, seconds_per_call=100)
    with pytest.raises(B.GateFailure, match="watchdog"):
        _run(_units(calib_units), tmp_path, led, be, timeout=50)
    assert len(be.calls) == 1
    assert len(U.load(tmp_path / "store").attempts) == 1


# ---- ledger ----------------------------------------------------------------------------------

def test_ledger_persists_and_open_allocation_accrues_across_restart(tmp_path):
    clk = B.FakeClock()
    led = _ledger(tmp_path, clk, prior=2.0)
    led.open("s", 2)
    clk.advance(1800)
    del led                                              # simulated crash, no close
    clk.advance(1800)
    led2 = B.Ledger(tmp_path / "ledger.jsonl", clock=clk, stage_caps={"s": 10.0},
                    shutdown_margin_hours=0.0)
    assert led2.spent("s") == pytest.approx(2.0)          # 1 h wall x 2 devices
    assert led2.spent() == pytest.approx(4.0)             # + prior
    with pytest.raises(B.LedgerError):
        led2.open("s", 1)                                 # earlier allocation unconfirmed
    led2.close(led2.open_allocations()[0]["allocation_id"], "provider console")
    clk.advance(3600)
    assert led2.spent() == pytest.approx(4.0)


@pytest.mark.parametrize("devices", [0, -1, 1.5, True, "2"])
def test_invalid_device_counts_rejected(tmp_path, devices):
    led = _ledger(tmp_path, B.FakeClock())
    with pytest.raises(B.LedgerError):
        led.open("s", devices)


def test_unknown_or_missing_prior_spend_blocks_allocation(tmp_path):
    led = _ledger(tmp_path, B.FakeClock(), status=None)
    with pytest.raises(B.GateFailure, match="no prior-spend"):
        led.open("s", 1)
    led.record_prior_spend(None, "unknown", "vast.ai CLI activity on 17 Oct")
    with pytest.raises(B.GateFailure, match="unknown"):
        led.open("s", 1)


def test_stage_cap_reserve_and_margin(tmp_path):
    clk = B.FakeClock()
    led = B.Ledger(tmp_path / "l.jsonl", clock=clk, stage_caps={"a": 30.0},
                   shutdown_margin_hours=0.5)
    led.record_prior_spend(25.0, "owner_reported", "test")
    with pytest.raises(B.BudgetExhausted, match="usable"):
        led.check("a", 1.0)                               # 25 + 1 + 0.5 > 26 usable
    led.check("a", 0.4)
    with pytest.raises(B.GateFailure, match="no approved cap"):
        led.check("unapproved", 0.0)
    led.reserve_released = True
    led.check("a", 1.0)


def test_ledger_rejects_unterminated_tail(tmp_path):
    p = tmp_path / "ledger.jsonl"
    p.write_text('{"schema": "rba-ledger-v1", "type": "prior')
    with pytest.raises(B.LedgerError):
        B.Ledger(p)
