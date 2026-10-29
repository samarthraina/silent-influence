"""CLI entry point for the calibration run. BLOCKED until every required execution gate is
confirmed with evidence in artifacts/EXECUTION_GATES_v1.json; the gate check runs first,
before the manifest, ledger, backend or any model import.

  python -B scripts/run_calibration.py --ledger <path> --store <dir> \
      --stage-cap-hours H --projected-unit-seconds S --unit-timeout-seconds T
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXT / "src"))
from rba import gates as G  # noqa: E402

GATES = EXT / "artifacts/EXECUTION_GATES_v1.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--stage-cap-hours", type=float, required=True)
    ap.add_argument("--projected-unit-seconds", type=float, required=True)
    ap.add_argument("--unit-timeout-seconds", type=float, required=True)
    ap.add_argument("--stage", default=None)
    a = ap.parse_args(argv)
    try:
        G.require(GATES, "calibration_run")          # fail fast, before any other import
    except G.GateFailure as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    from rba import calib as C, inputs as I, launch as L  # noqa: E402
    from rba.budget import GateFailure, Ledger  # noqa: E402
    man = EXT / "artifacts/calibration/run_manifest_v1.jsonl"
    msha = (EXT / "artifacts/calibration/run_manifest_v1.sha256").read_text().split()[0]
    import hashlib, json
    if hashlib.sha256(man.read_bytes()).hexdigest() != msha:
        raise GateFailure("recorded manifest hash mismatch")
    rows = [json.loads(line) for line in man.read_text().splitlines() if line.strip()]
    for row in rows:
        for field, filename in (("parser_sha256", "scaled_parsing.py"),
                                ("validity_policy_sha256", "output_validity.py"),
                                ("generation_code_sha256", "exact_generation.py")):
            row[field] = hashlib.sha256((EXT / "src/rba/legacy" / filename).read_bytes()).hexdigest()
    effective = Path(a.store) / "execution_manifest.jsonl"
    effective.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    if effective.exists() and effective.read_text() != body:
        raise GateFailure("output directory belongs to another execution manifest")
    effective.write_text(body)
    man, msha = effective, hashlib.sha256(body.encode()).hexdigest()
    tasks = {f"{x['dataset']}/{x['source_task_id']}": x for x in I.load_json("answers")["accepted"]}

    def verify(u):
        t = tasks[u["base_task_id"]]
        r = C.render(t["question"], t["answer"], u["context"], u["rubric_id"])
        msgs = C.messages(u["model_key"], r["prompt"])
        if C.sha256_text(r["prompt"]) != u["prompt_sha256"] or \
                C.sha256_text(C.canonical(msgs)) != u["messages_sha256"]:
            raise GateFailure(f"prompt identity mismatch for {u['unit_id']}")
        return msgs

    stage = a.stage or L.STAGE
    ledger = Ledger(Path(a.ledger), stage_caps={stage: a.stage_cap_hours})
    L.launch_calibration(stage=stage, gates_path=GATES, manifest_path=man, manifest_sha256=msha,
                         store_dir=Path(a.store), ledger=ledger, verify_identity=verify,
                         projected_unit_hours=a.projected_unit_seconds / 3600,
                         unit_timeout_s=a.unit_timeout_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
