"""Matched-history patching executor (Llama rba-mhp-v1 / Qwen rba-mhp-qwen-v1).

Modes:
  --mode study  units from the frozen manifest; gate 'mhp_study_run' (llama) or
                'mhp_qwen_study_run' (qwen)
  --mode smoke  ENGINEERING tasks only (the timing-gate tasks, never the 72 study tasks);
                gate 'engineering_preflight'; outputs never enter any estimate

Per task: native prompts for self_high_10 / self_low_2 (vendored original renderer and
message envelope), final-input index = last token of each native encoding, one prefill-only
capture per condition (original patching.capture_states), then the 10 generations with the
original patching.patch_positions / no_patch hooks. Attempts are append-only JSONL with
payload hashes; a resume skips units that already have a final attempt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

EXT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXT / "src"))
from rba import gates as G  # noqa: E402

MAX_ATTEMPTS = 3


def canon(o):
    return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=("llama", "qwen"), required=True)
    ap.add_argument("--mode", choices=("study", "smoke"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--stage-cap-hours", type=float, default=None)
    ap.add_argument("--projected-task-seconds", type=float, required=True)
    ap.add_argument("--smoke-tasks", type=int, default=2)
    a = ap.parse_args()
    action = ("engineering_preflight" if a.mode == "smoke" else
              {"llama": "mhp_study_run", "qwen": "mhp_qwen_study_run"}[a.model])
    auth = G.require(EXT / "artifacts/EXECUTION_GATES_v1.json", action)

    from rba import calib as C, inputs as I, mhp as M, runner as RN
    from rba.budget import GateFailure, Ledger
    from rba.legacy import patching as PT, scaled_conditions as sc
    caps = {a.stage: a.stage_cap_hours} if a.stage_cap_hours is not None else None
    led = Ledger(Path(a.ledger), stage_caps=caps, shutdown_margin_hours=0.25)
    m = M.MODELS[a.model]
    tasks = {f"{x['dataset']}/{x['source_task_id']}": x for x in I.load_json("answers")["accepted"]}

    if a.mode == "study":
        mdir = EXT / ("matched_history_patching" if a.model == "llama" else "matched_history_patching_qwen")
        man = mdir / ("mhp_manifest_v1.jsonl" if a.model == "llama" else "mhp_qwen_manifest_v1.jsonl")
        sha_rec = (man.parent / (man.stem + ".sha256")).read_text().split()[0]
        raw = man.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha_rec:
            raise GateFailure("patching manifest hash mismatch")
        units = [json.loads(l) for l in raw.decode().splitlines() if l.strip()]
    else:
        tim = [json.loads(l) for l in open(EXT / "artifacts/engineering/timing_gate_manifest_v1.jsonl")]
        eng = sorted({u["base_task_id"] for u in tim})[: a.smoke_tasks]
        units = [dict(u, unit_id="SMOKE|" + u["unit_id"], readout="engineering_timing_only")
                 for u in M.build_units(eng, a.model)]
    if len({u["unit_id"] for u in units}) != len(units):
        raise GateFailure("duplicate unit ids")
    assert all(u["model"]["revision"] == m["revision"] for u in units)
    if a.mode == "study":
        for u in units:
            task = tasks[u["base_task_id"]]
            for role in ("source", "target"):
                condition = u[role]
                if condition is None:
                    continue
                prompt = sc.render_prompt(task["question"], task["answer"], sc.resolve(condition))
                if hashlib.sha256(prompt.encode()).hexdigest() != u[role + "_prompt_sha256"]:
                    raise GateFailure(f"{role} prompt hash mismatch for {u['unit_id']}")

    out = Path(a.out) / f"{a.mode}_{a.model}"
    out.mkdir(parents=True, exist_ok=True)
    from rba import mhp_store as MS
    store = MS.Writer(out)                 # quarantines a partial tail; rejects other corruption
    final, n_att = store.final, store.next
    if store.quarantined:
        print("QUARANTINED incomplete trailing record(s):", store.quarantined, flush=True)
    planned_ids = {u["unit_id"] for u in units}
    unexpected = {r["unit_id"] for r in store.records} - planned_ids
    if unexpected:
        raise GateFailure(f"records for units not in this manifest: {sorted(unexpected)[:3]}")

    def record(u, status, payload):
        store.append(u["unit_id"], status, payload,
                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    # Check the ledger before loading weights, not only before each task.
    led.check(a.stage, a.projected_task_seconds / 3600)
    import torch
    be = RN.HFBackend(a.model, m["hf_id"], m["revision"], m["disable_thinking"], authorization=auth)
    be.load()
    eg, model, tok = be.eg, be.loaded.model, be.loaded.tokenizer
    n_layers = model.config.num_hidden_layers
    meta = {"model": a.model, "mode": a.mode, "action": action, "torch": torch.__version__,
            "transformers": be.loaded.transformers_version, "attn": be.loaded.attn_implementation,
            "dtype": str(next(model.parameters()).dtype), "device": torch.cuda.get_device_name(0),
            "chat_template_sha256": be.loaded.chat_template_sha256, "n_layers": n_layers,
            "site_layer": m["site_layer"], "hook_module_site": f"model.model.layers[{m['site_layer'] - 1}]",
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    assert 2 <= m["site_layer"] <= n_layers - 4
    (out / f"run_meta_{int(time.time())}.json").write_text(json.dumps(meta, indent=2))

    by_task = {}
    for u in units:
        by_task.setdefault(u["base_task_id"], []).append(u)
    for ti, (b, tu) in enumerate(by_task.items(), 1):
        if all(u["unit_id"] in final for u in tu):
            continue
        led.check(a.stage, a.projected_task_seconds / 3600)
        t = tasks[b]
        enc, fin, cap, msgs = {}, {}, {}, {}
        for cond in M.CONDS:
            p = sc.render_prompt(t["question"], t["answer"], sc.resolve(cond))
            msgs[cond] = C.messages(a.model, p)
            ids = eg.encode_chat(tok, msgs[cond], disable_thinking=m["disable_thinking"])["input_ids"].to(model.device)
            enc[cond] = ids
            fin[cond] = [ids.shape[1] - 1]
            c = PT.capture_states(model, ids, {"final_input": fin[cond]}, n_layers)
            cap[cond] = {L: c["final_input"][L] for L in (m["site_layer"], M.CONTROL_LAYER)}
            del c
        for u in tu:
            if u["unit_id"] in final:
                continue
            tgt = u["target"]
            while u["unit_id"] not in final:
                err, gen = None, None
                try:
                    if u["kind"] == "baseline":
                        ctx = None
                    elif u["kind"] == "patch":
                        ctx = PT.patch_positions(model, u["layer"], fin[tgt], cap[u["source"]][u["layer"]])
                    elif u["kind"] == "noop":
                        ctx = PT.no_patch(model, u["layer"])
                    else:
                        ctx = PT.patch_positions(model, u["layer"], fin[tgt], cap[tgt][u["layer"]])
                    if ctx is None:
                        gen = eg.generate_exact(be.loaded, msgs[tgt], max_new_tokens=512, seed=42)
                    else:
                        with ctx:
                            gen = eg.generate_exact(be.loaded, msgs[tgt], max_new_tokens=512, seed=42)
                except Exception as e:  # technical failure, recorded
                    err = f"{type(e).__name__}: {e}"
                payload = RN.payload_from_generation(gen, err, 512)
                payload.update(key=M.unit_key(u), base_task_id=b, final_input_index=fin[tgt][0],
                               prompt_len=int(enc[tgt].shape[1]),
                               text=None if gen is None else gen["text"])
                tech = err is not None or gen is None or not (gen.get("text") or "").strip()
                if tech:
                    status = "permanent_failure" if n_att.get(u["unit_id"], 0) + 1 >= MAX_ATTEMPTS else "technical_failure"
                else:
                    status = "accepted"
                record(u, status, payload)
        print(f"[{a.model}/{a.mode}] task {ti}/{len(by_task)} {b} done "
              f"{time.strftime('%H:%M:%S', time.gmtime())}", flush=True)
    store.close()
    print("COMPLETE", a.model, a.mode, flush=True)


if __name__ == "__main__":
    main()
