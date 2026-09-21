"""Jacobian-Lens signed token-level deltas on the frozen 72-task extension.

INSTRUMENT. The official jacobian-lens implementation, used as the earlier discovery used it:
    h -> lens.transport(h, jlens_layer) -> model.unembed(...)
This is NOT an ordinary logit lens. A logit lens would unembed the raw residual with no
Jacobian transport; every layer here goes through lens.transport, and any layer the lens was
not fitted on is skipped rather than silently unembedded.
LAYER INDEXING: jlens layer i == our L(i+1). Everything is reported in OUR indexing.

QUANTITY. Per token, the signed difference of lens log-probabilities at final_input:
    delta(A,B) = log P_A(token) - log P_B(token)
Positive => the token is MORE PROMOTED under condition A. Log-probabilities are used rather
than raw logits so the measure is invariant to per-condition logit shifts.

COMPARISONS (direction is in the name and in every output column):
    self_low_2_minus_no_history
    self_low_2_minus_unrelated_low_2
    self_high_10_minus_self_low_2

L24 and the window [23,24,25] are inherited frozen from the earlier Jacobian-Lens discovery.
Nothing here selects a layer.

Retains the complete vocabulary-level signed delta for every task and every lens-covered
layer, fp16, one .npy per comparison.
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
from silent_influence import activations as act
from silent_influence import exact_generation as eg
from silent_influence import final_study_messages as fsm
from silent_influence import scaled_conditions as sc

COMPARISONS = [("self_low_2", "no_history"),
               ("self_low_2", "unrelated_low_2"),
               ("self_high_10", "self_low_2")]
CONDITIONS = sorted({c for pair in COMPARISONS for c in pair})

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True)
ap.add_argument("--candidates", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--lens-repo", default="neuronpedia/jacobian-lens")
ap.add_argument("--lens-file",
                default="llama3.1-8b-it/jlens/Salesforce-wikitext/"
                        "Llama-3.1-8B-Instruct_jacobian_lens.pt")
ap.add_argument("--lens-revision", default="a4114d7752d11eb546e6cf372213d7e75526d3a1")
A = ap.parse_args()

OUT = pathlib.Path(A.out_dir); OUT.mkdir(parents=True, exist_ok=True)
man = json.loads(pathlib.Path(A.manifest).read_text(encoding="utf-8"))
tasks = man["tasks"]

import run_final_scoring as RFS

spec = next(s for s in RFS.SCORERS if s.key == "llama")
cands = {(c["dataset"], c["source_task_id"]): c for c in RFS.load_candidates(A.candidates)}
conds = {c.name: c for c in sc.CONDITIONS}

t0 = time.time()
torch.cuda.reset_peak_memory_stats()
loaded = eg.load_exact_model(spec, hf_token=None)
model, tok = loaded.model, loaded.tokenizer
n_layers = model.config.num_hidden_layers

import jlens

jm = jlens.from_hf(model, tok, force_bos=False)
lens = jlens.JacobianLens.from_pretrained(A.lens_repo, filename=A.lens_file,
                                          revision=A.lens_revision)
FITTED = set(lens.source_layers)
COVERED = sorted(i + 1 for i in FITTED if 1 <= i + 1 <= n_layers)   # our indexing
VOCAB = model.config.vocab_size
print(f"lens fitted jlens {min(FITTED)}..{max(FITTED)} -> our L{COVERED[0]}..{COVERED[-1]} "
      f"({len(COVERED)} layers) | vocab {VOCAB} | {len(tasks)} tasks", flush=True)
print(f"instrument: lens.transport + unembed (Jacobian lens, NOT a logit lens)", flush=True)


def render(cand, cname):
    prompt = sc.render_prompt(cand["question"], cand["answer"], conds[cname])
    msgs = fsm.build_scorer_messages("llama", prompt)
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    enc = tok(text, return_tensors="pt", return_offsets_mapping=True,
              add_special_tokens=False)
    offs = enc.pop("offset_mapping")[0].tolist()
    sp = act.locate_positions(text, offs, None, None)
    return enc["input_ids"].to(model.device), sp["final_input"].token_indices


store = {f"{a}_minus_{b}": np.zeros((len(tasks), len(COVERED), VOCAB), dtype=np.float16)
         for a, b in COMPARISONS}

for ti, t in enumerate(tasks):
    cand = cands[(t["dataset"], t["task_id"])]
    logp = {c: {} for c in CONDITIONS}
    for c in CONDITIONS:
        ids, pos = render(cand, c)
        with torch.no_grad():
            o = model(input_ids=ids, output_hidden_states=True, use_cache=False)
        for li, L in enumerate(COVERED):
            h = o.hidden_states[L][0, pos, :].float()          # [1, hidden]
            h = lens.transport(h, L - 1)                        # Jacobian step
            lg = jm.unembed(h).float().reshape(-1)
            logp[c][li] = torch.log_softmax(lg, -1)
        del o
    for a, b in COMPARISONS:
        key = f"{a}_minus_{b}"
        for li in range(len(COVERED)):
            d = (logp[a][li] - logp[b][li]).to(torch.float16).cpu().numpy()
            store[key][ti, li, :] = d
    del logp
    if (ti + 1) % 5 == 0 or ti == 0:
        el = time.time() - t0
        print(f"  [{ti+1}/{len(tasks)}] {t['dataset']}/{t['task_id']}  {el/60:.1f}m  "
              f"ETA {(el/(ti+1))*(len(tasks)-ti-1)/60:.1f}m", flush=True)

for key, arr in store.items():
    np.save(OUT / f"delta_{key}.npy", arr)
    print(f"  [save] delta_{key}.npy  {arr.nbytes/1e6:.0f} MB  shape {arr.shape}", flush=True)

meta = {
    "stage": "JACOBIAN-LENS SIGNED TOKEN DELTAS -- 72-task extension",
    "instrument": "official jacobian-lens: lens.transport(h, i) then model.unembed",
    "is_logit_lens": False,
    "quantity": "log P_A(token) - log P_B(token) at final_input",
    "sign_convention": "positive for A_minus_B => token MORE PROMOTED under condition A",
    "comparisons": [f"{a}_minus_{b}" for a, b in COMPARISONS],
    "position": "final_input",
    "our_layers_covered": COVERED, "jlens_layers_fitted": sorted(FITTED),
    "unfitted_layers_skipped_not_logit_lensed": True,
    "locked_layer": 24, "locked_window": [23, 24, 25],
    "layer_not_selected_here": True,
    "vocab_size": VOCAB, "n_tasks": len(tasks),
    "tasks": [{"dataset": t["dataset"], "task_id": t["task_id"]} for t in tasks],
    "array_axes": "[task, layer_index_into_our_layers_covered, vocab]",
    "dtype": "float16",
    "runtime_s": round(time.time() - t0, 1),
    "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
}
(OUT / "jlens_tokens_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in meta.items() if k != "tasks"}, indent=2), flush=True)
