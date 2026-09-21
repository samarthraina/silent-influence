"""Cross-model patching replication: Gemma-2-9B-IT and Qwen3-8B.

Tests whether the Llama L24 activation-patching result replicates causally in two other
scorers. Behavioural scoring, rationale annotation, steering, ablation and Jacobian vocabulary
sweeps are all out of scope and are not run.

INSTRUMENT SUBSTITUTION, DECLARED. Llama's layer was selected with the Jacobian Lens using the
Neuronpedia lens fitted for Llama-3.1-8B. No fitted Jacobian lens exists for Gemma-2 or Qwen3,
none is cached, and this host is deliberately offline from the Hub. Layer selection here
therefore uses the same QUANTITY at the same position -- distributional divergence between the
two conditions' next-token readout at final_input -- but through the model's own unembedding
(a logit lens), not a Jacobian lens. The rule (peak divergence at final_input, one layer,
frozen before validation) is identical; the readout instrument is not. Layer indices are
therefore NOT comparable across models as "the same layer".

Everything else is the frozen final-study path: exact prompts, conditions, parsers, pinned
revisions, greedy decoding, batch size 1.
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
from silent_influence import final_study_messages as fsm
from silent_influence import patching
from silent_influence import scaled_conditions as sc

ap = argparse.ArgumentParser()
ap.add_argument("--stage", required=True, choices=["discovery", "validation"])
ap.add_argument("--scorer", required=True, choices=["gemma", "qwen"])
ap.add_argument("--manifest", required=True)
ap.add_argument("--candidates", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--layer-file", default=None, help="validation: frozen layer from discovery")
ap.add_argument("--early-layer", type=int, default=2)
ap.add_argument("--exclude-first", type=int, default=4)
ap.add_argument("--exclude-last", type=int, default=4)
A = ap.parse_args()

OUT = pathlib.Path(A.out_dir); OUT.mkdir(parents=True, exist_ok=True)
man = json.loads(pathlib.Path(A.manifest).read_text(encoding="utf-8"))
tasks = man["tasks"]
LO, HI = "self_low_2", "no_history"

import run_final_scoring as RFS

spec = next(s for s in RFS.SCORERS if s.key == A.scorer)
cands = {(c["dataset"], c["source_task_id"]): c for c in RFS.load_candidates(A.candidates)}
conds = {c.name: c for c in sc.CONDITIONS}

t0 = time.time()
torch.cuda.reset_peak_memory_stats()
from transformers import AutoModelForCausalLM, AutoTokenizer

tok = AutoTokenizer.from_pretrained(spec.hf_id, revision=spec.revision,
                                    local_files_only=True,
                                    clean_up_tokenization_spaces=False)
model = AutoModelForCausalLM.from_pretrained(
    spec.hf_id, revision=spec.revision, local_files_only=True,
    dtype=torch.bfloat16, device_map={"": 0}, attn_implementation="sdpa")
model.eval()
if model.generation_config is not None:            # frozen determinism
    model.generation_config.do_sample = False
    for k in ("temperature", "top_p", "top_k"):
        setattr(model.generation_config, k, None)
if tok.pad_token_id is None:
    tok.pad_token = tok.eos_token
n_layers = model.config.num_hidden_layers
MAXNEW = spec.max_new_tokens
print(f"{A.scorer} {spec.hf_id}@{spec.revision[:8]} | {n_layers} layers | "
      f"max_new_tokens={MAXNEW} | stage={A.stage}", flush=True)

# module addressing the patching hooks assume
patching._module_for_layer(model, 0)
patching._module_for_layer(model, n_layers)


def render(cand, cname):
    prompt = sc.render_prompt(cand["question"], cand["answer"], conds[cname])
    msgs = fsm.build_scorer_messages(A.scorer, prompt)
    # Qwen3 emits a <think> block by default and would spend the frozen 512-token ceiling
    # on it. ExactModelSpec.disable_thinking is the frozen behavioural setting for this
    # scorer, so it is honoured here rather than re-decided.
    tkw = {"enable_thinking": False} if getattr(spec, "disable_thinking", False) else {}
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, **tkw)
    enc = tok(text, return_tensors="pt", return_offsets_mapping=True,
              add_special_tokens=False)
    offs = enc.pop("offset_mapping")[0].tolist()
    sp = act.locate_positions(text, offs, None, None)      # final_input only
    return enc["input_ids"].to(model.device), sp["final_input"].token_indices


def gen(ids):
    with torch.no_grad():
        o = model.generate(input_ids=ids, max_new_tokens=MAXNEW, do_sample=False,
                           pad_token_id=tok.pad_token_id, use_cache=True)
    seq = o[0, ids.shape[1]:]
    return (tok.decode(seq, skip_special_tokens=True), int(seq.shape[0]),
            bool((seq == tok.eos_token_id).any().item()))


def a5(n_out, em):
    return not (n_out >= MAXNEW and not em)


_norm = model.model.norm
_head = model.lm_head
_softcap = getattr(model.config, "final_logit_softcapping", None)


def readout(h):
    """The model's own next-token readout from a residual state (logit lens)."""
    lg = _head(_norm(h.to(_head.weight.dtype)))
    if _softcap:
        lg = _softcap * torch.tanh(lg / _softcap)
    return lg.float().reshape(-1)


def jsd_bits(p_log, q_log):
    p = torch.softmax(p_log, -1); q = torch.softmax(q_log, -1)
    m = 0.5 * (p + q); lm = m.clamp_min(1e-12).log()
    kl_p = (p * (p.clamp_min(1e-12).log() - lm)).sum(-1)
    kl_q = (q * (q.clamp_min(1e-12).log() - lm)).sum(-1)
    return float((0.5 * (kl_p + kl_q) / np.log(2.0)).item())


# ------------------------------------------------------------------ discovery
if A.stage == "discovery":
    rows = []
    for i, t in enumerate(tasks, 1):
        cand = cands[(t["dataset"], t["task_id"])]
        h = {}
        for c in (LO, HI):
            ids, pos = render(cand, c)
            with torch.no_grad():
                o = model(input_ids=ids, output_hidden_states=True, use_cache=False)
            h[c] = {L: o.hidden_states[L][0, pos[0], :].detach().float()
                    for L in range(1, n_layers + 1)}
            del o
        for L in range(1, n_layers + 1):
            a, b = h[LO][L], h[HI][L]
            cos = float(torch.nn.functional.cosine_similarity(a, b, dim=0))
            rows.append({"dataset": t["dataset"], "task_id": t["task_id"], "layer": L,
                         "jsd_bits": jsd_bits(readout(a), readout(b)),
                         "cosine_divergence": 1.0 - cos})
        print(f"  [{i}/{len(tasks)}] {t['dataset']}/{t['task_id']} "
              f"({time.time()-t0:.0f}s)", flush=True)
    with (OUT / f"discovery_{A.scorer}_per_task_layer.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    by = {}
    for L in range(1, n_layers + 1):
        sub = [r for r in rows if r["layer"] == L]
        by[L] = {"layer": L,
                 "jsd_bits_mean": float(np.mean([r["jsd_bits"] for r in sub])),
                 "jsd_bits_sd": float(np.std([r["jsd_bits"] for r in sub], ddof=1)),
                 "cosine_divergence_mean": float(np.mean([r["cosine_divergence"] for r in sub]))}
    lo_ok, hi_ok = A.exclude_first + 1, n_layers - A.exclude_last
    elig = [L for L in by if lo_ok <= L <= hi_ok]
    best = max(elig, key=lambda L: by[L]["jsd_bits_mean"])
    sel = {"scorer": A.scorer, "stage": "DISCOVERY -- frozen before validation",
           "n_layers": n_layers, "position": "final_input",
           "selection_metric": "logit-lens JSD (bits) between the two conditions' readouts",
           "instrument_note": "NOT a Jacobian lens; no fitted lens exists for this model. "
                              "Same quantity and position as the Llama rule, different readout.",
           "eligible_layers": [lo_ok, hi_ok],
           "excluded_first": A.exclude_first, "excluded_last": A.exclude_last,
           "selected_layer": best, "n_discovery_tasks": len(tasks),
           "by_layer": [by[L] for L in sorted(by)],
           "selected_before_any_validation_run": True,
           "runtime_s": round(time.time() - t0, 1),
           "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
    (OUT / f"SELECTED_LAYER_{A.scorer}.json").write_text(json.dumps(sel, indent=2),
                                                         encoding="utf-8")
    top = sorted((by[L] for L in elig), key=lambda d: -d["jsd_bits_mean"])[:6]
    print("\n  top eligible layers by mean JSD:", flush=True)
    for d in top:
        print(f"    L{d['layer']:<3} jsd {d['jsd_bits_mean']:.4f}  "
              f"cos_div {d['cosine_divergence_mean']:.4f}", flush=True)
    print(f"  SELECTED L{best} (eligible {lo_ok}-{hi_ok} of {n_layers}) "
          f"{sel['runtime_s']}s peak {sel['peak_gpu_gib']} GiB", flush=True)
    raise SystemExit(0)

# ------------------------------------------------------------------ validation
LAYER = json.loads(pathlib.Path(A.layer_file).read_text(encoding="utf-8"))["selected_layer"]
print(f"  frozen layer L{LAYER} | early control L{A.early_layer} | {len(tasks)} tasks",
      flush=True)
rec_path = OUT / f"validation_{A.scorer}.jsonl"
done = set()
if rec_path.exists():
    for l in rec_path.open(encoding="utf-8"):
        if l.strip():
            done.add(json.loads(l)["unit"])
fh = rec_path.open("a", encoding="utf-8")
n = 0
for ti, t in enumerate(tasks, 1):
    cand = cands[(t["dataset"], t["task_id"])]
    ids, pos, caps = {}, {}, {}
    for c in (LO, HI):
        ids[c], pos[c] = render(cand, c)
        with torch.no_grad():
            o = model(input_ids=ids[c], output_hidden_states=True, use_cache=False)
        caps[c] = {L: o.hidden_states[L][0, pos[c], :].detach().clone()
                   for L in (LAYER, A.early_layer)}
        del o
    base = {}
    for c in (LO, HI):
        txt, no_, em = gen(ids[c])
        s, st = MA.score_of(txt)
        base[c] = s
        key = f"baseline|{t['dataset']}/{t['task_id']}|{c}"
        if key not in done:
            fh.write(json.dumps({"unit": key, "arm": f"baseline_{c}", "scorer": A.scorer,
                                 "dataset": t["dataset"], "task_id": t["task_id"],
                                 "condition": c, "layer": None, "score": s,
                                 "parse_status": st, "a5_valid": a5(no_, em),
                                 "output_tokens": no_,
                                 "archived_behavioural_score": t.get(c)}) + "\n")
            fh.flush(); n += 1

    def run(arm, cond, ctx, layer, extra=None):
        global n
        key = f"{arm}|{t['dataset']}/{t['task_id']}"
        if key in done:
            return
        with ctx:
            txt, no_, em = gen(ids[cond])
        s, st = MA.score_of(txt)
        r = {"unit": key, "arm": arm, "scorer": A.scorer, "dataset": t["dataset"],
             "task_id": t["task_id"], "condition": cond, "layer": layer, "score": s,
             "parse_status": st, "a5_valid": a5(no_, em), "output_tokens": no_,
             "target_baseline": base[cond],
             "self_low_2_endpoint": base[LO], "no_history_endpoint": base[HI]}
        if extra:
            r.update(extra)
        fh.write(json.dumps(r) + "\n"); fh.flush(); n += 1

    for L, tag in ((LAYER, f"L{LAYER}"), (A.early_layer, f"L{A.early_layer}")):
        run(f"patch_{tag}_lo2hi", HI, patching.patch_positions(model, L, pos[HI], caps[LO][L]),
            L, {"direction": "self_low_2->no_history", "source_baseline": base[LO]})
        run(f"patch_{tag}_hi2lo", LO, patching.patch_positions(model, L, pos[LO], caps[HI][L]),
            L, {"direction": "no_history->self_low_2", "source_baseline": base[HI]})
    for c in (LO, HI):
        run(f"noop_{c}", c, patching.no_patch(model, LAYER), LAYER)
        run(f"same_{c}", c, patching.patch_positions(model, LAYER, pos[c], caps[c][LAYER]),
            LAYER)
    el = time.time() - t0
    print(f"  [{ti}/{len(tasks)}] {t['dataset']}/{t['task_id']} {n} calls {el/60:.1f}m "
          f"ETA {(el/ti)*(len(tasks)-ti)/60:.1f}m", flush=True)
fh.close()
meta = {"scorer": A.scorer, "stage": "VALIDATION", "selected_layer": LAYER,
        "early_layer": A.early_layer, "n_tasks": len(tasks), "n_calls": n,
        "layer_frozen_before_validation": True,
        "runtime_s": round(time.time() - t0, 1),
        "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
(OUT / f"validation_meta_{A.scorer}.json").write_text(json.dumps(meta, indent=2),
                                                      encoding="utf-8")
print(json.dumps(meta, indent=2), flush=True)
