#!/usr/bin/env python3
"""Verify every hash asserted anywhere in the amendment chain, read out of the freeze
records themselves rather than from a list maintained by hand.

The six records assert hashes in six different shapes, accumulated as the chain grew:

    {"new_artifacts_sha256": {"<path>": "<hash>"}}                    flat path -> hash
    {"artifacts": {"<name>": {"path": ..., "sha256": ...}}}           named, explicit path
    {"manifest": {"path": ..., "sha256": ...}}                        single object
    {"preserved_artifacts": {"<alias>": "<hash>"}}                    alias, NO path
    {"modules": {"<basename>.py": "<hash>"}}                          bare module name
    {"replacement_scorer": {"config_file_hashes_sha256": {...}}}      HF snapshot, not in repo

An earlier version of this script read four key names and one shape, which silently ignored
the other five and left two genuinely asserted artifacts -- manifest_v2_freeze_record.json
and select_final_tasks_v2_english.py -- verified by nothing at all, while still reporting a
plausible-looking count. Every shape is now walked, every assertion is classified, and an
assertion this script cannot classify is a hard failure rather than a silent omission.

Hard failure: a mismatched hash, a missing repo file, an unreachable working note, two
records disagreeing about one file, an unclassifiable assertion, or a verified-file count
that differs from EXPECTED_VERIFIED_FILES. There is no "skip" that still passes.

    python scripts/verify_all_frozen_hashes.py

Exit 0 only if every assertion was resolved and verified.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from _bootstrap import REPO

FREEZE_RECORDS = sorted((REPO / "results/final_task_selection").glob("*freeze_record.json"))

# Distinct files this gate must verify. Pinned so that a future change which quietly stops
# collecting a shape fails loudly instead of reporting a smaller, plausible number.
# 33 through A5; A6 adds its config and narrative, pins exact_generation.py, and is
# the first record to assert A5's own freeze record.
# 37 through A6; A7 adds its config and narrative and pins the two execution
# scripts, and is the first record to assert A6's own freeze record.
# 42 through A7; A8 adds its config and narrative and is the first record to
# assert A7's own freeze record. The two execution scripts were already pinned by
# A7, so A8 supersedes their hashes rather than adding files.
# 45 through A8; A9 adds config, narrative, the 234-task manifest, its selector,
# the calibration and OLMo-gate scripts, the frozen candidates file, and asserts
# A8's own freeze record.
# 54 through A9; A10 adds its config and narrative and re-pins run_final_scoring.
EXPECTED_VERIFIED_FILES = 57

# Bare-basename assertions, resolved by searching these directories in order.
MODULE_SEARCH_DIRS = ("src/silent_influence", "scripts")

# Assertions that are deliberately NOT repo artifacts: hashes of files served by the Hugging
# Face snapshot at the pinned revision. Verified against the hub during the model-download
# preflight, not from the working tree. Listed explicitly so they are visibly out of scope
# rather than dropped.
NON_REPO_PARENT_KEYS = ("config_file_hashes_sha256",)

# Provenance hashes of RUN artifacts that live outside the repository (under /workspace/
# production on the GPU host): the mechanically generated post-calibration record stamps the
# calibration verdict it read. Named explicitly, reported as out-of-scope, and never silently
# dropped -- an unnamed unclassifiable assertion is still a hard failure.
RUN_ARTIFACT_PROVENANCE_KEYS = ("calibration_verdict_sha256",)


def declared_supersessions(records=None) -> set:
    """Paths a record explicitly declares it re-pins."""
    out = set()
    for rec_path in (records if records is not None else FREEZE_RECORDS):
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        for key in SUPERSESSION_DECLARATION_KEYS:
            block = rec.get(key)
            if isinstance(block, dict):
                out |= {k for k, v in block.items() if isinstance(v, dict)}
    return out

# Alias maps: a nickname for an artifact whose path is asserted elsewhere in the chain. There
# is no path to resolve, so these are verified by requiring the hash to match a file this run
# already verified -- which is what the alias is asserting.
ALIAS_PARENT_KEYS = ("preserved_artifacts",)

# Living working documents: append-only by design, so successive freeze records legitimately
# record DIFFERENT hashes for them. The newest record's assertion is the current one;
# earlier ones are superseded history rather than a conflict. Every other artifact stays
# strictly immutable and a disagreement about it is still a hard failure.
LIVING_DOCUMENT_BASENAMES = ("JOURNAL.md", "OBSERVATIONS.md")

# A record may explicitly re-pin an implementation file an earlier record already pinned --
# A8 does this for the two execution scripts A7 froze mid-repair. The declaration must name
# the exact path under this key; a conflict about anything NOT declared here stays a hard
# failure, so being newer is not by itself a licence to disagree.
SUPERSESSION_DECLARATION_KEYS = ("supersedes_hashes_from_A7", "supersedes_hashes")

# The supersession block records the OLD and NEW hash side by side as documentation. Those
# are historical values by construction, not assertions about the current tree.
DOCUMENTATION_PARENT_KEYS = SUPERSESSION_DECLARATION_KEYS


def is_living_document(rel: str) -> bool:
    return rel.replace("\\", "/").rsplit("/", 1)[-1] in LIVING_DOCUMENT_BASENAMES

_HEX64 = 64


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_hash(v) -> bool:
    return isinstance(v, str) and len(v) == _HEX64 and all(c in "0123456789abcdef" for c in v)


def looks_absolute(rel: str) -> bool:
    """Decided by inspecting the string, not Path.is_absolute(): the latter answers
    differently for the same recorded path on Windows and on Linux, and this gate must
    classify identically on both hosts."""
    return rel.startswith(("/", "\\")) or (len(rel) > 1 and rel[1] == ":")


def is_note_path(rel: str) -> bool:
    return rel.startswith("Code/") or "research_notes" in rel.replace("\\", "/")


def collect(records=None) -> list:
    """Walk every record and return one dict per asserted hash.

    Each entry carries the record it came from and the JSON key path, so an unclassifiable
    assertion can be reported precisely instead of guessed at."""
    out = []
    for rec_path in (records if records is not None else FREEZE_RECORDS):
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        # Used only to order assertions about living documents; absent on older records, which
        # then sort before any dated one.
        frozen_at = rec.get("frozen_at_utc") or ""

        def walk(node, keypath, parent_key):
            # Shape: an object carrying its own path alongside its hash.
            if isinstance(node, dict) and is_hash(node.get("sha256")) \
                    and isinstance(node.get("path"), str):
                out.append({"record": rec_path.name, "keypath": keypath,
                            "path": node["path"], "hash": node["sha256"],
                            "frozen_at": frozen_at})
                # keep walking: such objects may nest further maps
            if isinstance(node, dict):
                for k, v in node.items():
                    kp = f"{keypath}.{k}" if keypath else k
                    if is_hash(v):
                        # Sibling convention: "<name>_sha256" is the hash OF the path held in
                        # sibling key "<name>" (A2's superseded_scorer.pin_file). Without this
                        # the key itself would be read as a path and be unclassifiable.
                        sib = k[: -len("_sha256")] if k.endswith("_sha256") else None
                        named = node.get(sib) if sib else None
                        path = named if isinstance(named, str) and named else k
                        out.append({"record": rec_path.name, "keypath": kp,
                                    "path": path, "hash": v, "parent_key": parent_key,
                                    "frozen_at": frozen_at})
                    else:
                        walk(v, kp, k)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{keypath}[{i}]", parent_key)

        walk(rec, "", None)
    # A path+sha256 object also emits its "sha256" child as a bare hash keyed "sha256";
    # drop those, they duplicate the richer entry.
    return [a for a in out if a["path"] != "sha256"]


def classify(a: dict) -> str:
    parent = a.get("parent_key")
    if a.get("path") in RUN_ARTIFACT_PROVENANCE_KEYS:
        return "non_repo_snapshot"
    if parent in DOCUMENTATION_PARENT_KEYS or a.get("keypath", "").startswith(
            SUPERSESSION_DECLARATION_KEYS):
        return "documentation"
    if any(a.get("keypath", "").startswith(k + ".") for k in SUPERSESSION_DECLARATION_KEYS):
        return "documentation"
    if parent in NON_REPO_PARENT_KEYS:
        return "non_repo_snapshot"
    if parent in ALIAS_PARENT_KEYS:
        return "alias"
    p = a["path"]
    if is_note_path(p):
        return "note"
    if "/" in p.replace("\\", "/"):
        return "repo"
    if p.endswith(".py"):
        return "module_basename"
    return "unclassifiable"


def resolve_note(rel: str) -> Path | None:
    """Working notes live outside the pushable repo, and the two hosts nest them differently:
    PROJECT/Code/research_notes with the repo at Code/GitHub/<repo>, versus /workspace/Code
    beside /workspace/<repo>. A2's record additionally spelled one note as an absolute
    Windows path.

    An absolute spelling is accepted ONLY when the tail it names is also asserted somewhere
    as a portable "Code/..." path, i.e. only when it is provably an alias for a file this
    gate already knows about. Re-pointing an arbitrary absolute path at a same-named file in
    the notes directory would let the gate verify a different file than the one recorded and
    report a pass, so that is not done."""
    norm = rel.replace("\\", "/")
    idx = norm.find("research_notes/")
    if idx < 0:
        return None
    rest = norm[idx:]
    for cand in (REPO.parents[1] / rest, REPO.parent / "Code" / rest):
        if cand.exists():
            return cand
    return None


def resolve_module(basename: str) -> Path | None:
    for d in MODULE_SEARCH_DIRS:
        cand = REPO / d / basename
        if cand.exists():
            return cand
    return None


def main() -> int:
    if not FREEZE_RECORDS:
        print("no freeze records found -- refusing to report success")
        return 1

    assertions = collect()

    # Group by file identity so two spellings of one file must agree.
    by_path: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    aliases, non_repo, unclassifiable, documentation = [], [], [], []
    superseded_paths = declared_supersessions()
    portable_note_tails = {
        a["path"].replace("\\", "/")[a["path"].replace("\\", "/").find("research_notes/"):]
        for a in assertions
        if classify(a) == "note" and a["path"].startswith("Code/")
    }

    for a in assertions:
        kind = classify(a)
        if kind == "alias":
            aliases.append(a)
        elif kind == "non_repo_snapshot":
            non_repo.append(a)
        elif kind == "documentation":
            documentation.append(a)
        elif kind == "unclassifiable":
            unclassifiable.append(a)
        else:
            by_path[a["path"]][a["hash"]].append(a)

    print(f"freeze records: {len(FREEZE_RECORDS)}")
    for r in FREEZE_RECORDS:
        print(f"  - {r.name}")
    print(f"\nassertions collected: {len(assertions)}  "
          f"(paths {sum(len(v) for v in by_path.values())}, aliases {len(aliases)}, "
          f"non-repo {len(non_repo)}, unclassifiable {len(unclassifiable)})\n")

    ok = mismatch = missing = conflict = 0
    verified_hashes: set[str] = set()
    seen_files: set[Path] = set()

    superseded = 0
    for rel in sorted(by_path):
        variants = by_path[rel]
        if len(variants) > 1:
            if is_living_document(rel) or rel in superseded_paths:
                # Append-only document: take the assertion from the newest freeze record and
                # report the rest as superseded, so the gate still verifies the CURRENT state
                # rather than skipping the file or failing on its own history.
                newest = max((a for srcs in variants.values() for a in srcs),
                             key=lambda a: (a.get("frozen_at") or "", a["record"]))
                want, srcs = newest["hash"], [newest]
                older = sum(len(v) for v in variants.values()) - 1
                superseded += older
                tag = "LIVING" if is_living_document(rel) else "RE-PINNED"
                print(f"[{tag:<8}] {rel}  current per {newest['record']}"
                      f" ({older} superseded assertion(s))")
            else:
                conflict += 1
                print(f"[CONFLICT] {rel}")
                for h, srcs in variants.items():
                    print(f"           {h[:16]}... from "
                          f"{', '.join(f'{a['record']}:{a['keypath']}' for a in srcs)}")
                continue
        else:
            want, srcs = next(iter(variants.items()))

        kind = "note" if is_note_path(rel) else ("module_basename"
                                                 if "/" not in rel.replace("\\", "/")
                                                 else "repo")
        if kind == "note":
            if looks_absolute(rel):
                tail = rel.replace("\\", "/")
                tail = tail[tail.find("research_notes/"):]
                if tail not in portable_note_tails:
                    print(f"[UNPROVEN] {rel}")
                    print("           absolute spelling with no portable twin asserted; "
                          "refusing to guess which file it names")
                    missing += 1
                    continue
            p = resolve_note(rel)
        elif kind == "module_basename":
            p = resolve_module(rel)
        else:
            p = REPO / rel

        if p is None or not p.exists():
            missing += 1
            label = "UNREACHABLE" if kind == "note" else "MISSING"
            print(f"[{label:<9}] {rel}  <- hard failure ({len(srcs)} assertion(s))")
            continue

        got = sha256_file(p)
        if got == want:
            ok += 1
            verified_hashes.add(got)
            seen_files.add(p.resolve())
            print(f"[OK       ] {rel}  ({len(srcs)} assertion(s))")
        else:
            mismatch += 1
            print(f"[MISMATCH ] {rel}\n            want {want}\n            got  {got}")

    # Aliases assert "this nickname still names content the chain froze"; verified by hash
    # membership among the files just verified.
    alias_bad = 0
    if aliases:
        print()
        for a in aliases:
            if a["hash"] in verified_hashes:
                print(f"[OK-ALIAS ] {a['record']}:{a['keypath']} -> {a['path']}")
            else:
                alias_bad += 1
                print(f"[BAD-ALIAS] {a['record']}:{a['keypath']} -> {a['path']}")
                print(f"            hash {a['hash'][:16]}... matches no verified artifact")

    if non_repo:
        print()
        for a in non_repo:
            print(f"[OUT-SCOPE] {a['keypath']} (HF snapshot file, verified at "
                  f"model-download preflight, not from the working tree)")

    if unclassifiable:
        print()
        for a in unclassifiable:
            print(f"[UNKNOWN  ] {a['record']}:{a['keypath']} -> {a['path']!r} "
                  f"<- cannot classify; refusing to skip it")

    distinct = len(seen_files)
    count_ok = distinct == EXPECTED_VERIFIED_FILES
    print(f"\nverified {ok} assertion group(s) over {distinct} distinct file(s) "
          f"(expected {EXPECTED_VERIFIED_FILES})")
    print(f"mismatched {mismatch} | missing/unreachable {missing} | conflicting {conflict} | "
          f"bad aliases {alias_bad} | unclassifiable {len(unclassifiable)} | "
          f"superseded/re-pinned assertions {superseded} | "
          f"documentation entries {len(documentation)}")
    if not count_ok:
        print(f"COUNT MISMATCH: verified {distinct} distinct files, expected "
              f"{EXPECTED_VERIFIED_FILES} -- a shape may have stopped being collected")

    hard = mismatch + missing + conflict + alias_bad + len(unclassifiable) + (0 if count_ok else 1)
    print("ALL FROZEN HASHES VERIFIED" if hard == 0 else "FROZEN HASH GATE FAILED")
    return 0 if hard == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
