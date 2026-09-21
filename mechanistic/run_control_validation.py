"""STAGE 3b -- HELD-OUT CONTROL VALIDATION. 24 validation tasks.

Reads DIRECTION_FREEZE.json and steering_direction.pt, both written by stage 3a before this
file ever ran. Nothing here refits the direction, re-searches a layer or re-picks beta.

Arms per task (all at the frozen L24 unless stated):
  baseline_<cond>        self_low_2, no_history, unrelated_low_2, unpatched
  steer                  self_low_2 + beta*d          learned intervention
  ablate                 self_low_2 with d removed    alpha = 1
  noop                   hooks fire, write nothing    identity control
  steer_early_L2         same steering at L2          early-layer control
  steer_random           norm-matched random d        fixed-seed direction control
  steer_on_no_history    learned intervention applied to no_history       specificity
  steer_on_unrelated     learned intervention applied to unrelated_low_2  specificity

Every generation runs the frozen behavioural path: frozen prompts, greedy decoding, frozen
token ceiling, frozen parser, frozen A5 rule.
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
tasks = man["validation"]
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
assert blob["layer"] == LAYER

# norm-matched random control: same L2 norm as the learned direction, fixed seed
g = torch.Generator(device="cpu").manual_seed(RSEED)
R = torch.randn(D.shape, generator=g).to(dev).float()
R = R / R.norm() * D.norm()
print(f"L{LAYER} beta={BETA} alpha={ALPHA} | learned |d|={D.norm():.3f} "
      f"random |r|={R.norm():.3f} | {len(tasks)} held-out tasks", flush=True)


def render(cand, cond_name):
    prompt = sc.render_prompt(cand["question"], cand["answer"], conds[cond_name])
    messages = fsm.build_scorer_messages("llama", prompt)
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    enc = tok(text, return_tensors="pt", return_offsets_mapping=True,
              add_special_tokens=False)
    offs = enc.pop("offset_mapping")[0].tolist()
    sp = act.locate_positions(text, offs, None, None)
    return enc["input_ids"].to(dev), sp["final_input"].token_indices


def gen(ids):
    with torch.no_grad():
        out = model.generate(input_ids=ids, max_new_tokens=spec.max_new_tokens,
                             do_sample=False, pad_token_id=tok.pad_token_id, use_cache=True)
    seq = out[0, ids.shape[1]:]
    return (tok.decode(seq, skip_special_tokens=True), int(seq.shape[0]),
            bool((seq == tok.eos_token_id).any().item()))


def a5(n_out, em):
    return not (n_out >= spec.max_new_tokens and not em)


rec_path = OUT / "control_records.jsonl"
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

    base = {}
    for c in (LO, HI, UN):
        key = f"baseline|{t['dataset']}/{t['task_id']}|{c}"
        txt, no_, em = gen(ids[c])
        s, st = MA.score_of(txt)
        base[c] = s
        if key not in done:
            fh.write(json.dumps({"unit": key, "kind": "baseline", "arm": f"baseline_{c}",
                                 "dataset": t["dataset"], "task_id": t["task_id"],
                                 "condition": c, "layer": None, "score": s,
                                 "parse_status": st, "a5_valid": a5(no_, em),
                                 "output_tokens": no_}) + "\n"); fh.flush(); n += 1

    def run(arm, cond, ctx, layer):
        global n
        key = f"{arm}|{t['dataset']}/{t['task_id']}"
        if key in done:
            return
        with ctx:
            txt, no_, em = gen(ids[cond])
        s, st = MA.score_of(txt)
        fh.write(json.dumps({
            "unit": key, "kind": arm, "arm": arm, "dataset": t["dataset"],
            "task_id": t["task_id"], "condition": cond, "layer": layer, "score": s,
            "parse_status": st, "a5_valid": a5(no_, em), "output_tokens": no_,
            "target_baseline": base[cond],
            "no_history_endpoint": base[HI], "self_low_2_endpoint": base[LO],
            "frozen_no_history": t[HI], "frozen_self_low_2": t[LO],
        }) + "\n"); fh.flush(); n += 1

    P = pos[LO]
    run("steer", LO, patching.add_positionwise(model, LAYER, P, D.unsqueeze(0), beta=BETA), LAYER)
    run("ablate", LO, patching.ablate_direction(model, LAYER, P, D, alpha=ALPHA), LAYER)
    run("noop", LO, patching.no_patch(model, LAYER), LAYER)
    run("steer_early_L2", LO,
        patching.add_positionwise(model, A.early_layer, P, D.unsqueeze(0), beta=BETA),
        A.early_layer)
    run("steer_random", LO,
        patching.add_positionwise(model, LAYER, P, R.unsqueeze(0), beta=BETA), LAYER)
    run("steer_on_no_history", HI,
        patching.add_positionwise(model, LAYER, pos[HI], D.unsqueeze(0), beta=BETA), LAYER)
    run("steer_on_unrelated", UN,
        patching.add_positionwise(model, LAYER, pos[UN], D.unsqueeze(0), beta=BETA), LAYER)

    el = time.time() - t0
    print(f"  [{ti}/{len(tasks)}] {t['dataset']}/{t['task_id']}  {n} calls  {el/60:.1f}m  "
          f"ETA {(el/ti)*(len(tasks)-ti)/60:.1f}m", flush=True)

fh.close()
meta = {"stage": "HELD-OUT CONTROL VALIDATION", "layer": LAYER, "beta": BETA,
        "alpha": ALPHA, "early_layer": A.early_layer, "random_seed": RSEED,
        "n_tasks": len(tasks), "n_calls": n, "position": "final_input",
        "direction_and_coefficient_frozen_before_validation": True,
        "runtime_s": round(time.time() - t0, 1),
        "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
(OUT / "control_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
print(json.dumps(meta, indent=2), flush=True)
