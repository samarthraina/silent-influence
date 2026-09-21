"""Not a test fixture: importing this module puts the study code on sys.path.

The analysis builders import analyze_final_study and silent_influence directly. Upstream
those sit beside them; in this package they live under code/scripts/ and code/src/.
"""
from __future__ import annotations

import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
for _p in (CODE / "src", CODE / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
