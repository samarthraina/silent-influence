"""STAGE 3a -- DISCOVERY ONLY. Fit the steering direction and pick its coefficient.

Uses the 12 discovery tasks and nothing else. The 24 validation tasks are not loaded, not
rendered and not generated from anywhere in this file. The grid below is declared in source
before any validation run exists, and the chosen value is written to a freeze record that
stage 3b reads and cannot change.

Direction: d = mean over discovery tasks of ( h[no_history] - h[self_low_2] ) at L24,
final_input. Used raw for steering (add_positionwise keeps the observed magnitude) and unit
-normalized for ablation (ablate_direction normalizes internally).

Layer L24 and the window [23,24,25] are inherited from the completed Jacobian-Lens
discovery. No layer is searched for here.
"""
import argparse
import json
import pathlib
import sys
import time

import numpy as np
import torch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mech_adapter as MA
from silent_influence import activations as act
from silent_influence import exact_generation as eg
from silent_influence import final_study_messages as fsm
from silent_influence import patching
from silent_influence import scaled_conditions as sc

# ---- DECLARED BEFORE ANY VALIDATION RUN ----------------------------------------------
BETA_GRID = [0.5, 1.0, 1.5, 2.0]     # steering coefficients considered
ABLATION_ALPHA = 1.0                 # full removal; not gridded
RANDOM_DIRECTION_SEED = 20260818     # norm-matched control, fixed here
SUCCESS_CRITERIA = {
    "primary": "steering self_low_2 toward no_history at L24 produces mean normalized "
               "movement > 0 with a task-bootstrap 95% CI excluding 0",
    "control_1": "learned-direction normalized movement exceeds the early-layer L2 arm",
    "control_2": "learned-direction normalized movement exceeds the norm-matched "
                 "random-direction arm",
    "specificity": "shifts induced under no_history and unrelated_low_2 are reported; if "
                   "they match the self_low_2 shift the intervention is nonspecific and "
                   "the primary result does not support a score-specific mechanism",
    "declared_before_validation": True,
}

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True)
ap.add_argument("--candidates", required=True)
ap.add_argument("--window-file", required=True)
ap.add_argument("--out-dir", required=True)
A = ap.parse_args()

OUT = pathlib.Path(A.out_dir); OUT.mkdir(parents=True, exist_ok=True)
man = json.loads(pathlib.Path(A.manifest).read_text(encoding="utf-8"))
win = json.loads(pathlib.Path(A.window_file).read_text(encoding="utf-8"))
LAYER = win["selected_layer"]
tasks = man["discovery"]
LO, HI = "self_low_2", "no_history"

import run_final_scoring as RFS

spec = next(s for s in RFS.SCORERS if s.key == "llama")
cands = {(c["dataset"], c["source_task_id"]): c for c in RFS.load_candidates(A.candidates)}
conds = {c.name: c for c in sc.CONDITIONS}

t0 = time.time()
torch.cuda.reset_peak_memory_stats()
loaded = eg.load_exact_model(spec, hf_token=None)
model, tok = loaded.model, loaded.tokenizer
print(f"L{LAYER} | {len(tasks)} discovery tasks | grid {BETA_GRID}", flush=True)


def render(cand, cond_name):
    prompt = sc.render_prompt(cand["question"], cand["answer"], conds[cond_name])
    messages = fsm.build_scorer_messages("llama", prompt)
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    enc = tok(text, return_tensors="pt", return_offsets_mapping=True,
              add_special_tokens=False)
    offs = enc.pop("offset_mapping")[0].tolist()
    # final_input only -- history anchoring is unnecessary and would not resolve for every
    # condition, so it is deliberately not requested.
    sp = act.locate_positions(text, offs, None, None)
    return enc["input_ids"].to(model.device), sp["final_input"].token_indices


def gen(ids):
    with torch.no_grad():
        out = model.generate(input_ids=ids, max_new_tokens=spec.max_new_tokens,
                             do_sample=False, pad_token_id=tok.pad_token_id, use_cache=True)
    seq = out[0, ids.shape[1]:]
    emitted = bool((seq == tok.eos_token_id).any().item())
    return tok.decode(seq, skip_special_tokens=True), int(seq.shape[0]), emitted


# ---- fit the direction on discovery tasks --------------------------------------------
prep, deltas = {}, []
for t in tasks:
    cand = cands[(t["dataset"], t["task_id"])]
    h = {}
    for c in (LO, HI):
        ids, pos = render(cand, c)
        with torch.no_grad():
            o = model(input_ids=ids, output_hidden_states=True, use_cache=False)
        h[c] = o.hidden_states[LAYER][0, pos, :].detach().float()
        prep[(t["task_id"], c)] = (ids, pos)
        del o
    deltas.append((h[HI] - h[LO]).squeeze(0))

D = torch.stack(deltas).mean(0)
d_unit = D / D.norm()
cos = torch.stack([torch.nn.functional.cosine_similarity(x, D, dim=0) for x in deltas])
print(f"direction: norm {D.norm():.3f} | per-task cosine to mean "
      f"{cos.mean():.3f} +- {cos.std():.3f} (min {cos.min():.3f})", flush=True)

# ---- coefficient selection, discovery tasks only --------------------------------------
grid_rows = []
for beta in BETA_GRID:
    norm_mv, raw_mv = [], []
    for t in tasks:
        ids, pos = prep[(t["task_id"], LO)]
        tb, sb = float(t[LO]), float(t[HI])
        with patching.add_positionwise(model, LAYER, pos, D.unsqueeze(0), beta=beta):
            txt, n_out, em = gen(ids)
        s, st = MA.score_of(txt)
        if s is None or sb == tb:
            continue
        raw_mv.append(s - tb)
        norm_mv.append((s - tb) / (sb - tb))
    grid_rows.append({"beta": beta, "n": len(norm_mv),
                      "normalized_mean": float(np.mean(norm_mv)) if norm_mv else None,
                      "raw_mean": float(np.mean(raw_mv)) if raw_mv else None})
    print(f"  beta {beta}: normalized {grid_rows[-1]['normalized_mean']:+.4f} "
          f"raw {grid_rows[-1]['raw_mean']:+.4f} (n={len(norm_mv)})  "
          f"{time.time()-t0:.0f}s", flush=True)

usable = [g for g in grid_rows if g["normalized_mean"] is not None]
best = max(usable, key=lambda g: (g["normalized_mean"], -g["beta"]))
BETA = best["beta"]

torch.save({"direction": D.cpu(), "unit": d_unit.cpu(), "layer": LAYER},
           OUT / "steering_direction.pt")
freeze = {
    "stage": "DISCOVERY -- direction and coefficient frozen before validation",
    "layer": LAYER, "window_descriptive": win["window"], "position": "final_input",
    "direction_source": "mean over the 12 discovery tasks of h[no_history] - h[self_low_2]",
    "direction_norm": float(D.norm()),
    "per_task_cosine_to_mean": {"mean": float(cos.mean()), "sd": float(cos.std()),
                                "min": float(cos.min())},
    "beta_grid_declared": BETA_GRID, "beta_selected": BETA,
    "beta_grid_results_discovery_only": grid_rows,
    "ablation_alpha": ABLATION_ALPHA,
    "random_direction_seed": RANDOM_DIRECTION_SEED,
    "success_criteria": SUCCESS_CRITERIA,
    "validation_tasks_untouched_here": True,
    "layer_not_searched": True,
    "runtime_s": round(time.time() - t0, 1),
    "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
}
(OUT / "DIRECTION_FREEZE.json").write_text(json.dumps(freeze, indent=2), encoding="utf-8")
print(f"\n  SELECTED beta={BETA}  alpha={ABLATION_ALPHA}  "
      f"({freeze['runtime_s']}s, peak {freeze['peak_gpu_gib']} GiB)", flush=True)
