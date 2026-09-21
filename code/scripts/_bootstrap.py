"""Path + config plumbing shared by the scripts."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))


def load_merged_config(path: str | Path) -> Dict[str, Any]:
    """Load a run config, merging any `include:` files (top-level keys, no deep merge)."""
    import yaml

    p = Path(path)
    if not p.is_absolute():
        p = (REPO / p) if (REPO / p).exists() else p.resolve()
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    merged: Dict[str, Any] = {}
    for inc in cfg.pop("include", []) or []:
        ip = REPO / inc
        with open(ip, encoding="utf-8") as f:
            part = yaml.safe_load(f) or {}
        for k, v in part.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k].update(v)
            else:
                merged[k] = v
    merged.update(cfg)
    merged["_config_path"] = str(p)
    return merged
