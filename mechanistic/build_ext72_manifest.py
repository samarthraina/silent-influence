"""Freeze the 72-task mechanistic generalization manifest.

PROVENANCE, STATED PLAINLY. This extension was specified AFTER the mixed 24-task control
result was observed. It is prospective only with respect to the 72 tasks named here -- none
of which has been through any mechanistic intervention -- and it is NOT preregistered
relative to the control study whose outcome motivated it. That is recorded in the manifest
itself so the distinction survives without this file.

Selection inputs are restricted to task id, dataset and pair-validity. Delta magnitude,
score values, rationales, response content and every prior mechanistic result are excluded
by construction: the pool is built from the presence of a matched A5-valid no_history /
self_low_2 pair and nothing else, and the ordering key is the task id alone. Note this
deliberately differs from the earlier manifest, which DID use scores (endpoint band, delta
thresholds); repeating that here would let outcomes back into selection.

Seed: the literal string below, hashed to an integer, so the draw is reproducible from the
string alone.
"""
import collections
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT / "Code/GitHub/silent-influence"
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
import analyze_final_study as A

SEED_STRING = "mechanistic_extension_72_20260818"
SEED_INT = int.from_bytes(hashlib.sha256(SEED_STRING.encode()).digest()[:8], "big")
SMOKE = ("arena_hard", "4c7d8a034c4e40f6")
DATASETS = ["mtbench", "arena_hard", "wildbench"]
N_PER_DS = 24
OUT = HERE / "manifest"

prior = json.loads((OUT / "mech_task_manifest.json").read_text(encoding="utf-8"))
excluded = {SMOKE}
excluded |= {(p["dataset"], p["task_id"]) for p in prior["discovery"]}
excluded |= {(p["dataset"], p["task_id"]) for p in prior["validation"]}

records = A.load_records(ROOT / "final_analysis_workspace/merged_raw_results.jsonl")
pivot = A.pivot_scores(records)

# Pool: pair-validity metadata only. Scores are read nowhere in this file.
pool = []
for (scorer, ds, tid), cell in pivot.items():
    if scorer != "llama":
        continue
    if "no_history" not in cell or "self_low_2" not in cell:
        continue
    if (ds, tid) in excluded:
        continue
    pool.append({"dataset": ds, "task_id": tid})

rng = np.random.default_rng(SEED_INT)
selected, shortfalls = [], []
for ds in DATASETS:
    cand = sorted([p for p in pool if p["dataset"] == ds], key=lambda p: str(p["task_id"]))
    if len(cand) < N_PER_DS:
        shortfalls.append(f"{ds}: {len(cand)} available, need {N_PER_DS}")
        continue
    order = rng.permutation(len(cand))          # deterministic task-id shuffle
    selected += [cand[i] for i in sorted(order[:N_PER_DS])]

if shortfalls:
    print("STOP -- insufficient stratum, criteria NOT relaxed:")
    for s in shortfalls:
        print("  " + s)
    raise SystemExit(2)

keys = {(p["dataset"], p["task_id"]) for p in selected}
assert len(selected) == 72 and len(keys) == 72
assert not (keys & excluded), "overlap with excluded tasks"

manifest = {
    "record_id": "llama_mechanistic_extension_72_manifest",
    "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "scorer": "llama",
    "PROVENANCE": {
        "specified_after_observing_the_24_task_control_result": True,
        "preregistered_before_that_result": False,
        "statement": "This 72-task extension was specified after the mixed 24-task control "
                     "outcome was seen. The 72 tasks are themselves mechanistically unseen, "
                     "so the replication is prospective with respect to them, but the "
                     "decision to run it was outcome-motivated and must not be described "
                     "as preregistered.",
    },
    "selection": {
        "seed_string": SEED_STRING, "seed_int": SEED_INT,
        "method": "deterministic task-id shuffle within each dataset stratum",
        "n_per_dataset": N_PER_DS,
        "inputs_used": ["task_id", "dataset", "pair_validity"],
        "inputs_forbidden_and_unused": ["delta magnitude", "score values", "rationales",
                                        "response content", "prior mechanistic results"],
        "differs_from_prior_manifest": "no endpoint band and no delta threshold -- those "
                                       "would reintroduce outcome information",
        "excluded_tasks": {"smoke": 1, "discovery": len(prior["discovery"]),
                           "validation": len(prior["validation"]),
                           "total": len(excluded)},
        "pool_after_exclusions": len(pool),
    },
    "reused_without_retuning": {
        "layer": 24, "beta": 1.5, "alpha": 1.0,
        "direction_file": "out/control_discovery/steering_direction.pt",
        "random_direction_seed": 20260818,
        "no_coefficient_search": True, "no_layer_search": True,
        "no_window_search": True, "no_task_replacement": True,
    },
    "secondary_strata_analytical_only": {
        "high": "delta >= 2", "moderate": "0 < delta < 2", "nonresponsive": "delta <= 0",
        "used_in_selection": False,
        "note": "computed after this manifest was frozen; affects reporting only",
    },
    "frozen_before_any_model_call": True,
    "tasks": selected,
}
path = OUT / "mech_ext72_manifest.json"
path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
sha = hashlib.sha256(path.read_bytes()).hexdigest()
(OUT / "mech_ext72_manifest.sha256").write_text(f"{sha}  mech_ext72_manifest.json\n",
                                                encoding="utf-8")

per = collections.Counter(p["dataset"] for p in selected)
print(f"  seed string '{SEED_STRING}' -> int {SEED_INT}")
print(f"  excluded {len(excluded)}  pool {len(pool)}  selected {len(selected)}")
print(f"  per dataset: {dict(sorted(per.items()))}")
print(f"  overlap with prior manifests: {len(keys & excluded)}")
print(f"  sha256 {sha}")
print(f"  [save] {path}")
