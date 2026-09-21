"""Shared test setup: put both src/ and scripts/ on sys.path so tests can import
silent_influence modules and top-level scripts/*.py directly, without a GPU or model
weights. Mirrors scripts/_bootstrap.py's own path setup."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
