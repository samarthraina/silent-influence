"""Put the study package on sys.path so the mechanistic tests can import it from this
package layout, where the source lives under code/src/ rather than beside these files."""
from __future__ import annotations

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "code" / "src", PKG / "code" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
