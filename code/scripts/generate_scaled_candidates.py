#!/usr/bin/env python3
"""Generate the 90 frozen Olmo-3-7B-Instruct candidate answers for the scaled experiment.

One answer per selected task, generated once, then treated as immutable experimental
input: every judge under every condition scores byte-identical text. Uses
silent_influence.exact_generation, an isolated path that reproduces the pilot's actual
model-input path -- verified by reading the code cell titled "HELD-OUT MT-BENCH SILENT
CONTEXT EXPERIMENT" in SSI_vs_SI.ipynb directly, not assumed. In particular, the OLMo
messages are NOT candidate_gen.build_answer_messages(): the pilot's system message is only
"You are producing the response..."; the "no scratch work" instruction is appended to the
USER turn after the question, not folded into the system message. See
exact_generation.build_olmo_messages() and its module docstring for the full verified list
(model loading kwargs, chat-template call shape, seeding, decode settings).

A weak, incorrect, refusing, unusually long, or token-capped answer is a VALID outcome and
is frozen as-is; it is never regenerated or swapped out (a deliberate, approved departure
from the pilot notebook, which excluded capped/empty answers before judging -- see the
implementation report). Only a genuine technical failure (an exception during generation,
or literally empty output) triggers a bounded retry and, if that still fails, a documented
substitution with the next task on that dataset's frozen, predetermined reserve list
(never a fresh draw).

Resumable: generation_state.json tracks, per slot, which task currently fills it and
whether it has an accepted answer yet; a slot already accepted is never regenerated.

    python scripts/generate_scaled_candidates.py --dry-run
    python scripts/generate_scaled_candidates.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import exact_generation as eg
from silent_influence.environment import capture_environment
from silent_influence.logging_utils import make_logger
from silent_influence.records import RecordWriter, write_manifest

SELECTION_FILE = REPO / "data/prompts/scaled_tasks_seed20260816.json"
OUT_DIR = REPO / "results/scaled_silent_influence"
CANDIDATES_OUT = REPO / "data/candidates/scaled_olmo_answers.json"
STATE_FILE_NAME = "generation_state.json"

GENERATOR_SPEC = eg.ExactModelSpec(
    key="olmo3", hf_id="allenai/Olmo-3-7B-Instruct",
    revision="6e5971d9eba42665f5bd5a0fcf047f299ce1dccc", disable_thinking=False,
)
MAX_NEW_TOKENS = 2048
GEN_SEED = 42
MAX_RETRIES_PER_TASK = 3      # genuine technical failures only
MAX_SUBSTITUTIONS_PER_SLOT = 10  # generous cap; reserve lists are 4 (mtbench) to 655


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_technical_failure(text, err) -> bool:
    return err is not None or text is None or not text.strip()


def load_state(path: Path, selection: dict) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    slots = {}
    for ds_name, ds in selection["datasets"].items():
        for t in ds["selected"]:
            slot_id = f"{ds_name}:{t['task_id']}"
            slots[slot_id] = {"dataset": ds_name, "slot_task_id": t["task_id"],
                              "current_task_id": t["task_id"], "attempts": [],
                              "accepted": False}
    return {"slots": slots,
           "reserve_cursor": {ds: 0 for ds in selection["datasets"]},
           "substitutions": []}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


def lookup_task(selection: dict, ds_name: str, task_id: str) -> dict:
    ds = selection["datasets"][ds_name]
    for t in ds["selected"] + ds["reserve"]:
        if t["task_id"] == task_id:
            return t
    raise KeyError(f"{ds_name}:{task_id} not found in selection or reserve")


def attempt_generation(loaded, task: dict, log, stub: bool) -> dict:
    msgs = eg.build_olmo_messages(task["question"])
    err, tb = None, None
    try:
        gen_fn = eg.generate_exact_stub if stub else eg.generate_exact
        result = gen_fn(loaded, msgs, max_new_tokens=MAX_NEW_TOKENS, seed=GEN_SEED)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc(limit=6)
        result = {"text": None, "output_tokens": None, "hit_token_cap": False,
                 "generation_seconds": 0.0, "prompt_tokens": None,
                 "first_input_token_id": None, "last_input_token_id": None}
    text = (result["text"] or "").strip()
    return {
        "text": text, "text_sha256": sha256_text(text) if text else None,
        "output_tokens": result["output_tokens"], "prompt_tokens": result["prompt_tokens"],
        "hit_token_cap": bool(result["hit_token_cap"]), "generation_error": err,
        "generation_traceback": tb, "generation_seconds": result["generation_seconds"],
        "generation_messages": msgs,
        "first_input_token_id": result["first_input_token_id"],
        "last_input_token_id": result["last_input_token_id"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="generate only the first N slots (smoke/dev use)")
    ap.add_argument("--stub", action="store_true",
                    help="use the deterministic no-GPU stub to test plumbing "
                         "(resume/retry/substitution/idempotency) only; never a source "
                         "of experimental data")
    ap.add_argument("--selection-file", default=str(SELECTION_FILE),
                    help="frozen selection to generate from (override for the smoke "
                         "fixture: data/prompts/smoke_tasks.json)")
    ap.add_argument("--out", default=str(OUT_DIR),
                    help="output directory (override to keep smoke output separate, "
                         "e.g. results/scaled_silent_influence_smoke)")
    ap.add_argument("--candidates-out", default=str(CANDIDATES_OUT))
    args = ap.parse_args()

    selection_file = Path(args.selection_file)
    out_dir = Path(args.out)
    candidates_out = Path(args.candidates_out)

    with open(selection_file, encoding="utf-8") as f:
        selection = json.load(f)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = make_logger(out_dir / "run.log")
    if not args.stub:
        eg.check_transformers_version(log)
    log(f"[generate_scaled_candidates] selection={selection_file}")
    log(f"[generate_scaled_candidates] generator={GENERATOR_SPEC.hf_id} "
       f"rev={GENERATOR_SPEC.revision} max_new_tokens={MAX_NEW_TOKENS} seed={GEN_SEED}")

    slot_ids_in_order = [f"{ds_name}:{t['task_id']}"
                         for ds_name, ds in selection["datasets"].items()
                         for t in ds["selected"]]
    if args.limit is not None:
        slot_ids_in_order = slot_ids_in_order[:args.limit]
    log(f"[plan] {len(slot_ids_in_order)} slots")

    if args.dry_run:
        for sid in slot_ids_in_order[:5]:
            ds_name, task_id = sid.split(":", 1)
            task = lookup_task(selection, ds_name, task_id)
            msgs = eg.build_olmo_messages(task["question"])
            log(f"  [{sid}] system={msgs[0]['content'][:80]}...")
            log(f"           user={msgs[1]['content'][:120]}...")
        log("[dry-run] nothing generated.")
        return 0

    state_path = out_dir / STATE_FILE_NAME
    state = load_state(state_path, selection)
    rec_path = out_dir / "generation_records.jsonl"

    todo = [sid for sid in slot_ids_in_order if not state["slots"][sid]["accepted"]]
    log(f"[resume] {len(slot_ids_in_order) - len(todo)} slots already accepted; "
       f"{len(todo)} remaining")

    if not todo:
        log("[skip] nothing to generate; rebuilding frozen candidates from state.")
    else:
        hf_token = os.environ.get("HF_TOKEN")
        loaded = (eg.load_stub_model(GENERATOR_SPEC) if args.stub
                 else eg.load_exact_model(GENERATOR_SPEC, hf_token=hf_token))
        log(f"[model] loaded {GENERATOR_SPEC.hf_id} "
           f"attn={loaded.attn_implementation} transformers={loaded.transformers_version} "
           f"chat_template_sha256={loaded.chat_template_sha256}")
        try:
            with RecordWriter(rec_path) as writer:
                for i, sid in enumerate(todo, 1):
                    slot = state["slots"][sid]
                    ds_name = slot["dataset"]
                    n_subs_this_slot = 0
                    while not slot["accepted"]:
                        task = lookup_task(selection, ds_name, slot["current_task_id"])
                        result, technical_fail = None, True
                        for attempt in range(1, MAX_RETRIES_PER_TASK + 1):
                            result = attempt_generation(loaded, task, log, args.stub)
                            technical_fail = is_technical_failure(result["text"],
                                                                  result["generation_error"])
                            writer.write({
                                "run_id": "scaled_silent_influence_generation",
                                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "slot_id": sid, "dataset": ds_name,
                                "slot_task_id": slot["slot_task_id"],
                                "task_id": task["task_id"], "attempt": attempt,
                                "technical_failure": technical_fail,
                                "accepted": False,  # updated retroactively below on success
                                **result,
                            })
                            if not technical_fail:
                                break
                            log(f"  [{sid}] attempt {attempt}/{MAX_RETRIES_PER_TASK} "
                               f"technical failure: {result['generation_error'] or 'empty output'}")

                        slot["attempts"].append({"task_id": task["task_id"],
                                                  "technical_failure": technical_fail})

                        if not technical_fail:
                            slot["accepted"] = True
                            slot["current_task_id"] = task["task_id"]
                            flag = " TRUNCATED" if result["hit_token_cap"] else ""
                            log(f"  [{i}/{len(todo)}] {sid} -> {task['task_id']} "
                               f"{result['output_tokens']} tok in "
                               f"{result['generation_seconds']:.1f}s{flag}")
                            break

                        n_subs_this_slot += 1
                        if n_subs_this_slot > MAX_SUBSTITUTIONS_PER_SLOT:
                            raise RuntimeError(
                                f"{sid}: exceeded {MAX_SUBSTITUTIONS_PER_SLOT} "
                                f"substitutions; reserve exhausted or systemic failure")
                        cursor = state["reserve_cursor"][ds_name]
                        reserve = selection["datasets"][ds_name]["reserve"]
                        if cursor >= len(reserve):
                            raise RuntimeError(f"{sid}: reserve exhausted for {ds_name}")
                        replacement = reserve[cursor]
                        state["reserve_cursor"][ds_name] = cursor + 1
                        sub = {"slot_id": sid, "failed_task_id": task["task_id"],
                              "replacement_task_id": replacement["task_id"],
                              "reason": (result["generation_error"] or
                                        "empty output after "
                                        f"{MAX_RETRIES_PER_TASK} attempts"),
                              "at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                        state["substitutions"].append(sub)
                        log(f"  [{sid}] SUBSTITUTION: {task['task_id']} -> "
                           f"{replacement['task_id']} ({sub['reason']})")
                        slot["current_task_id"] = replacement["task_id"]
                        save_state(state_path, state)

                    save_state(state_path, state)
        finally:
            eg.unload(loaded)

    # Rebuild the frozen candidates file from state + generation records (idempotent).
    all_records = []
    for line in open(rec_path, encoding="utf-8") if rec_path.exists() else []:
        line = line.strip()
        if line:
            all_records.append(json.loads(line))

    accepted = []
    for sid in slot_ids_in_order:
        slot = state["slots"][sid]
        assert slot["accepted"], f"{sid} has no accepted answer"
        final_task_id = slot["current_task_id"]
        matches = [r for r in all_records
                  if r["slot_id"] == sid and r["task_id"] == final_task_id
                  and not r["technical_failure"]]
        assert matches, f"{sid}: no successful record found for {final_task_id}"
        r = matches[-1]
        task = lookup_task(selection, slot["dataset"], final_task_id)
        accepted.append({
            "dataset": slot["dataset"], "slot_task_id": slot["slot_task_id"],
            "generated_task_id": final_task_id,
            "is_substitution": final_task_id != slot["slot_task_id"],
            "category": task["category"], "question": task["question"],
            "answer": r["text"], "answer_sha256": r["text_sha256"],
            "output_tokens": r["output_tokens"], "hit_token_cap": r["hit_token_cap"],
            "generation_seconds": r["generation_seconds"],
            "generator_model": GENERATOR_SPEC.hf_id,
            "generator_revision": GENERATOR_SPEC.revision,
        })

    payload = {
        "generator": {"key": GENERATOR_SPEC.key, "hf_id": GENERATOR_SPEC.hf_id,
                     "revision": GENERATOR_SPEC.revision},
        "generation_params": {"do_sample": False, "max_new_tokens": MAX_NEW_TOKENS,
                              "pad_token_id": "tokenizer.eos_token_id"},
        "generation_seed": GEN_SEED,
        "selection_seed": selection["selection_seed"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_accepted": len(accepted),
        "substitutions": state["substitutions"],
        "accepted": accepted,
    }
    candidates_out.parent.mkdir(parents=True, exist_ok=True)
    with open(candidates_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    # Results-bundle copies, per the required artifact list.
    with open(out_dir / "frozen_olmo_answers.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(out_dir / "selected_tasks.json", "w", encoding="utf-8") as f:
        json.dump(selection, f, ensure_ascii=False, indent=1)

    env = capture_environment()
    with open(out_dir / "environment.json", "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)

    write_manifest(out_dir / "manifest_generation.json", {
        "n_slots": len(slot_ids_in_order), "n_accepted": len(accepted),
        "n_substitutions": len(state["substitutions"]),
        "candidates_path": str(candidates_out),
        "generator": payload["generator"],
        "generation_params": payload["generation_params"],
    })

    log(f"\n[done] {len(accepted)} accepted, {len(state['substitutions'])} substitutions")
    log(f"[save] {candidates_out}")
    log(f"[save] {out_dir / 'frozen_olmo_answers.json'}")
    log(f"[save] {out_dir / 'selected_tasks.json'}")
    log(f"[save] {out_dir / 'environment.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
