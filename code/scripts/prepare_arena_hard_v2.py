#!/usr/bin/env python3
"""Download and pin a fresh Arena-Hard-v2 prompt pool into data/prompts/.

Companion to prepare_dataset.py, which only pins mtbench_t1 / wildbench_v2 / alpaca_eval
(all via huggingface_hub). Arena-Hard-v2 is not on HuggingFace for this project: the
existing data/prompts/arena_hard_v2_30_seed42.json was pinned from a *legacy* generation
checkpoint (see scripts/pin_candidates.py) and carries no source_repo/source_revision
metadata, and all 30 of its prompts are already consumed by earlier phases. This script
pulls the same upstream source (lmarena/arena-hard-auto, data/arena-hard-v2.0/question.jsonl)
fresh, pinned to a resolved commit SHA (the upstream repo has no tagged release for this
file; "main" is resolved to a commit at fetch time and recorded), so a bigger, freshly
addressable pool exists for scaled sampling.

Structural exclusion mirrors the convention already used for the original 30-prompt draw:
prompts longer than 3000 characters are dropped as not answerable within the standardized
2048-token generation budget (61 of 750 in the upstream file, confirmed at fetch time).

    python scripts/prepare_arena_hard_v2.py
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone

import requests

from _bootstrap import REPO

REPO_SLUG = "lmarena/arena-hard-auto"
SOURCE_FILE = "data/arena-hard-v2.0/question.jsonl"
OUT = REPO / "data/prompts/arena_hard_v2_pinned_v2.json"
MAX_PROMPT_CHARS = 3000  # matches the exclusion rule used for arena_hard_v2_30_seed42.json


def main() -> int:
    commit = requests.get(
        f"https://api.github.com/repos/{REPO_SLUG}/commits/main", timeout=30
    ).json()
    resolved_sha = commit["sha"]

    raw_url = f"https://raw.githubusercontent.com/{REPO_SLUG}/{resolved_sha}/{SOURCE_FILE}"
    resp = requests.get(raw_url, timeout=60)
    resp.raise_for_status()
    raw_bytes = resp.content
    file_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    rows, skipped = [], []
    for i, line in enumerate(raw_bytes.decode("utf-8").split("\n")):
        if not line.strip():
            continue
        r = json.loads(line)
        text = r["prompt"]
        if len(text) > MAX_PROMPT_CHARS:
            skipped.append({"prompt_id": r["uid"], "category": r.get("subcategory"),
                            "reason": f"prompt {len(text)} chars > {MAX_PROMPT_CHARS}: "
                                     f"not answerable within the standardized budget"})
            continue
        rows.append({"prompt_id": r["uid"], "uid": r["uid"],
                     "category": r.get("category"), "subcategory": r.get("subcategory"),
                     "prompt": text, "char_length": len(text)})

    payload = {
        "dataset": "arena_hard_v2",
        "source_repo": REPO_SLUG,
        "source_file": SOURCE_FILE,
        "source_revision": resolved_sha,
        "source_revision_resolved_from": "main",
        "source_revision_resolved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_file_sha256": file_sha256,
        "license": "apache-2.0",
        "note": ("Arena-Hard-v2, full upstream pool (superset of the 30-prompt draw in "
                "arena_hard_v2_30_seed42.json, which is a disjoint legacy artifact and "
                "is NOT reused here). Prompts >3000 chars excluded as structurally "
                "unanswerable within the standardized generation budget."),
        "pinned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_prompts": len(rows),
        "excluded": skipped,
        "categories": dict(sorted(Counter(r["subcategory"] for r in rows).items())),
        "prompts": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print(f"arena_hard_v2: {len(rows)} prompts -> {OUT}")
    print(f"  source     : {REPO_SLUG} @ {resolved_sha[:12]} (resolved from main) :: {SOURCE_FILE}")
    print(f"  file sha256: {file_sha256[:16]}")
    print(f"  license    : apache-2.0")
    print(f"  categories : {payload['categories']}")
    print(f"  excluded   : {len(skipped)} entries (>{MAX_PROMPT_CHARS} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
