#!/usr/bin/env python3
"""Pin candidate responses into this repo so a rerun scores identical bytes.

Reads a legacy generation checkpoint (read-only) and writes a self-contained candidates
file. The legacy tree is never modified.

    python scripts/pin_candidates.py \
        --generation-checkpoint <legacy>/checkpoints/generation_complete.json \
        --dataset arena_hard_v2 --temperature 0.3 --run-idx 0 \
        --out data/candidates/pinned_candidates_v1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generation-checkpoint", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--temperature", default="0.3")
    ap.add_argument("--run-idx", type=int, default=0)
    ap.add_argument("--models", nargs="*", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.generation_checkpoint, encoding="utf-8") as f:
        gen = json.load(f)
    if args.temperature not in gen:
        raise SystemExit(f"temperature {args.temperature!r} not in checkpoint "
                         f"(have {sorted(gen)})")

    out = []
    for entry in gen[args.temperature]:
        pid = str(entry["prompt_id"])
        for model, runs in entry.get("responses", {}).items():
            if args.models and model not in args.models:
                continue
            if len(runs) <= args.run_idx or not runs[args.run_idx]:
                continue
            text = runs[args.run_idx]
            out.append({
                "dataset": args.dataset,
                "prompt_id": pid,
                "candidate_response_id": f"{model}_r{args.run_idx}",
                "evaluated_model": model,
                "text": text,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
            })

    payload = {
        "source": str(Path(args.generation_checkpoint).resolve()),
        "source_note": "legacy SSI generation checkpoint, read-only",
        "dataset": args.dataset,
        "generation_temperature": args.temperature,
        "run_idx": args.run_idx,
        "pinned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_candidates": len(out),
        "candidates": out,
    }
    p = Path(args.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    models = sorted({c["evaluated_model"] for c in out})
    prompts = sorted({c["prompt_id"] for c in out}, key=lambda x: int(x))
    print(f"wrote {len(out)} candidates -> {p}")
    print(f"  models: {models}")
    print(f"  prompts: {len(prompts)} ({prompts[0]}..{prompts[-1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
