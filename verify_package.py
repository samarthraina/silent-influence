"""Check public-release file hashes and recorded headline consistency; stdlib only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parent
EXCLUDED = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "outputs", ".ruff_cache"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(root: Path) -> list[str]:
    manifest = json.loads((root / "ARTIFACT_MANIFEST.json").read_text())
    entries = manifest["files"]
    seen = set()
    errors = []
    for entry in entries:
        relative = entry["path"]
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or ".." in parsed.parts or "\\" in relative:
            errors.append(f"Unsafe manifest path: {relative}")
            continue
        if relative in seen:
            errors.append(f"Duplicate manifest path: {relative}")
            continue
        seen.add(relative)
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            errors.append(f"Symlink or escaping path: {relative}")
        elif not path.is_file():
            errors.append(f"Missing: {relative}")
        elif path.stat().st_size != entry["size"] or sha256(path) != entry["sha256"]:
            errors.append(f"Changed: {relative}")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
              and not any(part in EXCLUDED for part in p.relative_to(root).parts)
              and p.name not in {"ARTIFACT_MANIFEST.json", ".DS_Store"}}
    errors.extend(f"Unmanifested: {name}" for name in sorted(actual - seen))
    if len(entries) != manifest["n_files"]:
        errors.append("Manifest count disagrees with entries")
    if sum(e["size"] for e in entries) != manifest["total_bytes"]:
        errors.append("Manifest byte total disagrees with entries")
    return errors


def main() -> int:
    try:
        errors = verify(ROOT)
        sys.path.insert(0, str(ROOT / "examples"))
        from explore_results import summarize, matched_example
        summary = summarize(ROOT)
        matched_example(ROOT)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    count = json.loads((ROOT / "ARTIFACT_MANIFEST.json").read_text())["n_files"]
    print(f"PASS: {count} file hashes, complete inventory, and recorded result consistency")
    print(f"Complete-case score decrease: {summary['mean_shift']:.3f}, n={summary['matched_pairs']}")
    print("Integrity is not an independent reproduction of model inference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
