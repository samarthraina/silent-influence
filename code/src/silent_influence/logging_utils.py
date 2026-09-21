"""Minimal stdout+file logger, so every run leaves a run.log next to its records."""
from __future__ import annotations

from pathlib import Path
from typing import Callable


def make_logger(log_path: Path) -> Callable[[str], None]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_path, "a", encoding="utf-8", newline="\n")

    def log(msg: str) -> None:
        print(msg)
        fh.write(msg + "\n")
        fh.flush()

    return log
