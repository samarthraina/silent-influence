"""Persistence and resume guarantees."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from silent_influence.records import (UNIT_KEY_FIELDS, RecordWriter,  # noqa: E402
                                      count_truncated, derive_seed, load_completed,
                                      load_records, repair_truncated_tail, unit_id)

KEY = {f: "x" for f in UNIT_KEY_FIELDS}


def _key(**over):
    k = dict(KEY)
    k.update(over)
    return k


def test_unit_id_depends_on_every_key_field():
    base = unit_id(_key())
    for f in UNIT_KEY_FIELDS:
        assert unit_id(_key(**{f: "different"})) != base, f"unit_id ignores {f}"


def test_unit_id_is_order_independent_and_stable():
    a = unit_id(_key())
    b = unit_id({f: KEY[f] for f in reversed(UNIT_KEY_FIELDS)})
    assert a == b == unit_id(_key())


def test_unit_id_ignores_non_key_fields():
    assert unit_id({**KEY, "timestamp": "now", "raw_output": "zzz"}) == unit_id(_key())


def test_no_history_and_score_conditions_get_different_ids():
    a = unit_id(_key(prior_context_condition="no_history", prior_score_value=None))
    b = unit_id(_key(prior_context_condition="score_5", prior_score_value=5))
    assert a != b


def test_seed_is_deterministic_and_id_dependent():
    assert derive_seed(42, "abc") == derive_seed(42, "abc")
    assert derive_seed(42, "abc") != derive_seed(42, "abd")
    assert derive_seed(42, "abc") != derive_seed(43, "abc")


def test_writer_appends_and_completed_round_trips(tmp_path):
    p = tmp_path / "records.jsonl"
    with RecordWriter(p) as w:
        for i in range(5):
            k = _key(replicate=i)
            w.write({"unit_id": unit_id(k), **k})
    assert len(load_records(p)) == 5
    assert len(load_completed(p)) == 5


def test_truncated_tail_is_repaired_not_glued(tmp_path):
    """A crash mid-write must cost one record, never two."""
    p = tmp_path / "records.jsonl"
    with RecordWriter(p) as w:
        for i in range(3):
            k = _key(replicate=i)
            w.write({"unit_id": unit_id(k), **k})
    raw = p.read_text(encoding="utf-8")
    p.write_text(raw[:len(raw) - 30], encoding="utf-8")   # simulate the crash
    assert count_truncated(p) == 1

    with RecordWriter(p) as w:                            # repairs on open
        k = _key(replicate=2)
        w.write({"unit_id": unit_id(k), **k})

    assert count_truncated(p) == 0
    recs = load_records(p)
    assert len(recs) == 3
    assert len({r["unit_id"] for r in recs}) == 3


def test_repair_is_idempotent_on_a_healthy_file(tmp_path):
    p = tmp_path / "records.jsonl"
    with RecordWriter(p) as w:
        w.write({"unit_id": unit_id(_key()), **_key()})
    size = p.stat().st_size
    assert repair_truncated_tail(p) == 0
    assert p.stat().st_size == size


def test_repair_on_missing_or_empty_file(tmp_path):
    assert repair_truncated_tail(tmp_path / "nope.jsonl") == 0
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert repair_truncated_tail(empty) == 0


def test_load_completed_skips_unparseable_so_the_unit_is_rerun(tmp_path):
    p = tmp_path / "records.jsonl"
    good = {"unit_id": unit_id(_key()), **_key()}
    p.write_text(json.dumps(good) + "\n" + '{"unit_id": "half', encoding="utf-8")
    assert load_completed(p) == {good["unit_id"]}
