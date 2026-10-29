"""Matched-history patching (rba-mhp-v1): manifest, hook location, endpoints, gating."""
import hashlib
import json
from collections import Counter

import pytest

from conftest import ART, EXT
from rba import gates as G, inputs as I, mhp as M
from rba.budget import GateFailure
from rba.legacy import scaled_conditions as sc

MAN = EXT / "matched_history_patching/mhp_manifest_v1.jsonl"


def _units():
    return [json.loads(l) for l in open(MAN)]


def test_manifest_is_ext72_verbatim_with_full_unit_set():
    u = _units()
    assert hashlib.sha256(MAN.read_bytes()).hexdigest() == \
        (EXT / "matched_history_patching/mhp_manifest_v1.sha256").read_text().split()[0]
    ext72 = [f"{t['dataset']}/{t['task_id']}" for t in I.load_json("ext72_manifest")["tasks"]]
    assert [x["base_task_id"] for x in u[::10]] == ext72
    assert len(u) == 720 and len({x["unit_id"] for x in u}) == 720
    per = Counter((x["kind"], x["layer"]) for x in u)
    assert per == {("baseline", None): 144, ("patch", 24): 144, ("patch", 2): 144,
                   ("noop", 24): 144, ("same_state", 24): 144}
    for x in u:
        assert x["model"]["revision"] == "0e9e39f249a16976918f6564b8830bc894c89659"
        assert x["decoding"]["max_new_tokens"] == 512 and x["position"] == "final_input"
        if x["kind"] == "patch":
            assert {x["source"], x["target"]} == {"self_high_10", "self_low_2"}


def test_conditions_are_the_exact_original_sentences_and_differ_only_there(tasks):
    hi, lo = sc.resolve("self_high_10"), sc.resolve("self_low_2")
    assert hi.added_context == "The model that generated the content previously scored your answer 10/10."
    assert lo.added_context == "The model that generated the content previously scored your answer 2/10."
    t = tasks["mtbench/104"]
    a = sc.render_prompt(t["question"], t["answer"], hi)
    b = sc.render_prompt(t["question"], t["answer"], lo)
    assert a.replace("10/10.", "2/10.", 1) == b and a.endswith(t["answer"])


def test_hook_location_matches_original_indexing():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import LlamaConfig, LlamaForCausalLM
    from rba.legacy import patching as PT
    torch.manual_seed(0)
    m = LlamaForCausalLM(LlamaConfig(vocab_size=64, hidden_size=16, intermediate_size=32,
                                     num_hidden_layers=4, num_attention_heads=2,
                                     num_key_value_heads=1, attn_implementation="eager")).eval()
    ids = torch.randint(0, 64, (1, 9))
    cap = PT.capture_states(m, ids, {"final_input": [8]}, 4)
    # legacy layer L hooks model.model.layers[L-1]: patching L=2 with block-1 output is identity
    base = m(input_ids=ids).logits
    with PT.patch_positions(m, 2, [8], cap["final_input"][2]):
        same = m(input_ids=ids).logits
    assert torch.equal(base, same)
    with PT.patch_positions(m, 2, [8], cap["final_input"][2] + 1.0):
        moved = m(input_ids=ids).logits
    assert torch.equal(moved[0, :8], base[0, :8]) and not torch.equal(moved[0, 8], base[0, 8])
    assert M.SITE_LAYER == 24 and M.CONTROL_LAYER == 2


def _scores(gaps, patched):
    s = {}
    for t, (h, l) in gaps.items():
        s[(t, "baseline:self_high_10")] = h
        s[(t, "baseline:self_low_2")] = l
    for (t, key), v in patched.items():
        s[(t, key)] = v
    return s


def test_endpoints_raw_normalized_zero_gap_and_sensitivity():
    gaps = {"a": (9.0, 5.0), "b": (8.0, 8.0), "c": (7.0, 6.5), "d": (9.0, None)}
    p = {("a", "patch:L24:self_high_10->self_low_2"): 7.0,
         ("b", "patch:L24:self_high_10->self_low_2"): 8.0,
         ("c", "patch:L24:self_high_10->self_low_2"): 6.5,
         ("a", "patch:L2:self_high_10->self_low_2"): 5.0,
         ("c", "patch:L2:self_high_10->self_low_2"): 6.5}
    r = M.analyze(_scores(gaps, p), ["a", "b", "c", "d"])
    L = r["self_high_10->self_low_2"]["L24"]
    assert L["n_complete"] == 3 and L["missing_or_invalid"] == 1
    assert L["raw_movement_mean"] == pytest.approx((2 + 0 + 0) / 3)
    assert L["zero_gap_excluded"] == 1 and L["normalized_n"] == 2
    assert L["normalized_mean"] == pytest.approx((0.5 + 0.0) / 2)
    assert L["unchanged_fraction"] == pytest.approx(2 / 3)
    pr = r["self_high_10->self_low_2"]["paired_site_minus_control"]
    assert pr["n"] == 2 and pr["mean"] == pytest.approx((0.5 - 0) / 2 + (0 - 0) / 2)
    assert r["baseline_high_minus_low"]["n_zero"] == 1
    rs = M.analyze(_scores(gaps, p), ["a", "b", "c", "d"], min_gap=1.0)
    assert rs["self_high_10->self_low_2"]["L24"]["small_gap_excluded"] == 1
    assert rs["self_high_10->self_low_2"]["L24"]["normalized_n"] == 1


def test_identity_report_flags_failures():
    tok = {("a", "baseline:self_high_10"): "x", ("a", "noop:self_high_10"): "x",
           ("a", "same_state:self_high_10"): "y"}
    r = M.identity_report(tok, ["a"])
    assert r["checked"] == 2 and r["failures"] == [("a", "same_state:self_high_10")]


def test_public_release_never_carries_execution_approval(tmp_path):
    rec = json.loads((ART / "EXECUTION_GATES_v1.json").read_text())
    assert all(g["confirmed"] is False for g in rec["gates"].values())
    for action in ("calibration_run", "mhp_study_run", "mhp_qwen_study_run"):
        with pytest.raises(GateFailure):
            G.require(ART / "EXECUTION_GATES_v1.json", action)
    q = tmp_path / "q.json"
    q.write_text(json.dumps(G.blank()))
    with pytest.raises(GateFailure):
        G.require(q, "mhp_qwen_study_run")
    p = tmp_path / "g.json"
    p.write_text(json.dumps(G.blank()))
    with pytest.raises(GateFailure):
        G.require(p, "mhp_study_run")


def test_qwen_manifest_mirrors_llama_except_model_and_site():
    q = [json.loads(l) for l in open(EXT / "matched_history_patching_qwen/mhp_qwen_manifest_v1.jsonl")]
    l = _units()
    assert len(q) == 720 and [x["base_task_id"] for x in q] == [x["base_task_id"] for x in l]
    for a, b in zip(l, q):
        assert (a["kind"], a["source"], a["target"]) == (b["kind"], b["source"], b["target"])
        assert b["layer"] == (27 if a["layer"] == 24 else a["layer"])
        assert b["model"]["revision"] == "b968826d9c46dd6066d109eabc6255188de91218"
        assert b["decoding"] == a["decoding"]
    assert M.MODELS["qwen"]["site_layer"] == 27


def test_source_directed_movement_and_identity_exclusion():
    gaps = {"a": (9.0, 5.0), "b": (5.0, 9.0)}
    p = {("a", "patch:L24:self_high_10->self_low_2"): 7.0, ("a", "patch:L2:self_high_10->self_low_2"): 5.0,
         ("b", "patch:L24:self_high_10->self_low_2"): 9.0, ("b", "patch:L2:self_high_10->self_low_2"): 8.0}
    r = M.analyze(_scores(gaps, p), ["a", "b"])
    L = r["self_high_10->self_low_2"]
    # a: gap +4, moved +2 toward source; b: gap -4, moved 0 -> directed 0; L2: a 0, b +1 (toward source)
    assert L["L24"]["source_directed_points_mean"] == pytest.approx(1.0)
    assert L["L2"]["source_directed_points_mean"] == pytest.approx(0.5)
    assert L["paired_site_minus_control"]["source_directed_points_mean"] == pytest.approx(0.5)
    r2 = M.analyze(_scores(gaps, p), ["a", "b"], exclude_tasks=["a"])
    assert r2["excluded_tasks_pending_identity_investigation"] == ["a"]
    assert r2["self_high_10->self_low_2"]["L24"]["n_complete"] == 1
