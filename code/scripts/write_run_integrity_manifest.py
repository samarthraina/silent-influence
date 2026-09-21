#!/usr/bin/env python3
"""Assemble the run-integrity manifest for the final behavioral study: environment,
model/scorer revisions, prompt/parser module hashes, task-manifest hash, and (once they
exist) references to every stage's own manifest and gate report. Safe to run at any
point -- before data collection (to confirm the frozen inputs are intact) or after (to
capture what was actually used).

Every "frozen_*_sha256" value below is re-hashed from disk right now and compared to the
expected value recorded in configs/final_analysis_plan.json /
configs/final_analysis_plan_v2_1.json / configs/final_analysis_plan_v2_2.json (Amendment
A2) / configs/final_analysis_plan_v2_2_clarification_C1.json (Clarification C1) /
configs/final_analysis_plan_v2_3.json (Amendment A3) / configs/scorer_olmo3_1_32b_pin.json -- never assumed. A mismatch is recorded, not silently
ignored, so a diverged frozen input is visible in the manifest itself, not just at the
one-time gate the operator ran by hand.

The active scorer panel (Amendment A2) is llama/qwen/gemma/olmo32b. The superseded fourth
scorer, mistralai/Mistral-Small-24B-Instruct-2501, was never run; its pin file is still
gated here (status "historical_unused") so a corruption of that historical record would
also be caught, but it is excluded from the active SCORERS registry below.

    python scripts/write_run_integrity_manifest.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import REPO

from silent_influence.environment import capture_environment

OUT_DIR = REPO / "results/final_behavioral_study"

FROZEN_ARTIFACTS = {
    "task_manifest_v2": {
        "path": "data/prompts/final_tasks_v2_english_seed20260817.json",
        "expected_sha256": "a001d48b7769311da33cba1a8ef51bb4e9d1a27b2cc0d007bce85adab606037f",
        "status": "active",
    },
    "analysis_plan_v2": {
        "path": "configs/final_analysis_plan.json",
        "expected_sha256": "ea41c3d6f4af734605850896049d54952eec9f9450713881b24b2d52611cd52c",
        "status": "active",
    },
    "analysis_plan_amendment_A1": {
        "path": "configs/final_analysis_plan_v2_1.json",
        "expected_sha256": "0d92256df8e71fa74bcd9fa378f4602a71c47fec43dee709fc4b44f8991455b0",
        "status": "active",
    },
    "analysis_plan_amendment_A2": {
        "path": "configs/final_analysis_plan_v2_2.json",
        "expected_sha256": "9b202820df5d0d8837e22bd701a473e48eb5f726cd1baf854018ef16e828cbc3",
        "status": "active",
    },
    "analysis_plan_clarification_C1": {
        "path": "configs/final_analysis_plan_v2_2_clarification_C1.json",
        "expected_sha256": "998e11461163c0b03a6490ef6c3e5c150f491f819d8d658acb3ea23bfb0c96e6",
        "status": "active",
    },
    "analysis_plan_amendment_A3": {
        "path": "configs/final_analysis_plan_v2_3.json",
        "expected_sha256": "2d86b5df14f116b603159955468795af3530fc16e147f0df340f7d5383f1b86e",
        "status": "active",
    },
    # The freeze records are what make the amendment chain auditable: each one asserts the
    # hashes of its own new artifacts AND re-asserts every prior artifact as unmodified.
    # Gating them here means a rewritten history is caught, not just a rewritten plan.
    "freeze_record_plan_v2": {
        "path": "results/final_task_selection/final_analysis_plan_v2_freeze_record.json",
        "expected_sha256": "90334a62a46f788f75de2e7e23e7a7348ee9b428be1674dfeb6b027394d7f7b9",
        "status": "active",
    },
    "freeze_record_A1": {
        "path": "results/final_task_selection/final_analysis_plan_A1_freeze_record.json",
        "expected_sha256": "2d23431a3c201942303b7a2096ed57f4b7003b55368181e1086d3b7ded641f9d",
        "status": "active",
    },
    "freeze_record_A2": {
        "path": "results/final_task_selection/final_analysis_plan_A2_freeze_record.json",
        "expected_sha256": "21d9779761fc1d7206ec2e53388d539cbc857568ccf12116070727a0351b8fa8",
        "status": "active",
    },
    "freeze_record_A2_C1": {
        "path": "results/final_task_selection/final_analysis_plan_A2_C1_freeze_record.json",
        "expected_sha256": "71eb08923e09db81f6e209425342337a3e8fd86f65dacb830e9aa3e7b814b0c6",
        "status": "active",
    },
    "analysis_plan_amendment_A4": {
        "path": "configs/final_analysis_plan_v2_4.json",
        "expected_sha256": "062cb165a626fbd81388b499550227853b1d6454dd93a2f5a27850cf05932771",
        "status": "active",
    },
    "analysis_plan_amendment_A5": {
        "path": "configs/final_analysis_plan_v2_5.json",
        "expected_sha256": "756f7c4107108f6a9f30c50e0854f66f63a8706a9ada5cc18005fb9257019303",
        "status": "active",
    },
    "freeze_record_A5": {
        "path": "results/final_task_selection/final_analysis_plan_A5_freeze_record.json",
        "expected_sha256": "80fe52ce3b64d696837de33a594fb619b3b468b69ba3d941c50b5e5cbc54f4da",
        "status": "active",
    },
    "output_validity_module": {
        "path": "src/silent_influence/output_validity.py",
        "expected_sha256": "f24057fd6542e5cdf51a4ed75b3bfa94363ceb87ec529b3bad14392f89c47184",
        "status": "active",
    },
    "freeze_record_A4": {
        "path": "results/final_task_selection/final_analysis_plan_A4_freeze_record.json",
        "expected_sha256": "b610a23e3511c84bae40a25516ba57fda9a15d0263e0133f7809c79a34022432",
        "status": "active",
    },
    "freeze_record_A3": {
        "path": "results/final_task_selection/final_analysis_plan_A3_freeze_record.json",
        "expected_sha256": "663074863713dfed0604cd88e147f7096602c018f157904064a9ddffee2db8a8",
        "status": "active",
    },
    "olmo32b_scorer_pin": {
        "path": "configs/scorer_olmo3_1_32b_pin.json",
        "expected_sha256": "0818438052f6ec33b62f5ec8d6ec1d5e5240b427824768a3c2ab329a98b5684f",
        "status": "active",
    },
    "mistral_scorer_pin": {
        "path": "configs/scorer_mistral_small_24b_pin.json",
        "expected_sha256": "3ad5fec336531bc625274835cf23391d3c1a5f54ab27ee7142e9bd83c480b19a",
        "status": "historical_unused",
        "note": "superseded by Amendment A2; this scorer was never run. Pin file preserved "
               "unmodified and still integrity-checked, but excluded from the active "
               "scorer registry below.",
    },
}

# Amendment narratives. Not repo artifacts by design (working notes stay out of the pushable
# tree), so they are referenced by hash rather than gated by path. Resolved relative to the
# repo's grandparent; unreachable is an expected state, not a mismatch.
OUT_OF_TREE_REFERENCES = {
    "amendment_A5_narrative": {
        "path": "research_notes/final_analysis_plan_amendment_A5.md",
        "expected_sha256": "bb370989e07c074f5372ea8d986c7f7f364224699775e1acfbcdcaf886a32817",
        "asserted_by": "results/final_task_selection/final_analysis_plan_A5_freeze_record.json",
    },
    "amendment_A4_narrative": {
        "path": "research_notes/final_analysis_plan_amendment_A4.md",
        "expected_sha256": "61fba1a55c9f5eb884a46922bf04ba8f8ee74b36d4fa2260bd21264fa7824d07",
        "asserted_by": "results/final_task_selection/final_analysis_plan_A4_freeze_record.json",
    },
    "amendment_A3_narrative": {
        "path": "research_notes/final_analysis_plan_amendment_A3.md",
        "expected_sha256": "299d737b85af737476632c78fa91b271577112c13b6b23d9e0032a633107c7f7",
        "asserted_by": "results/final_task_selection/final_analysis_plan_A3_freeze_record.json",
    },
}

# Prompt-content and parsing-semantics modules that MUST NOT change during
# implementation; recorded here for provenance, not gated (the gate above covers the
# artifacts explicitly named by the user before implementation began).
CONTENT_MODULES = {
    "scaled_conditions.py": "src/silent_influence/scaled_conditions.py",
    "scaled_parsing.py": "src/silent_influence/scaled_parsing.py",
}
# New/extended infrastructure modules built for this study; recorded for provenance only
# (their hashes are expected to change across implementation revisions).
INFRA_MODULES = {
    "exact_generation.py": "src/silent_influence/exact_generation.py",
    "final_study_messages.py": "src/silent_influence/final_study_messages.py",
    "final_preflight_checks.py": "src/silent_influence/final_preflight_checks.py",
    "final_score_recovery.py": "src/silent_influence/final_score_recovery.py",
}

GENERATOR = {"key": "olmo3", "hf_id": "allenai/Olmo-3-7B-Instruct",
            "revision": "6e5971d9eba42665f5bd5a0fcf047f299ce1dccc"}
SCORERS = [
    {"key": "llama", "hf_id": "meta-llama/Llama-3.1-8B-Instruct",
     "revision": "0e9e39f249a16976918f6564b8830bc894c89659"},
    {"key": "qwen", "hf_id": "Qwen/Qwen3-8B",
     "revision": "b968826d9c46dd6066d109eabc6255188de91218", "disable_thinking": True},
    {"key": "gemma", "hf_id": "google/gemma-2-9b-it",
     "revision": "11c9b309abf73637e4b6f9a3fa1e92e615547819"},
    {"key": "olmo32b", "hf_id": "allenai/Olmo-3.1-32B-Instruct",
     "revision": "ac0587e4a7744a551c059d8cd17ba220bc940dae",
     "force_use_cache": True, "requires_memory_preflight": True},
]
SUPERSEDED_SCORERS = [
    {"key": "mistral", "hf_id": "mistralai/Mistral-Small-24B-Instruct-2501",
     "revision": "9527884be6e5616bdd54de542f9ae13384489724",
     "status": "historical_unused", "ever_run": False,
     "superseded_by": "olmo32b (Amendment A2)"},
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO,
                                       text=True, timeout=10,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def resolve_out_of_tree(rel: str) -> Path:
    """Locate a working-note path on either host layout: the workstation nests the repo as
    PROJECT/Code/GitHub/<repo> (so the notes sit at REPO.parents[1]), while the GPU box has
    /workspace/Code beside /workspace/<repo>. Absolute paths are taken as given.

    Callers and tests must both go through this rather than assuming one layout -- assuming
    the local one is what made two tests pass here and fail on the GPU host."""
    p = Path(rel)
    if p.is_absolute():
        return p
    for cand in (REPO.parents[1] / rel, REPO.parent / "Code" / rel):
        if cand.exists():
            return cand.resolve()
    return (REPO.parents[1] / rel).resolve()


def load_json_if_exists(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> int:
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    frozen_check = {}
    all_frozen_match = True
    active_frozen_match = True
    for name, spec in FROZEN_ARTIFACTS.items():
        p = REPO / spec["path"]
        status = spec.get("status", "active")
        if not p.exists():
            frozen_check[name] = {"path": spec["path"], "exists": False, "match": False,
                                  "status": status}
            all_frozen_match = False
            if status == "active":
                active_frozen_match = False
            continue
        got = sha256_file(p)
        match = got == spec["expected_sha256"]
        all_frozen_match &= match
        if status == "active":
            active_frozen_match &= match
        frozen_check[name] = {"path": spec["path"], "exists": True,
                             "expected_sha256": spec["expected_sha256"],
                             "actual_sha256": got, "match": match, "status": status,
                             "note": spec.get("note")}

    # The amendment narratives deliberately live OUTSIDE the pushable tree, so they cannot be
    # gated by a repo-relative path. Their hashes are asserted by the in-repo freeze records
    # (already gated above), and re-checked here when the out-of-tree copy is reachable.
    # Absent is "not_reachable", never a failure: on the GPU host the tree is intentionally
    # narrative-free, and a missing private note is the correct state there, not a defect.
    narrative_check = {}
    for name, spec in OUT_OF_TREE_REFERENCES.items():
        p = resolve_out_of_tree(spec["path"])
        if not p.exists():
            narrative_check[name] = {"path": spec["path"], "reachable": False,
                                    "status": "not_reachable_by_design",
                                    "asserted_by": spec["asserted_by"]}
            continue
        got = sha256_file(p)
        narrative_check[name] = {"path": spec["path"], "reachable": True,
                                "expected_sha256": spec["expected_sha256"],
                                "actual_sha256": got,
                                "match": got == spec["expected_sha256"],
                                "asserted_by": spec["asserted_by"]}

    content_module_hashes = {name: sha256_file(REPO / p) for name, p in CONTENT_MODULES.items()}
    infra_module_hashes = {name: sha256_file(REPO / p) for name, p in INFRA_MODULES.items()}

    # Compare every module the frozen plan pins against what is on disk now, and classify
    # each difference rather than leaving a silent mismatch for a later reader to find.
    # exact_generation.py is EXPECTED to differ: Amendment A1's own
    # unresolved_scientific_decisions.remaining_items_are_execution_or_verification_only
    # list mandates two code changes to it (add the Mistral scorer, disable reserve
    # substitution), so its pinned hash records the pre-amendment state, not a requirement.
    # The content/parsing modules -- which determine what the model is asked and how its
    # answer is read -- must match exactly, and a mismatch there is a hard failure.
    plan_path = REPO / "configs/final_analysis_plan.json"
    pinned_modules = {}
    if plan_path.exists():
        pinned_modules = (json.loads(plan_path.read_text(encoding="utf-8"))
                         .get("pinned_provenance", {}).get("modules", {}))
    EXPECTED_TO_DIFFER = {"exact_generation.py"}
    module_comparison = {}
    content_modules_intact = True
    for name, want in pinned_modules.items():
        p = REPO / "src/silent_influence" / name
        got = sha256_file(p) if p.exists() else None
        matches = got == want
        expected_to_differ = name in EXPECTED_TO_DIFFER
        module_comparison[name] = {
            "pinned_sha256": want, "actual_sha256": got, "matches": matches,
            "difference_expected": expected_to_differ,
            "status": ("unchanged" if matches
                      else "changed_as_mandated_by_amendment_A1" if expected_to_differ
                      else "UNEXPECTED_CHANGE"),
        }
        if not matches and not expected_to_differ:
            content_modules_intact = False

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "environment": capture_environment(),
        "frozen_artifact_verification": frozen_check,
        "all_frozen_artifacts_match": all_frozen_match,
        "active_frozen_artifacts_match": active_frozen_match,
        "out_of_tree_reference_verification": narrative_check,
        "content_and_parsing_modules_sha256": content_module_hashes,
        "infrastructure_modules_sha256": infra_module_hashes,
        "plan_pinned_module_comparison": module_comparison,
        "content_and_parsing_modules_intact": content_modules_intact,
        "generator": GENERATOR,
        "scorers": SCORERS,
        "superseded_scorers": SUPERSEDED_SCORERS,
        "conditions": ["no_history", "self_low_2", "other_low_2", "unrelated_low_2",
                      "verbal_negative", "self_high_10"],
        "n_tasks_expected": 578, "n_scoring_calls_expected": 13872,
        "stage_manifests": {
            "generation": load_json_if_exists(out_dir / "manifest_generation.json"),
            "scoring": load_json_if_exists(out_dir / "manifest_scoring.json"),
            "preflight_gate_report": load_json_if_exists(out_dir / "preflight_gate_report.json"),
            "batching_equivalence_verdict": load_json_if_exists(
                out_dir / "batching_equivalence_verdict.json"),
            "adjudication_manifest": load_json_if_exists(
                REPO / "results/final_behavioral_study_adjudicated/manifest_adjudication.json"),
        },
    }

    out_path = out_dir / "run_integrity_manifest.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=str)

    print(f"all_frozen_artifacts_match: {all_frozen_match} "
         f"(active_frozen_artifacts_match: {active_frozen_match})")
    for name, v in frozen_check.items():
        print(f"  [{'OK' if v['match'] else 'MISMATCH'}] {name} ({v['status']}): {v['path']}")
    for name, v in narrative_check.items():
        tag = "N/A" if not v["reachable"] else ("OK" if v["match"] else "MISMATCH")
        print(f"  [{tag}] {name} (out-of-tree): {v['path']}")
    print(f"content_and_parsing_modules_intact: {content_modules_intact}")
    for name, v in module_comparison.items():
        print(f"  [{'OK' if v['matches'] else v['status']}] {name}")
    print(f"[save] {out_path}")
    narratives_ok = all(v.get("match", True) for v in narrative_check.values())
    return 0 if (all_frozen_match and content_modules_intact and narratives_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
