"""Run the portable test suite, retaining documented research-record exclusions."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    exclusions = [line.strip() for line in (ROOT / "release_tests.txt").read_text().splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg")
    args = [sys.executable, "-B", "-m", "pytest", "code/tests", "silence/test_judge_prompt.py",
            "mechanistic", "tests", "-q", "-p", "no:cacheprovider"]
    args.extend(f"--deselect={node}" for node in exclusions)
    args.extend(sys.argv[1:])
    return subprocess.call(args, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
