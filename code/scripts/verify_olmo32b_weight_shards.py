#!/usr/bin/env python3
"""Verify downloaded allenai/Olmo-3.1-32B-Instruct weight shards against the frozen
sha256 map recorded in configs/scorer_olmo3_1_32b_pin.json BEFORE any inference runs.

This script is a GPU-host step: it only makes sense to run it after the 14 safetensors
shards have been downloaded there (~60 GiB; not fetched by this repo). It never downloads
anything itself -- it streams each already-present file in 8 MiB chunks and compares its
sha256 against the value recorded in the pin file's
weight_shard_lfs_sha256_for_later_verification, which was itself obtained from the
HuggingFace tree API at the pinned revision without downloading weights (see
configs/scorer_olmo3_1_32b_pin.json .artifact_integrity).

A missing shard or a hash mismatch is a hard failure: either means the run would be
scoring with weights other than the ones every other frozen artifact assumes, silently
invalidating hash-based reproducibility guarantees elsewhere in the pipeline (the
preflight gate's chat_template_sha256 check, the residency gate's expected-weight-bytes
check, etc. all assume these specific weights).

    python scripts/verify_olmo32b_weight_shards.py --shard-dir /path/to/downloaded/olmo32b
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence import exact_generation as eg

PIN_FILE = REPO / "configs/scorer_olmo3_1_32b_pin.json"
PIN_FILE_SHA256 = "0818438052f6ec33b62f5ec8d6ec1d5e5240b427824768a3c2ab329a98b5684f"


def load_expected_shard_hashes(pin_file: Path, skip_hash_check: bool) -> dict:
    if not skip_hash_check:
        import hashlib
        got = hashlib.sha256(pin_file.read_bytes()).hexdigest()
        if got != PIN_FILE_SHA256:
            raise SystemExit(f"FROZEN ARTIFACT MISMATCH: {pin_file} sha256={got} "
                             f"expected={PIN_FILE_SHA256}. Stopping; the pin file must "
                             f"not be edited to make this pass.")
    with open(pin_file, encoding="utf-8") as f:
        pin = json.load(f)
    expected = pin["weight_shard_lfs_sha256_for_later_verification"]
    # Drop the "note" key if present; every other key is a real shard filename.
    return {k: v for k, v in expected.items() if k != "note"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard-dir", required=True,
                    help="local directory containing the downloaded "
                         "model-*-of-00014.safetensors files")
    ap.add_argument("--pin-file", default=str(PIN_FILE))
    ap.add_argument("--skip-hash-check", action="store_true",
                    help="dev/test only -- bypass the pin-file hash gate")
    ap.add_argument("--out", default=None,
                    help="where to write the verification report "
                         "(default: <shard-dir>/weight_shard_verification.json)")
    args = ap.parse_args()

    expected = load_expected_shard_hashes(Path(args.pin_file), args.skip_hash_check)
    shard_dir = Path(args.shard_dir)
    print(f"[verify] {len(expected)} expected shards, checking against {shard_dir}")

    problems = eg.verify_weight_shard_hashes(shard_dir, expected)

    report = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shard_dir": str(shard_dir),
        "pin_file": str(args.pin_file),
        "n_expected_shards": len(expected),
        "n_problems": len(problems),
        "problems": problems,
        "passed": not problems,
    }
    out_path = Path(args.out) if args.out else shard_dir / "weight_shard_verification.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    if problems:
        print("WEIGHT SHARD VERIFICATION FAILED:")
        for p in problems:
            print(f"  {p}")
    else:
        print(f"WEIGHT SHARD VERIFICATION PASSED: all {len(expected)} shards byte-exact")
    print(f"[save] {out_path}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
