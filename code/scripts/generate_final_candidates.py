#!/usr/bin/env python3
"""Generate the 578 frozen Olmo-3-7B-Instruct candidate answers for the final behavioral
study (data/prompts/final_tasks_v2_english_seed20260817.json, sha256
a001d48b7769311da33cba1a8ef51bb4e9d1a27b2cc0d007bce85adab606037f). Writes into a
COMPLETELY NEW output directory (results/final_behavioral_study/) and never reads from or
writes into results/scaled_silent_influence[/_adjudicated] -- the completed 90-task run.

Same isolated model-input path as the 90-task run (silent_influence.exact_generation:
model loading kwargs, apply_chat_template call shape, seeding, decode settings), and the
same OLMo message split (build_olmo_messages: system = the single "producing the
response" sentence; the "no scratch work" instruction is appended to the user turn).

The ONE deliberate behavioral difference from generate_scaled_candidates.py, required by
the frozen collection_failure_policy (configs/final_analysis_plan.json
.collection_failure_policy.reserve_substitution_after_run_begins == false) and by
Amendment A1's "disable reserve substitution" implementation note: there is no reserve
list and no substitution path at all. A task that fails all MAX_RETRIES_PER_TASK attempts
is marked failed_permanently and contributes nothing; it is never replaced by a different
task. This reduces N for that task and N is reported, exactly as specified. A weak,
incorrect, refusing, unusually long, or token-capped answer remains a VALID, frozen
outcome, never regenerated or excluded.

Resumable: generation_state.json tracks, per task, its attempts and final status; a task
already "accepted" or "failed_permanently" is never re-attempted.

    python scripts/generate_final_candidates.py --dry-run
    python scripts/generate_final_candidates.py --stub          # no-GPU plumbing check
    python scripts/generate_final_candidates.py                  # real GPU run
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

from silent_influence import final_preflight_checks as fpc
from silent_influence import exact_generation as eg
from silent_influence.environment import capture_environment
from silent_influence.logging_utils import make_logger
from silent_influence.records import RecordWriter, write_manifest

MANIFEST_FILE = REPO / "data/prompts/final_tasks_v2_english_seed20260817.json"
MANIFEST_SHA256 = "a001d48b7769311da33cba1a8ef51bb4e9d1a27b2cc0d007bce85adab606037f"
OUT_DIR = REPO / "results/final_behavioral_study"
CANDIDATES_OUT = REPO / "data/candidates/final_olmo_answers.json"
STATE_FILE_NAME = "generation_state.json"

GENERATOR_SPEC = eg.ExactModelSpec(
    key="olmo3", hf_id="allenai/Olmo-3-7B-Instruct",
    revision="6e5971d9eba42665f5bd5a0fcf047f299ce1dccc", disable_thinking=False,
)
# Amendment A7: the generator runs at batch 6 in frozen manifest order --
# 578 = 96 full batches of 6 + one final partial batch of 2. The partial batch is an
# explicitly frozen part of the procedure, not an artefact to be padded away.
A7_GENERATOR_BATCH_SIZE = 6

MAX_NEW_TOKENS = 2048
GEN_SEED = 42
MAX_RETRIES_PER_TASK = 3  # genuine technical failures only; parse concerns do not apply here


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_manifest_hash(path: Path, expected_sha256: str) -> None:
    got = sha256_file(path)
    if got != expected_sha256:
        raise SystemExit(f"FROZEN ARTIFACT MISMATCH: {path} sha256={got} "
                         f"expected={expected_sha256}. Stopping; the manifest must not "
                         f"be regenerated or edited to make this pass.")


def is_technical_failure(text, err) -> bool:
    return err is not None or text is None or not text.strip()


def all_tasks(manifest: dict) -> list:
    """Flat list of every selected task across all three datasets, in manifest order."""
    out = []
    for ds_name, ds in manifest["datasets"].items():
        for t in ds["selected"]:
            out.append(t)
    return out


def task_key(t: dict) -> str:
    return f"{t['dataset']}:{t['source_task_id']}"


def load_state(path: Path, tasks: list) -> dict:
    """Merges rather than replaces: a prior run made with --limit (dev/smoke use) leaves
    a state file that only knows about the tasks it saw. Re-running against the full task
    list must not KeyError on the tasks that were never in that earlier slice -- every
    task in `tasks` gets a fresh 'pending' entry unless the state file already has one."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"tasks": {}}
    for t in tasks:
        state["tasks"].setdefault(task_key(t), {"attempts": [], "status": "pending"})
    return state


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


def attempt_generation_batch(loaded, tasks: list, stub: bool) -> list:
    """Amendment A7: one physical batch of up to A7_GENERATOR_BATCH_SIZE tasks, in frozen
    manifest order. The whole batch is generated in a single model.generate() call.

    On any exception the ENTIRE batch is reported as failed with the same error, because A7
    forbids retrying one member at a different batch size: the caller re-runs the identical
    batch composition or the run stops. Per-member records are still emitted individually so
    every task keeps its own logical record."""
    msgs_list = [eg.build_olmo_messages(t["question"]) for t in tasks]
    try:
        gen_fn = eg.generate_exact_batch_stub if stub else eg.generate_exact_batch
        results = gen_fn(loaded, msgs_list, max_new_tokens=MAX_NEW_TOKENS, seed=GEN_SEED)
        err, tb = None, None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc(limit=6)
        results = [{"text": None, "output_tokens": None, "hit_token_cap": False,
                    "generation_seconds": 0.0, "prompt_tokens": None,
                    "first_input_token_id": None, "last_input_token_id": None,
                    "emitted_terminator": None}
                   for _ in tasks]
    out = []
    for result in results:
        text = (result["text"] or "").strip()
        out.append({
            "text": text, "text_sha256": sha256_text(text) if text else None,
            "output_tokens": result.get("output_tokens"),
            "hit_token_cap": result.get("hit_token_cap"),
            "emitted_terminator": result.get("emitted_terminator"),
            "generation_seconds": result.get("generation_seconds", 0.0),
            "prompt_tokens": result.get("prompt_tokens"),
            "first_input_token_id": result.get("first_input_token_id"),
            "last_input_token_id": result.get("last_input_token_id"),
            "generation_error": err, "traceback": tb,
            "batch_size": len(tasks),
        })
    return out


def attempt_generation(loaded, task: dict, stub: bool) -> dict:
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
                    help="generate only the first N tasks (smoke/dev use)")
    ap.add_argument("--stub", action="store_true",
                    help="deterministic no-GPU stub for plumbing tests "
                         "(resume/retry/checkpoint) only; never a source of experimental "
                         "data")
    ap.add_argument("--manifest-file", default=str(MANIFEST_FILE))
    ap.add_argument("--skip-hash-check", action="store_true",
                    help="dev/test only -- bypass the frozen-manifest hash gate "
                         "(e.g. against a synthetic fixture)")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--candidates-out", default=str(CANDIDATES_OUT))
    args = ap.parse_args()

    # A stub run generates no real tokens. It must never be able to write the frozen
    # candidates file, which is a protected production target: a stub run of this script
    # previously filled it with 578 'stub response <hash>' answers. Fails closed before
    # any model is loaded.
    fpc.assert_stub_output_is_not_a_protected_dir(args.candidates_out, stub=args.stub,
                                                 repo_root=REPO)

    manifest_file = Path(args.manifest_file)
    out_dir = Path(args.out)
    candidates_out = Path(args.candidates_out)

    if not args.skip_hash_check:
        verify_manifest_hash(manifest_file, MANIFEST_SHA256)

    with open(manifest_file, encoding="utf-8") as f:
        manifest = json.load(f)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = make_logger(out_dir / "run.log")
    if not args.stub:
        eg.check_transformers_version(log)
    log(f"[generate_final_candidates] manifest={manifest_file} "
       f"n_tasks={manifest['n_selected_total']}")
    log(f"[generate_final_candidates] generator={GENERATOR_SPEC.hf_id} "
       f"rev={GENERATOR_SPEC.revision} max_new_tokens={MAX_NEW_TOKENS} seed={GEN_SEED} "
       f"reserve_substitution=DISABLED")

    all_manifest_tasks = all_tasks(manifest)
    tasks = all_manifest_tasks[:args.limit] if args.limit is not None else all_manifest_tasks
    log(f"[plan] {len(tasks)} tasks"
       + (f" (--limit applied; {len(all_manifest_tasks)} total in manifest)"
          if args.limit is not None else ""))

    if args.dry_run:
        for t in tasks[:5]:
            msgs = eg.build_olmo_messages(t["question"])
            log(f"  [{task_key(t)}] system={msgs[0]['content'][:80]}...")
            log(f"           user={msgs[1]['content'][:120]}...")
        log("[dry-run] nothing generated.")
        return 0

    state_path = out_dir / STATE_FILE_NAME
    # Always merge against the FULL manifest task list, not the --limit-truncated working
    # set: otherwise a later resume without --limit would KeyError on any task that was
    # never in an earlier --limit slice (dev/smoke use only; the real run never passes
    # --limit, but the state file must stay consistent regardless).
    state = load_state(state_path, all_manifest_tasks)
    rec_path = out_dir / "generation_records.jsonl"

    todo = [t for t in tasks if state["tasks"][task_key(t)]["status"] == "pending"]
    n_already = len(tasks) - len(todo)
    log(f"[resume] {n_already} tasks already resolved (accepted or permanently failed); "
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
                # A7: frozen manifest order, batch 6, final partial batch kept as-is.
                batches = [todo[k:k + A7_GENERATOR_BATCH_SIZE]
                           for k in range(0, len(todo), A7_GENERATOR_BATCH_SIZE)]
                n_full = sum(1 for b in batches if len(b) == A7_GENERATOR_BATCH_SIZE)
                n_partial = len(batches) - n_full
                log(f"[A7] {len(todo)} tasks -> {len(batches)} physical batches "
                    f"({n_full} full x {A7_GENERATOR_BATCH_SIZE}"
                    + (f" + {n_partial} partial of {len(batches[-1])}" if n_partial else "")
                    + ")")
                done = 0
                for bi, batch in enumerate(batches, 1):
                    # Whole-batch retry with identical composition and order (A7).
                    for attempt in range(1, MAX_RETRIES_PER_TASK + 1):
                        results = attempt_generation_batch(loaded, batch, args.stub)
                        fails = [is_technical_failure(r["text"], r["generation_error"])
                                 for r in results]
                        for t, result, technical_fail in zip(batch, results, fails):
                            writer.write({
                                "run_id": "final_behavioral_study_generation",
                                "timestamp": datetime.now(timezone.utc).isoformat(
                                    timespec="seconds"),
                                "dataset": t["dataset"],
                                "source_task_id": t["source_task_id"],
                                "attempt": attempt, "technical_failure": technical_fail,
                                "physical_batch_index": bi,
                                "physical_batch_size": len(batch),
                                "accepted": False,   # set retroactively below on success
                                **result,
                            })
                        call_raised = all(r["generation_error"] for r in results)
                        if not any(fails):
                            break
                        if call_raised and attempt == MAX_RETRIES_PER_TASK:
                            # A7: the identical batch was rerun to exhaustion and the call still
                            # raises. Marking all six members failed would punish batch-mates
                            # for an infrastructure fault, and retrying one member at batch 1 is
                            # forbidden. This is an irrecoverable technical error -> hard stop.
                            raise SystemExit(
                                f"HARD STOP (A7): batched generation call raised on every one "
                                f"of {MAX_RETRIES_PER_TASK} attempts for batch {bi}"
                                f"/{len(batches)} "
                                f"(tasks {[t['source_task_id'] for t in batch]}): "
                                f"{results[0]['generation_error']}. "
                                f"Resume reruns the identical batch once the cause is fixed.")
                        log(f"  [batch {bi}/{len(batches)}] attempt "
                            f"{attempt}/{MAX_RETRIES_PER_TASK}: "
                            f"{sum(fails)}/{len(batch)} technical failures -- rerunning the "
                            f"IDENTICAL batch (A7 forbids per-member retry at another size)")

                    for t, result, technical_fail in zip(batch, results, fails):
                        tk = task_key(t)
                        slot = state["tasks"][tk]
                        slot["attempts"].append({"technical_failure": technical_fail})
                        done += 1
                        if not technical_fail:
                            slot["status"] = "accepted"
                            flag = " TRUNCATED" if result["hit_token_cap"] else ""
                            log(f"  [{done}/{len(todo)}] b{bi} {tk} accepted "
                                f"{result['output_tokens']} tok{flag}")
                        else:
                            slot["status"] = "failed_permanently"
                            slot["failure_reason"] = (result["generation_error"] or
                                                      f"empty output after "
                                                      f"{MAX_RETRIES_PER_TASK} attempts")
                            log(f"  [{done}/{len(todo)}] b{bi} {tk} FAILED PERMANENTLY -- "
                                f"NOT substituted ({slot['failure_reason']})")
                    # Atomic commit: the whole batch's state lands together.
                    save_state(state_path, state)
        finally:
            eg.unload(loaded)

    # Rebuild the frozen candidates file from state + generation records (idempotent).
    all_records = []
    for line in open(rec_path, encoding="utf-8") if rec_path.exists() else []:
        line = line.strip()
        if line:
            all_records.append(json.loads(line))

    accepted, permanently_failed = [], []
    for t in tasks:
        tk = task_key(t)
        slot = state["tasks"][tk]
        if slot["status"] == "accepted":
            matches = [r for r in all_records
                      if r["dataset"] == t["dataset"]
                      and r["source_task_id"] == t["source_task_id"]
                      and not r["technical_failure"]]
            assert matches, f"{tk}: accepted but no successful record found"
            r = matches[-1]
            accepted.append({
                "dataset": t["dataset"], "source_task_id": t["source_task_id"],
                "category": t["category"], "question": t["question"],
                "question_sha256": t["question_sha256"],
                "previously_used": t.get("previously_used"),
                "prior_use_phases": t.get("prior_use_phases"),
                "answer": r["text"], "answer_sha256": r["text_sha256"],
                "output_tokens": r["output_tokens"], "hit_token_cap": r["hit_token_cap"],
                "generation_seconds": r["generation_seconds"],
                "generator_model": GENERATOR_SPEC.hf_id,
                "generator_revision": GENERATOR_SPEC.revision,
            })
        elif slot["status"] == "failed_permanently":
            permanently_failed.append({"dataset": t["dataset"],
                                       "source_task_id": t["source_task_id"],
                                       "reason": slot.get("failure_reason")})

    payload = {
        "generator": {"key": GENERATOR_SPEC.key, "hf_id": GENERATOR_SPEC.hf_id,
                     "revision": GENERATOR_SPEC.revision},
        "generation_params": {"do_sample": False, "max_new_tokens": MAX_NEW_TOKENS,
                              "pad_token_id": "tokenizer.eos_token_id"},
        "generation_seed": GEN_SEED,
        "manifest_path": str(manifest_file), "manifest_sha256": MANIFEST_SHA256,
        "selection_seed": manifest["selection_seed"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_tasks_total": len(tasks), "n_accepted": len(accepted),
        "n_permanently_failed": len(permanently_failed),
        "reserve_substitution": "disabled",
        "permanently_failed": permanently_failed,
        "accepted": accepted,
    }
    candidates_out.parent.mkdir(parents=True, exist_ok=True)
    with open(candidates_out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(out_dir / "frozen_olmo_answers.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with open(out_dir / "selected_tasks.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    env = capture_environment()
    with open(out_dir / "environment.json", "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)

    write_manifest(out_dir / "manifest_generation.json", {
        "n_tasks_total": len(tasks), "n_accepted": len(accepted),
        "n_permanently_failed": len(permanently_failed),
        "reserve_substitution": "disabled",
        "candidates_path": str(candidates_out),
        "generator": payload["generator"],
        "generation_params": payload["generation_params"],
    })

    log(f"\n[done] {len(accepted)} accepted, {len(permanently_failed)} permanently failed "
       f"(not substituted) of {len(tasks)} tasks")
    log(f"[save] {candidates_out}")
    log(f"[save] {out_dir / 'frozen_olmo_answers.json'}")
    log(f"[save] {out_dir / 'selected_tasks.json'}")
    log(f"[save] {out_dir / 'environment.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
