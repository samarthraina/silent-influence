"""Dataset-agnostic prompt loading.

A dataset is a config entry, never a code path. Adding a source means adding a YAML block
with a field mapping, not editing this module.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PromptRow:
    dataset: str
    prompt_id: str
    text: str
    category: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


def _read_records(path: Path, fmt: str) -> List[Dict]:
    if fmt == "json_list":
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if fmt == "jsonl":
        with open(path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]
    if fmt == "pinned_json":            # written by scripts/prepare_dataset.py
        with open(path, encoding="utf-8") as f:
            return json.load(f)["prompts"]
    raise ValueError(f"unknown dataset format {fmt!r} "
                     f"(json_list | jsonl | pinned_json)")


def load_dataset(name: str, spec: Dict, root: Path) -> List[PromptRow]:
    path = (root / spec["path"]).resolve()
    if not path.exists():
        raise FileNotFoundError(f"dataset {name!r}: {path} not found")
    fields = spec.get("fields", {})
    id_f = fields.get("id", "prompt_id")
    text_f = fields.get("text", "prompt")
    cat_f = fields.get("category")

    rows = []
    for i, r in enumerate(_read_records(path, spec.get("format", "json_list"))):
        text = r.get(text_f)
        if not text or not str(text).strip():
            continue
        rows.append(PromptRow(
            dataset=name,
            prompt_id=str(r.get(id_f, i)),
            text=str(text),
            category=str(r[cat_f]) if cat_f and r.get(cat_f) is not None else None,
            meta={k: v for k, v in r.items() if k not in {text_f}},
        ))
    return rows


def sample(rows: List[PromptRow], n: Optional[int], seed: int,
           stratify: bool = True) -> List[PromptRow]:
    """Deterministic sample. Stratified by category when every row carries one."""
    if n is None or n >= len(rows):
        return sorted(rows, key=lambda r: r.prompt_id)
    rng = random.Random(seed)
    if stratify and all(r.category for r in rows):
        by_cat: Dict[str, List[PromptRow]] = defaultdict(list)
        for r in rows:
            by_cat[r.category].append(r)
        cats = sorted(by_cat)
        picked: List[PromptRow] = []
        # round-robin so the sample stays balanced when n is not a multiple of |cats|
        pools = {c: rng.sample(by_cat[c], len(by_cat[c])) for c in cats}
        while len(picked) < n:
            progressed = False
            for c in cats:
                if pools[c] and len(picked) < n:
                    picked.append(pools[c].pop())
                    progressed = True
            if not progressed:
                break
        return sorted(picked, key=lambda r: r.prompt_id)
    return sorted(rng.sample(rows, n), key=lambda r: r.prompt_id)
