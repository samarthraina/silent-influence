#!/usr/bin/env python3
"""Download and pin an evaluation dataset into data/prompts/.

Pinning matters for the same reason judge revisions are pinned: the task set is
experimental input, and an upstream edit must not silently change it. Each output file
records the source repo, the file, its sha256, and any exclusions.

Flattening happens here rather than in the loader, so datasets.py stays a plain
field-mapping reader and every dataset on disk has the same shape.

    python scripts/prepare_dataset.py --dataset mtbench_t1
    python scripts/prepare_dataset.py --dataset alpaca_eval
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

# MT-Bench first turn. 131 and 138 are excluded because the task itself asks the model to
# emit numeric ratings, which would collide with the injected prior score later.
MTBENCH_EXCLUDE = {131, 138}

# WildBench v2 structural eligibility. Every rule below is a property of the task, fixed
# before any judging, and none depends on the answer Model X produces.
#
# MAX_PROMPT_CHARS: a 2048-token answer to a longer specification is structurally unlikely
# to be complete, so those tasks cannot meet the standardized response budget.
# MAX_REQUESTED_WORDS: an explicit demand for more words than the budget can hold.
WILDBENCH_MAX_PROMPT_CHARS = 6000
WILDBENCH_MAX_REQUESTED_WORDS = 1200

# Read individually, not matched by pattern: a keyword screen over the single-turn set
# produced candidates, each was read, and only these genuinely violate a structural rule.
# Six of nine "image" hits were self-contained coding/writing tasks that merely mention
# images and are therefore kept.
WILDBENCH_READ_EXCLUSIONS = {
    "1f62b28d7ae44f58": "references an image not supplied ('The image above shows the first 1600 differences')",
    "051987cb599849c2": "requires an image not supplied (Einstein caricature)",
    "fef5e14da329425c": "requires real, working external links (live web access)",
    "2162306e918d4f31": "primary output is itself a numeric rating ('Rate his plan from 1-100')",
}

SOURCES = {
    "mtbench_t1": {
        "repo": "HuggingFaceH4/mt_bench_prompts",
        "file": "raw/question.jsonl",
        "license": "apache-2.0",
        "out": "data/prompts/mtbench_t1_pinned.json",
        "note": "MT-Bench, first turn only (prompt[0]); 2-turn items flattened",
    },
    "wildbench_v2": {
        "repo": "allenai/WildBench",
        "file": "v2/test-00000-of-00001.parquet",
        "license": "see dataset card (allenai/WildBench)",
        "out": "data/prompts/wildbench_v2_pinned.json",
        "note": "WildBench v2, single-turn entries only; structural eligibility filters applied",
    },
    "alpaca_eval": {
        "repo": "tatsu-lab/alpaca_eval",
        "file": "alpaca_eval.json",
        "license": "cc-by-nc-4.0",
        "out": "data/prompts/alpaca_eval_pinned.json",
        "note": "AlpacaEval instructions; single-turn, self-contained",
    },
}


def _load_mtbench(path: Path):
    rows, skipped = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            qid = int(r["question_id"])
            if qid in MTBENCH_EXCLUDE:
                skipped.append({"prompt_id": str(qid), "category": r["category"],
                                "reason": "task asks for numeric rating output"})
                continue
            turns = r["prompt"]
            rows.append({"prompt_id": str(qid),
                         "prompt": turns[0],
                         "subcategory": r["category"],
                         "n_turns_in_source": len(turns)})
    return rows, skipped


def _load_alpaca(path: Path):
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    rows = [{"prompt_id": str(i),
             "prompt": r["instruction"],
             "subcategory": r.get("dataset") or "unknown"}
            for i, r in enumerate(raw)]
    return rows, []


def _load_wildbench(path: Path):
    """Single-turn WildBench v2 entries that meet the structural eligibility rules."""
    import re

    import pyarrow.parquet as pq

    rows, skipped = [], []
    for r in pq.read_table(path).to_pylist():
        rid, tag = r["id"], r["primary_tag"]

        def drop(reason):
            skipped.append({"prompt_id": rid, "category": tag, "reason": reason})

        if r["length"] != 1:
            drop(f"multi-turn ({r['length']} turns): depends on earlier dialogue")
            continue
        turn = r["conversation_input"][0]
        if turn.get("role") != "user":
            drop(f"single turn has role={turn.get('role')!r}, not user")
            continue
        text = turn["content"]
        if rid in WILDBENCH_READ_EXCLUSIONS:
            drop(WILDBENCH_READ_EXCLUSIONS[rid])
            continue
        if len(text) > WILDBENCH_MAX_PROMPT_CHARS:
            drop(f"prompt {len(text)} chars > {WILDBENCH_MAX_PROMPT_CHARS}: "
                 f"not answerable within the standardized budget")
            continue
        asks = [int(m) for m in re.findall(r"(\d{3,5})\s*words", text, re.I)]
        if asks and max(asks) > WILDBENCH_MAX_REQUESTED_WORDS:
            drop(f"explicitly requests {max(asks)} words > {WILDBENCH_MAX_REQUESTED_WORDS}: "
                 f"exceeds the standardized response budget")
            continue
        rows.append({"prompt_id": rid, "prompt": text, "subcategory": tag,
                     "secondary_tags": r.get("secondary_tags") or [],
                     "prompt_chars": len(text)})
    return rows, skipped


LOADERS = {"mtbench_t1": _load_mtbench, "alpaca_eval": _load_alpaca,
           "wildbench_v2": _load_wildbench}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=sorted(SOURCES))
    args = ap.parse_args()

    from huggingface_hub import HfApi, hf_hub_download
    spec = SOURCES[args.dataset]
    api = HfApi()
    info = api.dataset_info(spec["repo"])
    local = Path(hf_hub_download(spec["repo"], spec["file"],
                                 repo_type="dataset", revision=info.sha))
    sha = hashlib.sha256(local.read_bytes()).hexdigest()

    rows, skipped = LOADERS[args.dataset](local)
    from collections import Counter
    payload = {
        "dataset": args.dataset,
        "source_repo": spec["repo"],
        "source_file": spec["file"],
        "source_revision": info.sha,
        "source_file_sha256": sha,
        "license": spec["license"],
        "note": spec["note"],
        "pinned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_prompts": len(rows),
        "excluded": skipped,
        "categories": dict(sorted(Counter(r["subcategory"] for r in rows).items())),
        "prompts": rows,
    }
    out = REPO / spec["out"]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print(f"{args.dataset}: {len(rows)} prompts -> {out}")
    print(f"  source     : {spec['repo']} @ {info.sha[:12]} :: {spec['file']}")
    print(f"  file sha256: {sha[:16]}")
    print(f"  license    : {spec['license']}")
    print(f"  categories : {payload['categories']}")
    if skipped:
        from collections import Counter as _C
        reasons = _C(s["reason"].split(":")[0].split("(")[0].strip() for s in skipped)
        print(f"  EXCLUDED   : {len(skipped)} entries")
        for why, n in reasons.most_common():
            print(f"               {n:>5}  {why}")
    L = sorted(len(r["prompt"]) for r in rows)
    print(f"  prompt chars: min {L[0]} / median {L[len(L)//2]} / max {L[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
