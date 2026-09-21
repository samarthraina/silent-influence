"""STAGE 1 -- DISCOVERY. Jacobian-Lens readout across all layers, 12 discovery tasks.

Discovery only. Nothing here is a causal claim; it selects one layer window for stage 2 and
is then closed. Validation outcomes never feed back into this choice.

Instrument: the official jacobian-lens implementation, unmodified, with the Neuronpedia
pre-fitted lens (WikiText-only; no task, prompt, condition or result of ours touched it).
LAYER INDEXING: jlens records the output of block i as layer i, so jlens i == our L(i+1).
Everything below is reported in OUR indexing.

Position: final_input only -- the sole position semantically shared by no_history and
self_low_2, per the compatibility smoke.

Separation reported per layer:
  jsd_bits      Jensen-Shannon divergence between the two conditions' lens distributions
  score_mass_d  |P(score numerals) difference| -- the score-relevant restriction
Layer selection is over OUR L4..L27 only; the final four layers are excluded by construction
so a win cannot be trivial next-token forcing.
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

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True)
ap.add_argument("--candidates", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--lens-repo", default="neuronpedia/jacobian-lens")
ap.add_argument("--lens-file",
                default="llama3.1-8b-it/jlens/Salesforce-wikitext/"
                        "Llama-3.1-8B-Instruct_jacobian_lens.pt")
ap.add_argument("--lens-revision", default="a4114d7752d11eb546e6cf372213d7e75526d3a1")
ap.add_argument("--layer-lo", type=int, default=4)
ap.add_argument("--layer-hi", type=int, default=27)
A = ap.parse_args()

OUT = pathlib.Path(A.out_dir); OUT.mkdir(parents=True, exist_ok=True)
man = json.loads(pathlib.Path(A.manifest).read_text(encoding="utf-8"))
tasks = man["discovery"]
LO, HI = "self_low_2", "no_history"

import run_final_scoring as RFS

spec = next(s for s in RFS.SCORERS if s.key == "llama")
cands = {(c["dataset"], c["source_task_id"]): c
         for c in RFS.load_candidates(A.candidates)}
conds = {c.name: c for c in sc.CONDITIONS}

t_start = time.time()
torch.cuda.reset_peak_memory_stats()
loaded = eg.load_exact_model(spec, hf_token=None)
model, tok = loaded.model, loaded.tokenizer
n_layers = model.config.num_hidden_layers

import jlens

jm = jlens.from_hf(model, tok, force_bos=False)
lens = jlens.JacobianLens.from_pretrained(A.lens_repo, filename=A.lens_file,
                                          revision=A.lens_revision)
print(f"model {spec.hf_id}@{spec.revision[:8]} n_layers={n_layers}", flush=True)
print(f"lens  {lens}", flush=True)

# score numerals, as leading-token variants the model would actually emit
score_tok = set()
for n in list(range(0, 11)):
    for form in (f"{n}", f" {n}"):
        ids = tok.encode(form, add_special_tokens=False)
        if len(ids) == 1:
            score_tok.add(ids[0])
score_ids = torch.tensor(sorted(score_tok), device=model.device)
print(f"score numeral tokens: {len(score_tok)}", flush=True)


def render(cand, cond_name):
    prompt = sc.render_prompt(cand["question"], cand["answer"], conds[cond_name])
    messages = fsm.build_scorer_messages("llama", prompt)
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    enc = tok(text, return_tensors="pt", return_offsets_mapping=True,
              add_special_tokens=False)
    offs = enc.pop("offset_mapping")[0].tolist()
    return text, enc["input_ids"].to(model.device), offs


hist_prefix = conds[LO].added_context.split("2/10")[0]


def jsd_bits(p_logits, q_logits):
    p = torch.softmax(p_logits.float(), -1)
    q = torch.softmax(q_logits.float(), -1)
    m = 0.5 * (p + q)
    lm = m.clamp_min(1e-12).log()
    kl_p = (p * (p.clamp_min(1e-12).log() - lm)).sum(-1)
    kl_q = (q * (q.clamp_min(1e-12).log() - lm)).sum(-1)
    return float((0.5 * (kl_p + kl_q) / np.log(2.0)).item())


# Only the lens's own fitted layers get a Jacobian readout. Unembedding an unfitted layer
# would be a logit lens wearing the same name, so those layers are simply not covered and
# are excluded from selection rather than silently mixed in.
# jlens layer i == our L(i+1); the residual for our L is hidden_states[L].
FITTED_JLENS = set(lens.source_layers)
COVERED_OURS = sorted(i + 1 for i in FITTED_JLENS if 1 <= i + 1 <= n_layers)
print(f"lens fitted jlens layers {min(FITTED_JLENS)}..{max(FITTED_JLENS)} "
      f"({len(FITTED_JLENS)}) -> our L {COVERED_OURS[0]}..{COVERED_OURS[-1]} "
      f"({len(COVERED_OURS)} covered)", flush=True)

rows = []
for i, t in enumerate(tasks, 1):
    cand = cands[(t["dataset"], t["task_id"])]
    per_cond = {}
    for c in (LO, HI):
        text, ids, offs = render(cand, c)
        sv = 2 if c == LO else None
        sp = act.locate_positions(text, offs, None if sv is None else hist_prefix, sv)
        pos = sp["final_input"].token_indices
        with torch.no_grad():
            out = model(input_ids=ids, output_hidden_states=True, use_cache=False)
        hs = out.hidden_states
        per_cond[c] = {L: hs[L][0, pos[0], :].detach().float().unsqueeze(0)
                       for L in COVERED_OURS}
        del out
    for L in COVERED_OURS:
        j = L - 1                                   # jlens index for our layer L
        logit = {}
        for c in (LO, HI):
            h = per_cond[c][L]
            h = lens.transport(h, j)                # J_l @ h -- the Jacobian step
            logit[c] = jm.unembed(h).float().reshape(-1)
        pm_lo = float(torch.softmax(logit[LO], -1)[score_ids].sum().item())
        pm_hi = float(torch.softmax(logit[HI], -1)[score_ids].sum().item())
        rows.append({"dataset": t["dataset"], "task_id": t["task_id"], "layer": L,
                     "jlens_layer": j,
                     "jsd_bits": jsd_bits(logit[LO], logit[HI]),
                     "score_mass_self_low_2": pm_lo, "score_mass_no_history": pm_hi,
                     "score_mass_diff": abs(pm_hi - pm_lo)})
    print(f"  [{i}/{len(tasks)}] {t['dataset']}/{t['task_id']} done "
          f"({time.time()-t_start:.0f}s)", flush=True)

with open(OUT / "readout_per_task_layer.jsonl", "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r) + "\n")

by_layer = {}
for L in COVERED_OURS:
    sub = [r for r in rows if r["layer"] == L]
    by_layer[L] = {
        "layer": L, "n_tasks": len(sub),
        "jsd_bits_mean": float(np.mean([r["jsd_bits"] for r in sub])),
        "jsd_bits_sd": float(np.std([r["jsd_bits"] for r in sub], ddof=1)),
        "score_mass_diff_mean": float(np.mean([r["score_mass_diff"] for r in sub])),
    }

elig = [L for L in by_layer if A.layer_lo <= L <= A.layer_hi]
if not elig:
    raise SystemExit(f"no lens-covered layer in [{A.layer_lo},{A.layer_hi}]")
best = max(elig, key=lambda L: by_layer[L]["jsd_bits_mean"])
window = [L for L in (best - 1, best, best + 1) if 1 <= L <= n_layers]
assert all(L <= n_layers - 4 for L in window), "window entered the final four layers"

sel = {
    "stage": "DISCOVERY -- not a causal claim",
    "position": "final_input",
    "selection_metric": "jsd_bits_mean across the 12 discovery tasks",
    "eligible_layers": [A.layer_lo, A.layer_hi],
    "final_four_layers_excluded": list(range(n_layers - 3, n_layers + 1)),
    "lens_covered_layers_ours": COVERED_OURS,
    "lens_fitted_jlens_layers": sorted(FITTED_JLENS),
    "unfitted_layers_excluded_not_logit_lensed": True,
    "selected_layer": best, "window": window,
    "selected_before_any_validation_run": True,
    "by_layer": [by_layer[L] for L in sorted(by_layer)],
    "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
    "runtime_s": round(time.time() - t_start, 1),
}
(OUT / "readout_layer_summary.json").write_text(json.dumps(sel, indent=2), encoding="utf-8")
(OUT / "SELECTED_WINDOW.json").write_text(
    json.dumps({"selected_layer": best, "window": window, "n_layers": n_layers}, indent=2),
    encoding="utf-8")

top = sorted(by_layer.values(), key=lambda d: -d["jsd_bits_mean"])[:8]
print("\n  top layers by mean JSD (our indexing):", flush=True)
for d in top:
    print(f"    L{d['layer']:<3} jsd {d['jsd_bits_mean']:.4f}  "
          f"score_mass_diff {d['score_mass_diff_mean']:.4f}", flush=True)
print(f"\n  SELECTED L{best}  window {window}  "
      f"(eligible {A.layer_lo}-{A.layer_hi}; final four excluded)", flush=True)
print(f"  runtime {sel['runtime_s']}s  peak {sel['peak_gpu_gib']} GiB", flush=True)
