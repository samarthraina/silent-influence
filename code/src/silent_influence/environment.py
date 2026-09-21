"""Environment/version snapshot, for the "environment metadata/package versions" artifact.

Captured once per run, not per record — kept in the manifest, matching how the rest of
this project records provenance (models.yaml revisions, dataset source hashes) at the
run level rather than duplicating it onto every line of a JSONL file.
"""
from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any, Dict


def capture_environment() -> Dict[str, Any]:
    env: Dict[str, Any] = {
        "python_version": sys.version,
        "platform": platform.platform(),
    }
    for pkg in ("torch", "transformers", "accelerate", "huggingface_hub", "numpy"):
        try:
            mod = __import__(pkg)
            env[f"{pkg}_version"] = getattr(mod, "__version__", "unknown")
        except ImportError:
            env[f"{pkg}_version"] = None

    try:
        import torch
        env["cuda_available"] = bool(torch.cuda.is_available())
        env["cuda_device_count"] = torch.cuda.device_count() if torch.cuda.is_available() else 0
        env["cuda_device_names"] = ([torch.cuda.get_device_name(i)
                                     for i in range(torch.cuda.device_count())]
                                    if torch.cuda.is_available() else [])
    except Exception as e:
        env["cuda_available"] = None
        env["cuda_error"] = str(e)

    try:
        env["pip_freeze"] = subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"], text=True, timeout=60
        ).splitlines()
    except Exception as e:
        env["pip_freeze"] = None
        env["pip_freeze_error"] = str(e)

    return env
