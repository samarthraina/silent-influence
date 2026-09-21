"""Run ONE judge over the blinded silence-run items. NOT EXECUTED YET.

Deterministic decoding (do_sample=False, fixed seed, greedy), fixed JSON output, one item per
call. Resumable: an existing output file is read first and finished item_ids are skipped, so
a dropped connection costs minutes.

    python run_silence_judge.py --judge J1 --model <hf_id> --revision <sha> --out judge_J1_raw.jsonl

The judge never sees anything but item_id and rationale_text.
"""
import argparse
import json
import pathlib
import sys
import time

import torch

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from judge_prompt import build_messages, consistency_flag, parse_judge_output

ap = argparse.ArgumentParser()
ap.add_argument("--judge", required=True, choices=["J1", "J2"])
ap.add_argument("--model", required=True)
ap.add_argument("--revision", required=True)
ap.add_argument("--items", default=None)
ap.add_argument("--out", default=None)
ap.add_argument("--max-new-tokens", type=int, default=128)
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--limit", type=int, default=None)
ap.add_argument("--disable-thinking", action="store_true",
                help="pass enable_thinking=False to the chat template. Qwen3 emits a "
                     "<think> block by default and exhausts the token cap before the "
                     "JSON; the frozen behavioural study set disable_thinking=True for "
                     "this same model, so this matches it rather than inventing a setting.")
A = ap.parse_args()

items_path = pathlib.Path(A.items or HERE / f"blinded_items_{A.judge}.jsonl")
out_path = pathlib.Path(A.out or HERE / f"judge_{A.judge}_raw.jsonl")
items = [json.loads(l) for l in items_path.open(encoding="utf-8") if l.strip()]
if A.limit:
    items = items[:A.limit]

done = set()
if out_path.exists():
    for l in out_path.open(encoding="utf-8"):
        if l.strip():
            done.add(json.loads(l)["item_id"])
todo = [i for i in items if i["item_id"] not in done]
print(f"judge {A.judge} | {A.model}@{A.revision[:8]} | {len(todo)} of {len(items)} remaining",
      flush=True)

from transformers import AutoModelForCausalLM, AutoTokenizer

torch.manual_seed(A.seed)
tok = AutoTokenizer.from_pretrained(A.model, revision=A.revision,
                                    clean_up_tokenization_spaces=False)
model = AutoModelForCausalLM.from_pretrained(
    A.model, revision=A.revision, torch_dtype=torch.bfloat16,
    device_map={"": 0}, attn_implementation="sdpa")
model.eval()
if model.generation_config is not None:                 # neutralise shipped sampling
    model.generation_config.do_sample = False
    for k in ("temperature", "top_p", "top_k"):
        setattr(model.generation_config, k, None)
if tok.pad_token_id is None:
    tok.pad_token = tok.eos_token

t0 = time.time()
fh = out_path.open("a", encoding="utf-8")
n_ok = n_bad = 0
for i, it in enumerate(todo, 1):
    msgs = build_messages(it["rationale_text"])
    # transformers 5.x returns a BatchEncoding here, 4.x a bare tensor. Handle both rather
    # than pinning to one, so the runner does not silently depend on the minor version.
    tmpl_kw = {"enable_thinking": False} if A.disable_thinking else {}
    enc = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt",
                                  **tmpl_kw)
    if not torch.is_tensor(enc):
        enc = enc["input_ids"]
    ids = enc.to(model.device)
    with torch.no_grad():
        out = model.generate(input_ids=ids, max_new_tokens=A.max_new_tokens,
                             do_sample=False, pad_token_id=tok.pad_token_id, use_cache=True)
    raw = tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True)
    parsed, status = parse_judge_output(raw)
    rec = {"item_id": it["item_id"], "judge": A.judge, "model": A.model,
           "revision": A.revision, "raw_output": raw, "parse_status": status}
    if parsed:
        rec.update(parsed)
        rec["consistency_flag"] = consistency_flag(parsed)
        n_ok += 1
    else:
        n_bad += 1
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fh.flush()
    if i % 50 == 0 or i == len(todo):
        el = time.time() - t0
        print(f"  [{i}/{len(todo)}] ok={n_ok} bad={n_bad} {el/60:.1f}m "
              f"ETA {(el/i)*(len(todo)-i)/60:.1f}m", flush=True)
fh.close()
print(json.dumps({"judge": A.judge, "model": A.model, "revision": A.revision,
                  "n_items": len(items), "n_run": len(todo), "parsed_ok": n_ok,
                  "parse_failures": n_bad, "deterministic": True, "disable_thinking": A.disable_thinking,
                  "runtime_s": round(time.time() - t0, 1),
                  "peak_gpu_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)},
                 indent=2), flush=True)
