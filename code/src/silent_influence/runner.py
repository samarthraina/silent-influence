"""Resumable executor.

Units are grouped by judge model so each model loads once. A unit already present in the
records file is skipped, so rerunning the same command is a no-op on completed work.
Records are written whether or not parsing succeeded — a failed parse is data.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import backends, parsing, protocols, render, templates
from .conditions import resolve as resolve_condition
from .grid import Plan, UnitSpec
from .records import RecordWriter, load_completed, write_manifest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def render_for(plan: Plan, u: UnitSpec, *, score_sentinel: bool = False):
    row = plan.prompts[(u.dataset, u.prompt_id)]
    c = plan.candidates[(u.dataset, u.prompt_id, u.candidate_response_id)]
    return render.render(
        question=row.text,
        candidate_response=c.text,
        prior=resolve_condition(u.prior_context_condition),
        rubric_variant=u.rubric_variant,
        output_protocol=u.output_protocol,
        history_template=u.history_template,
        evaluated_label=c.evaluated_model,
        score_sentinel=score_sentinel,
    )


def run(plan: Plan, out_dir: Path, *, resume: bool = True,
        limit: Optional[int] = None,
        log: Callable[[str], None] = print) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "records.jsonl"

    done = load_completed(records_path) if resume else set()
    todo = [u for u in plan.units if u.uid not in done]
    if limit is not None:
        todo = todo[:limit]

    log(f"[plan] {len(plan.units)} units | {len(done)} already complete | "
        f"{len(todo)} to run")

    by_model: Dict[str, List[UnitSpec]] = {}
    for u in todo:
        by_model.setdefault(u.judge_model, []).append(u)

    stats = {"attempted": 0, "written": 0, "parse_ok": 0, "parse_fail": 0,
             "errors": 0, "skipped_existing": len(done),
             "by_status": {}, "model_identities": {}}
    t0 = time.time()

    with RecordWriter(records_path) as writer:
        for model_key, units in by_model.items():
            spec = plan.models[model_key]
            log(f"[model] loading {model_key} ({spec.backend}:{spec.hf_id}) "
                f"for {len(units)} units")
            backend = backends.build(spec)
            identity = backend.identity()
            stats["model_identities"][model_key] = identity
            try:
                for i, u in enumerate(units, 1):
                    prompt = render_for(plan, u)
                    seed = plan.seed_for(u)
                    proto = protocols.resolve(u.output_protocol)
                    if spec.backend == "stub":
                        spec.extra["_protocol_fields"] = list(proto.fields)

                    raw, err, tb = None, None, None
                    t1 = time.time()
                    try:
                        raw = backend.generate(prompt.system, prompt.user,
                                               plan.gen_params, seed)
                    except Exception as e:                    # keep the cell, log the failure
                        err = f"{type(e).__name__}: {e}"
                        tb = traceback.format_exc(limit=6)
                        stats["errors"] += 1
                    gen_s = time.time() - t1

                    pr = (parsing.parse(raw, proto.wants_justification)
                          if raw is not None
                          else parsing.ParseResult(parsing.EMPTY_OUTPUT,
                                                   error="generation failed"))

                    rec = {
                        "unit_id": u.uid,
                        "run_id": plan.run_id,
                        "timestamp": _now(),
                        **u.key(),
                        "seed": seed,
                        "base_seed": plan.base_seed,
                        "system_prompt": prompt.system,
                        "user_prompt": prompt.user,
                        "raw_output": raw,
                        "parse_status": pr.status,
                        "parse_error": pr.error,
                        "relevance": pr.relevance,
                        "reasoning_quality": pr.reasoning_quality,
                        "total": pr.total,
                        "justification": pr.justification,
                        "generation_error": err,
                        "generation_traceback": tb,
                        "generation_seconds": round(gen_s, 3),
                        "generation_params": plan.gen_params.as_dict(),
                        "model_identity": identity,
                    }
                    writer.write(rec)
                    stats["attempted"] += 1
                    stats["written"] += 1
                    stats["by_status"][pr.status] = stats["by_status"].get(pr.status, 0) + 1
                    if pr.ok:
                        stats["parse_ok"] += 1
                    else:
                        stats["parse_fail"] += 1
                    if i % 25 == 0 or i == len(units):
                        log(f"  [{model_key}] {i}/{len(units)} "
                            f"({stats['parse_ok']} parsed ok)")
            finally:
                backend.close()

    stats["wall_seconds"] = round(time.time() - t0, 2)
    manifest = {
        "run_id": plan.run_id,
        "timestamp": _now(),
        "records_path": str(records_path),
        "n_units_planned": len(plan.units),
        "n_units_run": len(todo),
        "resume": resume,
        "base_seed": plan.base_seed,
        "generation_params": plan.gen_params.as_dict(),
        "history_template": {
            name: templates.resolve(name)
            for name in {u.history_template for u in plan.units}
        },
        "system_prompt": render.SYSTEM_PROMPT,
        "answer_label": render.ANSWER_LABEL,
        "instruction": render.INSTRUCTION,
        "stats": stats,
        "config": plan.config,
    }
    write_manifest(out_dir / f"manifest_{plan.run_id}.json", manifest)
    log(f"[done] {stats['written']} records in {stats['wall_seconds']}s "
        f"-> {records_path}")
    return stats
