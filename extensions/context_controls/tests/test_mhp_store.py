"""Recovery of interrupted patching runs: quarantine only an incomplete trailing record,
reject other corruption, never modify the original file, never duplicate completed units."""
import hashlib
import json
from pathlib import Path

import pytest

from conftest import EXT
from rba import mhp as M, mhp_store as MS

REC = EXT / "results/raw/study_llama/attempts.jsonl"


def _rec(u, i=0, status="accepted", payload=None):
    p = payload or {"x": u}
    return {"unit_id": u, "attempt_index": i, "status": status, "payload": p,
            "payload_sha256": MS.payload_sha(p), "recorded_utc": "t"}


def _write(d, recs, tail=b""):
    d.mkdir(parents=True, exist_ok=True)
    data = b"".join((MS.canon(r) + "\n").encode() for r in recs) + tail
    (d / "attempts.jsonl").write_bytes(data)
    return data


def test_incomplete_trailing_record_quarantined_original_unchanged(tmp_path):
    data = _write(tmp_path, [_rec("a"), _rec("b")], tail=b'{"unit_id": "c", "attempt_in')
    w = MS.Writer(tmp_path)
    assert w.final == {"a", "b"} and len(w.quarantined) == 1
    q = w.quarantined[0]
    assert q["line"] == 3 and q["sha256"] == hashlib.sha256(b'{"unit_id": "c", "attempt_in').hexdigest()
    w.append("c", "accepted", {"x": "c"}, "t")
    w.close()
    assert (tmp_path / "attempts.jsonl").read_bytes() == data          # untouched
    assert (tmp_path / "attempts.seg0001.jsonl").exists()
    assert (tmp_path / "quarantine_report_seg0001.json").exists()
    recs, quar = MS.load(tmp_path)
    assert [r["unit_id"] for r in recs] == ["a", "b", "c"] and len(quar) == 1


def test_complete_last_line_without_newline_is_quarantined_not_trusted(tmp_path):
    _write(tmp_path, [_rec("a")], tail=MS.canon(_rec("b")).encode())
    recs, quar = MS.load(tmp_path)
    assert [r["unit_id"] for r in recs] == ["a"] and quar[0]["reason"] == "no terminating newline"


@pytest.mark.parametrize("bad", ["interior", "hash", "index", "after_final"])
def test_other_corruption_rejected(tmp_path, bad):
    recs = [_rec("a"), _rec("b")]
    if bad == "interior":
        data = (MS.canon(recs[0]) + "\n{broken\n" + MS.canon(recs[1]) + "\n").encode()
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "attempts.jsonl").write_bytes(data)
    elif bad == "hash":
        r = dict(recs[1], payload={"x": "tampered"})
        _write(tmp_path, [recs[0], r])
    elif bad == "index":
        _write(tmp_path, [recs[0], _rec("b", i=1)])
    else:
        _write(tmp_path, [recs[0], _rec("a", i=1)])
    with pytest.raises(MS.StoreCorruption):
        MS.load(tmp_path)


def test_resume_never_duplicates_and_segments_accumulate(tmp_path):
    _write(tmp_path, [_rec("a"), _rec("b", status="technical_failure")])
    w = MS.Writer(tmp_path)
    with pytest.raises(MS.StoreCorruption):
        w.append("a", "accepted", {"x": 1}, "t")
    w.append("b", "accepted", {"x": "b2"}, "t")
    w.close()
    w2 = MS.Writer(tmp_path)
    assert w2.final == {"a", "b"} and w2.path.name == "attempts.seg0002.jsonl"
    recs, _ = MS.load(tmp_path)
    assert [(r["unit_id"], r["attempt_index"]) for r in recs] == [("a", 0), ("b", 0), ("b", 1)]


def test_recovered_llama_file_and_resume_load_cleanly():
    assert len(REC.read_text().splitlines()) == 628
    recs, quar = MS.load(REC.parent)
    assert quar == [] and len(recs) == 720
    man = [json.loads(l) for l in open(EXT / "matched_history_patching/mhp_manifest_v1.jsonl")]
    assert {r["unit_id"] for r in recs} == {u["unit_id"] for u in man}


def test_inclusive_small_gap_threshold_keeps_exact_one():
    s = {("a", "baseline:self_high_10"): 8.0, ("a", "baseline:self_low_2"): 7.0,
         ("b", "baseline:self_high_10"): 8.0, ("b", "baseline:self_low_2"): 7.5}
    for t in ("a", "b"):
        s[(t, "patch:L24:self_high_10->self_low_2")] = s[(t, "baseline:self_low_2")]
    r = M.analyze(s, ["a", "b"], min_gap=1.0)["self_high_10->self_low_2"]["L24"]
    assert r["normalized_n"] == 1 and r["small_gap_excluded"] == 1     # gap 1.0 kept, 0.5 out
