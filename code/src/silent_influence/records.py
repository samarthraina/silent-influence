"""Draw-level persistence.

One JSONL line per experimental unit, appended and fsync'd immediately. Nothing is
aggregated at write time: every aggregate in this project is derived, and the legacy
pipeline's worst data loss came from an aggregation that dropped a condition key.

A crash can leave one truncated final line; `load_completed` tolerates exactly that and
reports it rather than failing.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Set, Tuple

# The fields that identify a cell. Two runs agreeing on all of these are the same unit.
UNIT_KEY_FIELDS: Tuple[str, ...] = (
    "dataset",
    "prompt_id",
    "candidate_response_id",
    "judge_model",
    "evaluated_model",
    "prior_context_condition",
    "prior_score_value",
    "rubric_variant",
    "output_protocol",
    "history_template",
    "backend",
    # Changes what the model actually receives (e.g. Qwen3 enable_thinking pre-fills an
    # empty <think></think>), so it must partition units or a resume would silently mix
    # records taken under different template settings.
    "chat_template_kwargs",
    "replicate",
)


def unit_id(key: Dict[str, Any]) -> str:
    missing = [f for f in UNIT_KEY_FIELDS if f not in key]
    if missing:
        raise KeyError(f"unit key missing fields: {missing}")
    canon = json.dumps({f: key[f] for f in UNIT_KEY_FIELDS},
                       sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]


def derive_seed(base_seed: int, uid: str) -> int:
    """Per-unit seed derived from the unit identity, so a rerun of one cell reproduces."""
    h = hashlib.sha256(f"{base_seed}:{uid}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def repair_truncated_tail(path: Path) -> int:
    """Drop an incomplete trailing record so the next append cannot be glued onto it.

    Without this, a crash mid-write costs two records rather than one: the partial line
    has no terminator, so the next append concatenates onto it and both become garbage.
    Returns the number of bytes discarded.
    """
    if not path.exists() or path.stat().st_size == 0:
        return 0
    data = path.read_bytes()
    cut = data.rfind(b"\n") + 1  # keep only whole, newline-terminated lines
    body = data[:cut]
    while body:
        last_nl = body.rfind(b"\n", 0, len(body) - 1) + 1
        try:
            json.loads(body[last_nl:].decode("utf-8"))
            break
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = body[:last_nl]
    if len(body) != len(data):
        with open(path, "r+b") as f:
            f.truncate(len(body))
            f.flush()
            os.fsync(f.fileno())
    return len(data) - len(body)


@dataclass
class RecordWriter:
    path: Path

    def __post_init__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        dropped = repair_truncated_tail(self.path)
        if dropped:
            print(f"[records] discarded {dropped} bytes of an incomplete trailing "
                  f"record in {self.path.name}; that unit will be re-run")
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")

    def write(self, record: Dict[str, Any]) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def iter_records(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                yield json.loads(ln)
            except json.JSONDecodeError:
                continue  # truncated tail from an interrupted write


def load_records(path: Path) -> List[Dict[str, Any]]:
    return list(iter_records(path))


def load_completed(path: Path) -> Set[str]:
    return {r["unit_id"] for r in iter_records(path) if "unit_id" in r}


def count_truncated(path: Path) -> int:
    if not path.exists():
        return 0
    bad = 0
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                try:
                    json.loads(ln)
                except json.JSONDecodeError:
                    bad += 1
    return bad


def write_manifest(path: Path, manifest: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on Windows and POSIX
