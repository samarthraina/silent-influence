"""72-task mechanistic generalization replication.

Everything causal is REUSED, not refitted: the L24 direction tensor, beta=1.5, alpha=1.0 and
the fixed-seed norm-matched random direction all come from the frozen control-study artifacts
and are asserted against DIRECTION_FREEZE.json at startup. No coefficient search, no layer
search, no window search, no task replacement.

Arms per task (17), all at L24 unless stated:
  baseline_{self_low_2,no_history,unrelated_low_2}   unpatched
  steer / ablate                                     learned intervention on self_low_2
  steer_early_L2                                     early-layer control
  steer_random                                       norm-matched random direction
  steer_on_no_history / steer_on_unrelated           specificity
  patch_L24_lo2hi / patch_L24_hi2lo                  locked bidirectional patching
  patch_L2_lo2hi  / patch_L2_hi2lo                   early-layer patching control
  noop_{self_low_2,no_history}                       identity
  same_{self_low_2,no_history}                       same-condition identity
"""
import argparse
import json
import pathlib
import sys
import time

import torch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mech_adapter as MA
from silent_influence import activations as act
from silent_influence import exact_generation as eg
from silent_influence import final_study_messages as fsm
from silent_influence import patching
from silent_influence import scaled_conditions as sc

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True)
ap.add_argument("--candidates", required=True)
ap.add_argument("--freeze", required=True)
ap.add_argument("--direction", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--early-layer", type=int, default=2)
A = ap.parse_args()

OUT = pathlib.Path(A.out_dir); OUT.mkdir(parents=True, exist_ok=True)
man = json.loads(pathlib.Path(A.manifest).read_text(encoding="utf-8"))
fz = json.loads(pathlib.Path(A.freeze).read_text(encoding="utf-8"))
blob = torch.load(A.direction, map_location="cpu")

LAYER, BETA, ALPHA = fz["layer"], fz["beta_selected"], fz["ablation_alpha"]
RSEED = fz["random_direction_seed"]
reuse = man["reused_without_retuning"]
assert (LAYER, BETA, ALPHA, RSEED) == (reuse["layer"], reuse["beta"], reuse["alpha"],
                                       reuse["random_direction_seed"]), "reuse drift"
assert blob["layer"] == LAYER
tasks = man["tasks"]
LO, HI, UN = "self_low_2", "no_history", "unrelated_low_2"

import run_final_scoring as RFS

spec = next(s for s in RFS.SCORERS if s.key == "llama")
cands = {(c["dataset"], c["source_task_id"]): c for c in RFS.load_candidates(A.candidates)}
conds = {c.name: c for c in sc.CONDITIONS}

t0 = time.time()
torch.cuda.reset_peak_memory_stats()
loaded = eg.load_exact_model(spec, hf_token=None)
model, tok = loaded.model, loaded.tokenizer
dev = model.device
D = blob["direction"].to(dev).float()
g = torch.Generator(device="cpu").manual_seed(RSEED)
R = torch.randn(D.shape, generator=g).to(dev).float()
R = R / R.norm() * D.norm()
print(f"L{LAYER} beta={BETA} alpha={ALPHA} reused | |d|={D.norm():.3f} |r|={R.norm():.3f} "
      f"| {len(tasks)} tasks x 17 arms = {len(tasks)*17} calls", flush=True)


def render(cand, c):
    prompt = sc.render_prompt(cand["question"], cand["answer"], conds[c])
    msgs = fsm.build_scorer_messages("llama", prompt)
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    enc = tok(text, return_tensors="pt", return_offsets_mapping=True,
              add_special_tokens=False)
    offs = enc.pop("offset_mapping")[0].tolist()
    sp = act.locate_positions(text, offs, None, None)
    return enc["input_ids"].to(dev), sp["final_input"].token_indices


def gen(ids):
    with torch.no_grad():
        o = model.generate(input_ids=ids, max_new_tokens=spec.max_new_tokens,
                           do_sample=False, pad_token_id=tok.pad_token_id, use_cache=True)
    seq = o[0, ids.shape[1]:]
    return (tok.decode(seq, skip_special_tokens=True), int(seq.shape[0]),
            bool((seq == tok.eos_token_id).any().item()))


def a5(n_out, em):
    return not (n_out >= spec.max_new_tokens and not em)


rec_path = OUT / "ext72_records.jsonl"
done = set()
if rec_path.exists():
    for l in rec_path.open(encoding="utf-8"):
        if l.strip():
            done.add(json.loads(l)["unit"])
fh = rec_path.open("a", encoding="utf-8")
n = 0

for ti, t in enumerate(tasks, 1):
    cand = cands[(t["dataset"], t["task_id"])]
    ids, pos = {}, {}
    for c in (LO, HI, UN):
        ids[c], pos[c] = render(cand, c)
    caps = {}
    for c in (LO, HI):
        with torch.no_grad():
            o = model(input_ids=ids[c], output_hidden_states=True, use_cache=False)
        caps[c] = {L: o.hidden_states[L][0, pos[c], :].detach().clone()
                   for L in (LAYER, A.early_layer)}
        del o

    base = {}
    for c in (LO, HI, UN):
        key = f"baseline|{t['dataset']}/{t['task_id']}|{c}"
        txt, no_, em = gen(ids[c])
        s, st = MA.score_of(txt)
        base[c] = s
        if key not in done:
            fh.write(json.dumps({"unit": key, "arm": f"baseline_{c}", "kind": "baseline",
                                 "dataset": t["dataset"], "task_id": t["task_id"],
                                 "condition": c, "layer": None, "score": s,
                                 "parse_status": st, "a5_valid": a5(no_, em),
                                 "output_tokens": no_}) + "\n"); fh.flush(); n += 1

    def run(arm, cond, ctx, layer, extra=None):
        global n
        key = f"{arm}|{t['dataset']}/{t['task_id']}"
        if key in done:
            return
        with ctx:
            txt, no_, em = gen(ids[cond])
        s, st = MA.score_of(txt)
        rec = {"unit": key, "arm": arm, "kind": arm, "dataset": t["dataset"],
               "task_id": t["task_id"], "condition": cond, "layer": layer, "score": s,
               "parse_status": st, "a5_valid": a5(no_, em), "output_tokens": no_,
               "target_baseline": base[cond],
               "self_low_2_endpoint": base[LO], "no_history_endpoint": base[HI],
               "unrelated_endpoint": base[UN]}
        if extra:
            rec.update(extra)
        fh.write(json.dumps(rec) + "\n"); fh.flush(); n += 1

    P, PH, PU = pos[LO], pos[HI], pos[UN]
    # steering / ablation block -- learned intervention, reused unchanged
    run("steer", LO, patching.add_positionwise(model, LAYER, P, D.unsqueeze(0), beta=BETA), LAYER)
    run("ablate", LO, patching.ablate_direction(model, LAYER, P, D, alpha=ALPHA), LAYER)
    run("steer_early_L2", LO,
        patching.add_positionwise(model, A.early_layer, P, D.unsqueeze(0), beta=BETA),
        A.early_layer)
    run("steer_random", LO,
        patching.add_positionwise(model, LAYER, P, R.unsqueeze(0), beta=BETA), LAYER)
    run("steer_on_no_history", HI,
        patching.add_positionwise(model, LAYER, PH, D.unsqueeze(0), beta=BETA), LAYER)
    run("steer_on_unrelated", UN,
        patching.add_positionwise(model, LAYER, PU, D.unsqueeze(0), beta=BETA), LAYER)
    # locked bidirectional causal patching, L24 and the L2 early control
    for L in (LAYER, A.early_layer):
        tag = "L24" if L == LAYER else f"L{L}"
        run(f"patch_{tag}_lo2hi", HI, patching.patch_positions(model, L, PH, caps[LO][L]), L,
            {"direction": "self_low_2->no_history", "source_baseline": base[LO]})
        run(f"patch_{tag}_hi2lo", LO, patching.patch_positions(model, L, P, caps[HI][L]), L,
            {"direction": "no_history->self_low_2", "source_baseline": base[HI]})
    # identity controls
    for c, pc in ((LO, P), (HI, PH)):
        run(f"noop_{c}", c, patching.no_patch(model, LAYER), LAYER)
        run(f"same_{c}", c, patching.patch_positions(model, LAYER, pc, caps[c][LAYER]), LAYER)

    el = time.time() - t0
    print(f"  [{ti}/{len(tasks)}] {t['dataset']}/{t['task_id']}  {n} calls  {el/60:.1f}m  "
          f"ETA {(el/ti)*(len(tasks)-ti)/60:.1f}m", flush=True)

fh.close()
meta = {"stage": "72-TASK GENERALIZATION REPLICATION",
        "specified_after_observing_24_task_control_result": True,
        "preregistered_before_that_result": False,
        "layer": LAYER, "beta": BETA, "alpha": ALPHA, "early_layer": A.early_layer,
        "random_seed": RSEED, "n_tasks": len(tasks), "n_calls": n,
        "reused_without_retuning": True, "manifest_sha256_frozen_before_run": True,
        "runtime_s": round(time.time() - t0, 1),
        "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
(OUT / "ext72_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
print(json.dumps(meta, indent=2), flush=True)
