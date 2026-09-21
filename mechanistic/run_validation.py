"""STAGE 2 -- HELD-OUT CAUSAL VALIDATION. 24 validation tasks, disjoint from discovery.

The layer window is read from SELECTED_WINDOW.json, which stage 1 wrote before this script
ever ran. It is not recomputed, and nothing here can change it.

Per task, per window layer, both transfer directions at final_input:
    self_low_2 -> no_history      (does the low-prior state pull the clean run down?)
    no_history -> self_low_2      (does the clean state pull the primed run up?)

Controls, run identically:
    noop_<cond>       hooks installed and firing, writing nothing -- identity check
    same_<cond>       the condition's own captured state written back over itself
    early_L<k>        the same cross-condition patch at an early layer

Every generation goes through the frozen behavioural path: frozen prompts, greedy decoding,
frozen token ceiling, frozen parser, frozen A5 validity rule.
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
from silent_influence import output_validity as ov
from silent_influence import patching
from silent_influence import scaled_conditions as sc

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True)
ap.add_argument("--candidates", required=True)
ap.add_argument("--window-file", required=True)
ap.add_argument("--out-dir", required=True)
ap.add_argument("--early-layer", type=int, default=2)
A = ap.parse_args()

OUT = pathlib.Path(A.out_dir); OUT.mkdir(parents=True, exist_ok=True)
man = json.loads(pathlib.Path(A.manifest).read_text(encoding="utf-8"))
win = json.loads(pathlib.Path(A.window_file).read_text(encoding="utf-8"))
WINDOW, SELECTED = win["window"], win["selected_layer"]
tasks = man["validation"]
LO, HI = "self_low_2", "no_history"
POS = "final_input"

import run_final_scoring as RFS

spec = next(s for s in RFS.SCORERS if s.key == "llama")
cands = {(c["dataset"], c["source_task_id"]): c
         for c in RFS.load_candidates(A.candidates)}
conds = {c.name: c for c in sc.CONDITIONS}
hist_prefix = conds[LO].added_context.split("2/10")[0]

t_start = time.time()
torch.cuda.reset_peak_memory_stats()
loaded = eg.load_exact_model(spec, hf_token=None)
model, tok = loaded.model, loaded.tokenizer
n_layers = model.config.num_hidden_layers
print(f"window {WINDOW} (selected L{SELECTED}) | early control L{A.early_layer} | "
      f"{len(tasks)} tasks", flush=True)
assert all(L <= n_layers - 4 for L in WINDOW), "window entered the final four layers"


def render(cand, cond_name):
    prompt = sc.render_prompt(cand["question"], cand["answer"], conds[cond_name])
    messages = fsm.build_scorer_messages("llama", prompt)
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    enc = tok(text, return_tensors="pt", return_offsets_mapping=True,
              add_special_tokens=False)
    offs = enc.pop("offset_mapping")[0].tolist()
    return text, enc["input_ids"].to(model.device), offs


def gen(ids):
    with torch.no_grad():
        out = model.generate(input_ids=ids, max_new_tokens=spec.max_new_tokens,
                             do_sample=False, pad_token_id=tok.pad_token_id,
                             use_cache=True)
    seq = out[0, ids.shape[1]:]
    text = tok.decode(seq, skip_special_tokens=True)
    emitted = bool((seq == tok.eos_token_id).any().item()) if tok.eos_token_id is not None \
        else False
    return text, int(seq.shape[0]), emitted


def a5_valid(n_out, emitted):
    """Frozen A5 rule: a response that exhausted the ceiling without a terminator is
    capped_incomplete and invalid for analysis."""
    return not (n_out >= spec.max_new_tokens and not emitted)


rec_path = OUT / "validation_records.jsonl"
done = set()
if rec_path.exists():
    for l in rec_path.open(encoding="utf-8"):
        if l.strip():
            done.add(json.loads(l)["unit"])

fh = rec_path.open("a", encoding="utf-8")


def emit(**kw):
    fh.write(json.dumps(kw) + "\n")
    fh.flush()


n_done = 0
for ti, t in enumerate(tasks, 1):
    cand = cands[(t["dataset"], t["task_id"])]
    R, spans, caps = {}, {}, {}
    for c in (LO, HI):
        text, ids, offs = render(cand, c)
        sv = 2 if c == LO else None
        sp = act.locate_positions(text, offs, None if sv is None else hist_prefix, sv)
        spans[c] = sp[POS].token_indices
        R[c] = ids
        with torch.no_grad():
            out = model(input_ids=ids, output_hidden_states=True, use_cache=False)
        caps[c] = {L: out.hidden_states[L][0, spans[c], :].detach().clone()
                   for L in set(WINDOW) | {A.early_layer}}
        del out

    base = {}
    for c in (LO, HI):
        key = f"baseline|{t['dataset']}/{t['task_id']}|{c}"
        txt, n_out, em = gen(R[c])
        s, st = MA.score_of(txt)
        base[c] = s
        emit(unit=key, kind="baseline", dataset=t["dataset"], task_id=t["task_id"],
             condition=c, layer=None, score=s, parse_status=st,
             a5_valid=a5_valid(n_out, em), output_tokens=n_out,
             frozen_behavioural_score=t[c])
        n_done += 1

    for L in sorted(set(WINDOW) | {A.early_layer}):
        is_early = L == A.early_layer and L not in WINDOW
        for src, tgt in ((LO, HI), (HI, LO)):
            kind = "early_control" if is_early else "transfer"
            key = f"{kind}|{t['dataset']}/{t['task_id']}|{src}->{tgt}|L{L}"
            if key in done:
                continue
            with patching.patch_positions(model, L, spans[tgt], caps[src][L]):
                txt, n_out, em = gen(R[tgt])
            s, st = MA.score_of(txt)
            emit(unit=key, kind=kind, dataset=t["dataset"], task_id=t["task_id"],
                 direction=f"{src}->{tgt}", source_condition=src, target_condition=tgt,
                 layer=L, score=s, parse_status=st, a5_valid=a5_valid(n_out, em),
                 output_tokens=n_out, target_baseline=base[tgt], source_baseline=base[src])
            n_done += 1

        for c in (LO, HI):   # same-condition patch: writing a state back over itself
            key = f"same|{t['dataset']}/{t['task_id']}|{c}|L{L}"
            if key in done:
                continue
            with patching.patch_positions(model, L, spans[c], caps[c][L]):
                txt, n_out, em = gen(R[c])
            s, st = MA.score_of(txt)
            emit(unit=key, kind="same_condition", dataset=t["dataset"],
                 task_id=t["task_id"], condition=c, layer=L, score=s, parse_status=st,
                 a5_valid=a5_valid(n_out, em), output_tokens=n_out, target_baseline=base[c])
            n_done += 1

        for c in (LO, HI):   # no-op: hooks fire, write nothing
            key = f"noop|{t['dataset']}/{t['task_id']}|{c}|L{L}"
            if key in done:
                continue
            with patching.no_patch(model, L):
                txt, n_out, em = gen(R[c])
            s, st = MA.score_of(txt)
            emit(unit=key, kind="noop", dataset=t["dataset"], task_id=t["task_id"],
                 condition=c, layer=L, score=s, parse_status=st,
                 a5_valid=a5_valid(n_out, em), output_tokens=n_out, target_baseline=base[c])
            n_done += 1

    el = time.time() - t_start
    print(f"  [{ti}/{len(tasks)}] {t['dataset']}/{t['task_id']}  {n_done} calls  "
          f"{el/60:.1f}m  ETA {(el/ti)*(len(tasks)-ti)/60:.1f}m", flush=True)

fh.close()
meta = {"stage": "HELD-OUT VALIDATION", "window": WINDOW, "selected_layer": SELECTED,
        "early_control_layer": A.early_layer, "n_tasks": len(tasks),
        "n_calls": n_done, "position": POS,
        "layer_selected_before_validation": True,
        "runtime_s": round(time.time() - t_start, 1),
        "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
(OUT / "validation_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
print(json.dumps(meta, indent=2), flush=True)
