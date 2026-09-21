"""Candidate responses being judged.

Held fixed across every prior-score condition — the manipulation must not co-vary with the
text under evaluation. Candidates are pinned to a file so a rerun scores identical bytes.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Candidate:
    dataset: str
    prompt_id: str
    candidate_response_id: str
    evaluated_model: str
    text: str


def load_candidates(path: Path) -> List[Candidate]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for r in raw["candidates"]:
        out.append(Candidate(
            dataset=str(r["dataset"]),
            prompt_id=str(r["prompt_id"]),
            candidate_response_id=str(r["candidate_response_id"]),
            evaluated_model=str(r["evaluated_model"]),
            text=str(r["text"]),
        ))
    return out


def index(cands: List[Candidate]) -> Dict[tuple, List[Candidate]]:
    ix: Dict[tuple, List[Candidate]] = defaultdict(list)
    for c in cands:
        ix[(c.dataset, c.prompt_id)].append(c)
    for k in ix:
        ix[k].sort(key=lambda c: (c.evaluated_model, c.candidate_response_id))
    return ix


def select(ix: Dict[tuple, List[Candidate]], dataset: str, prompt_id: str,
           evaluated_models: Optional[List[str]],
           per_prompt: Optional[int]) -> List[Candidate]:
    got = ix.get((dataset, prompt_id), [])
    if evaluated_models:
        got = [c for c in got if c.evaluated_model in evaluated_models]
    return got[:per_prompt] if per_prompt else got
