"""J3: independent external LLM-judge robustness check with openai/gpt-oss-20b.

Blinded. The judge receives only item_id and rationale_text, exactly as they appear in
blinded_items_J1.jsonl. No key file, no condition, scorer, dataset, task id or score is read
by this script, and no J1 / J2 / human file is opened.

Rubric: the frozen judge_prompt.py, imported unchanged. The label definitions, the JSON
contract and the evidence requirement all come from that module; nothing is restated here.

Inference follows the GPT-OSS setup used in Silent Social Influence:
vLLM, bfloat16, harmony chat format via the tokenizer template, reasoning effort low,
temperature 0.1, top_p 0.95, batches of 10 items. Seed is fixed at 20260821.

Resumable: an existing output file is read first and finished item_ids are skipped.
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from judge_prompt import GUIDE, build_messages, consistency_flag, parse_judge_output

ap = argparse.ArgumentParser()
ap.add_argument("--items", default=str(HERE / "blinded_items_J1.jsonl"))
ap.add_argument("--out", default=str(HERE / "judge_J3_gptoss_raw.jsonl"))
ap.add_argument("--model", default="openai/gpt-oss-20b")
ap.add_argument("--revision", default=None, help="resolved and recorded if omitted")
ap.add_argument("--batch-size", type=int, default=10)
ap.add_argument("--seed", type=int, default=20260821)
ap.add_argument("--reasoning-effort", default="low")
ap.add_argument("--max-model-len", type=int, default=8192)
ap.add_argument("--gpu-util", type=float, default=0.90)
ap.add_argument("--dtype", default="bfloat16", help="SSI used bfloat16; 'auto' keeps the checkpoint's native MXFP4 when bf16 does not fit 48 GB")
ap.add_argument("--max-tokens", type=int, default=2000)
ap.add_argument("--limit", type=int, default=None, help="smoke only")
ap.add_argument("--freeze-out", default=None)
A = ap.parse_args()

ITEMS = pathlib.Path(A.items)
OUT = pathlib.Path(A.out)

items = [json.loads(l) for l in ITEMS.open(encoding="utf-8") if l.strip()]
ids = [i["item_id"] for i in items]
assert len(items) == len(set(ids)) == 1872, (len(items), len(set(ids)))
for it in items:                      # blinding guard: nothing but the two allowed fields
    assert set(it) == {"item_id", "rationale_text"}, sorted(it)

if A.limit:
    items = items[:A.limit]

done = set()
if OUT.exists():
    for l in OUT.open(encoding="utf-8"):
        if l.strip():
            done.add(json.loads(l)["item_id"])
todo = [i for i in items if i["item_id"] not in done]

# ── freeze record: hashes taken before any inference ──────────────────────────────────
def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


from huggingface_hub import HfApi

rev = A.revision or HfApi().model_info(A.model).sha
FREEZE = {
    "stage": "J3 external LLM-judge robustness check",
    "judge_model": A.model, "model_revision": rev,
    "input_file": ITEMS.name, "input_sha256": sha(ITEMS),
    "n_items": len(items), "n_unique_ids": len(set(ids)),
    "prompt_module": "judge_prompt.py", "prompt_sha256": sha(HERE / "judge_prompt.py"),
    "prompt_guide_sha256": hashlib.sha256(GUIDE.encode("utf-8")).hexdigest(),
    "runner": pathlib.Path(__file__).name, "runner_sha256": sha(__file__),
    "label_definitions": "frozen in judge_prompt.GUIDE, imported unchanged",
    "labels": ["A", "N", "D", "U"],
    "also_recorded": ["context_mentioned yes/no", "verbatim evidence span"],
    "parser": "judge_prompt.parse_judge_output (strict; unknown labels are a failure)",
    "inference": {"engine": "vLLM", "dtype": A.dtype,
                  "chat_format": "harmony via tokenizer.apply_chat_template",
                  "reasoning_effort": A.reasoning_effort, "temperature": 0.1,
                  "top_p": 0.95, "seed": A.seed, "batch_size": A.batch_size,
                  "max_model_len": A.max_model_len, "max_tokens": A.max_tokens},
    "blinding": "judge sees item_id and rationale_text only",
    "files_not_opened": ["silence_key_PRIVATE.jsonl", "human_validation_key_PRIVATE.jsonl",
                         "human_validation_A.csv", "human_validation_B.csv",
                         "judge_J1_raw.jsonl", "judge_J2_raw.jsonl",
                         "agreement.json", "silence_joined.csv", "silence_summary.json"],
}
if A.freeze_out:
    pathlib.Path(A.freeze_out).write_text(json.dumps(FREEZE, indent=2), encoding="utf-8")
print(json.dumps(FREEZE, indent=2), flush=True)
print(f"  {len(todo)} of {len(items)} remaining", flush=True)

# ── vLLM ──────────────────────────────────────────────────────────────────────────────
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

tok = AutoTokenizer.from_pretrained(A.model, revision=rev)
llm = LLM(model=A.model, revision=rev, dtype=A.dtype, max_model_len=A.max_model_len,
          gpu_memory_utilization=A.gpu_util, enforce_eager=False, trust_remote_code=True,
          seed=A.seed)
sampling = SamplingParams(temperature=0.1, top_p=0.95, max_tokens=A.max_tokens, seed=A.seed)

SYSTEM = (f"You are a careful, precise rater. Reasoning: {A.reasoning_effort}. "
          f"Always respond with ONLY valid JSON as requested.")


def chat(user_text):
    return tok.apply_chat_template(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_text}],
        tokenize=False, add_generation_prompt=True)


t0 = time.time()
fh = OUT.open("a", encoding="utf-8")
n_ok = n_bad = 0
for bi in range(0, len(todo), A.batch_size):
    batch = todo[bi:bi + A.batch_size]
    # one item per prompt; batching is a throughput device, never a shared context
    prompts = [chat(build_messages(it["rationale_text"])[0]["content"]) for it in batch]
    outs = llm.generate(prompts, sampling)
    for it, o in zip(batch, outs):
        raw = o.outputs[0].text.strip()
        parsed, status = parse_judge_output(raw)
        rec = {"item_id": it["item_id"], "judge": "J3", "model": A.model,
               "revision": rev, "raw_output": raw, "parse_status": status}
        if parsed:
            rec.update(parsed)
            rec["consistency_flag"] = consistency_flag(parsed)
            n_ok += 1
        else:
            n_bad += 1
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fh.flush()
    done_n = bi + len(batch)
    if done_n % 100 < A.batch_size or done_n == len(todo):
        el = time.time() - t0
        print(f"  [{done_n}/{len(todo)}] ok={n_ok} bad={n_bad} {el/60:.1f}m "
              f"ETA {(el/done_n)*(len(todo)-done_n)/60:.1f}m", flush=True)
fh.close()
print(json.dumps({"judge": "J3", "model": A.model, "revision": rev,
                  "n_items": len(items), "n_run": len(todo), "parsed_ok": n_ok,
                  "parse_failures": n_bad, "runtime_s": round(time.time() - t0, 1)},
                 indent=2), flush=True)
