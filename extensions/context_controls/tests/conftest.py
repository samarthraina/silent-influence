import json
import sys
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXT / "src"))
ART = EXT / "artifacts"


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


@pytest.fixture(scope="session")
def sample():
    return json.loads((ART / "sample/sample_manifest_v1.json").read_text())


@pytest.fixture(scope="session")
def tasks():
    from rba import inputs as I
    return {f"{x['dataset']}/{x['source_task_id']}": x for x in I.load_json("answers")["accepted"]}


@pytest.fixture(scope="session")
def frozen_by_unit(sample):
    """Frozen original records for the sampled tasks (local-only test input)."""
    from rba import inputs as I
    ids = {r["base_task_id"] for r in sample["selected"]}
    out = {}
    for r in I.iter_jsonl("merged_raw"):
        if f"{r['dataset']}/{r['source_task_id']}" in ids:
            out[r["unit_id"]] = r
    return out


@pytest.fixture(scope="session")
def calib_units():
    return read_jsonl(ART / "calibration/run_manifest_v1.jsonl")
