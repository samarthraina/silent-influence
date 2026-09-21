"""Explicitly rebuild release checksums after intentional changes; never run implicitly."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_package import EXCLUDED, sha256


def main() -> None:
    entries = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if not path.is_file() or any(part in EXCLUDED for part in rel.parts):
            continue
        if path.name in {"ARTIFACT_MANIFEST.json", ".DS_Store"}:
            continue
        if path.is_symlink():
            raise ValueError(f"Release must not contain symlinks: {rel}")
        entries.append({"path": rel.as_posix(), "size": path.stat().st_size,
                        "sha256": sha256(path)})
    manifest = {"package": "silent-influence", "format_version": 1,
                "scope": "Public release files, excluding this manifest and local generated artifacts",
                "n_files": len(entries), "total_bytes": sum(e["size"] for e in entries),
                "files": entries}
    (ROOT / "ARTIFACT_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote manifest for {len(entries)} files")


if __name__ == "__main__":
    main()
