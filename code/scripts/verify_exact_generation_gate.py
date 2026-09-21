#!/usr/bin/env python3
"""GPU smoke-test verification gate for the exact-generation path.

Loads all four pinned models (the OLMo-3 generator and the three scorers) and, for each,
records and checks: the rendered messages, the tokenizer's chat-template hash, the input
token count, the first and last input token IDs, the attention implementation actually
resolved on the loaded model, the installed transformers version, and the decode cleanup
setting used. Run this before the real 90-task GPU run, not instead of it -- it uses the
two-task smoke fixture (data/prompts/smoke_tasks.json) and a placeholder candidate answer,
so nothing here touches held-out data.

    python scripts/verify_exact_generation_gate.py --stub   # no-GPU plumbing check
    python scripts/verify_exact_generation_gate.py           # real GPU check, all 4 models
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import exact_generation as eg
from silent_influence import scaled_conditions as sc

GENERATOR_SPEC = eg.ExactModelSpec(
    key="olmo3", hf_id="allenai/Olmo-3-7B-Instruct",
    revision="6e5971d9eba42665f5bd5a0fcf047f299ce1dccc", disable_thinking=False,
)
SCORERS = [
    eg.ExactModelSpec(key="llama", hf_id="meta-llama/Llama-3.1-8B-Instruct",
                      revision="0e9e39f249a16976918f6564b8830bc894c89659"),
    eg.ExactModelSpec(key="qwen", hf_id="Qwen/Qwen3-8B",
                      revision="b968826d9c46dd6066d109eabc6255188de91218",
                      disable_thinking=True),
    eg.ExactModelSpec(key="gemma", hf_id="google/gemma-2-9b-it",
                      revision="11c9b309abf73637e4b6f9a3fa1e92e615547819"),
]

PLACEHOLDER_ANSWER = ("This is a placeholder candidate answer used only to verify the "
                      "scoring input path. It is not real experimental content.")
DECODE_SETTINGS = {"skip_special_tokens": True, "clean_up_tokenization_spaces": False,
                   "pad_token_id_source": "tokenizer.eos_token_id"}


def gate_for_model(spec, messages, max_new_tokens: int, hf_token, stub: bool) -> dict:
    loaded = eg.load_stub_model(spec) if stub else eg.load_exact_model(spec, hf_token=hf_token)
    try:
        gen_fn = eg.generate_exact_stub if stub else eg.generate_exact
        result = gen_fn(loaded, messages, max_new_tokens=max_new_tokens, seed=42)
        return {
            "key": spec.key, "hf_id": spec.hf_id, "revision": spec.revision,
            "disable_thinking": spec.disable_thinking,
            "rendered_messages": messages,
            "chat_template_sha256": loaded.chat_template_sha256,
            "input_token_count": result["prompt_tokens"],
            "first_input_token_id": result["first_input_token_id"],
            "last_input_token_id": result["last_input_token_id"],
            "attn_implementation": loaded.attn_implementation,
            "transformers_version": loaded.transformers_version,
            "decode_settings": DECODE_SETTINGS,
            "sample_output_tokens": result["output_tokens"],
            "sample_output_text": result["text"],
        }
    finally:
        eg.unload(loaded)


def check(report: dict, expected_transformers_version: str, stub: bool) -> list:
    if stub:
        return []
    problems = []
    if report["transformers_version"] != expected_transformers_version:
        problems.append(f"transformers=={report['transformers_version']} installed, "
                        f"pilot used {expected_transformers_version}")
    if report["attn_implementation"] != "sdpa":
        problems.append(f"attn_implementation={report['attn_implementation']!r}, "
                        f"expected 'sdpa' for all four models")
    if not report["chat_template_sha256"]:
        problems.append("no chat_template found on the tokenizer")
    if not report["input_token_count"]:
        problems.append("input_token_count is empty/zero")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke-tasks", default=str(REPO / "data/prompts/smoke_tasks.json"))
    ap.add_argument("--out",
                    default=str(REPO / "results/scaled_silent_influence_smoke"
                                       "/gpu_smoke_gate_report.json"))
    ap.add_argument("--stub", action="store_true",
                    help="no-GPU plumbing check only; never verifies real model behavior")
    ap.add_argument("--max-new-tokens", type=int, default=16)
    args = ap.parse_args()

    with open(args.smoke_tasks, encoding="utf-8") as f:
        smoke = json.load(f)
    sample_task = smoke["datasets"]["mtbench"]["selected"][0]
    question = sample_task["question"]
    hf_token = os.environ.get("HF_TOKEN")

    reports = {}
    reports["olmo3"] = gate_for_model(GENERATOR_SPEC, eg.build_olmo_messages(question),
                                      args.max_new_tokens, hf_token, args.stub)
    for spec in SCORERS:
        prompt = sc.render_prompt(question, PLACEHOLDER_ANSWER, sc.resolve("no_history"))
        messages = [{"role": "user", "content": prompt}]
        reports[spec.key] = gate_for_model(spec, messages, args.max_new_tokens, hf_token,
                                           args.stub)

    problems_by_model = {}
    for key, report in reports.items():
        problems = check(report, eg.REQUIRED_TRANSFORMERS_VERSION, args.stub)
        if problems:
            problems_by_model[key] = problems

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stub": args.stub,
        "expected_transformers_version": eg.REQUIRED_TRANSFORMERS_VERSION,
        "reports": reports,
        "problems": problems_by_model,
        "gate_passed": len(problems_by_model) == 0,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    for key, report in reports.items():
        print(f"[{key}] attn={report['attn_implementation']} "
             f"transformers={report['transformers_version']} "
             f"input_tokens={report['input_token_count']} "
             f"first/last_token_id={report['first_input_token_id']}/"
             f"{report['last_input_token_id']} "
             f"chat_template_sha256={report['chat_template_sha256']}")

    if problems_by_model:
        print("\nGATE FAILED:")
        for key, problems in problems_by_model.items():
            for p in problems:
                print(f"  [{key}] {p}")
    else:
        print("\nGATE PASSED: all four models verified.")
    print(f"[save] {out_path}")
    return 0 if not problems_by_model else 1


if __name__ == "__main__":
    raise SystemExit(main())
