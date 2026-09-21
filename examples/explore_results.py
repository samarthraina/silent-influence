"""Explore recorded study results without installing packages or loading a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]
MODELS = {"llama": "Llama 3.1 8B", "qwen": "Qwen3 8B",
          "gemma": "Gemma 2 9B", "olmo32b": "OLMo 3.1 32B"}
DATASETS = ("mtbench", "arena_hard", "wildbench")


def read_json(relative_path: str, root: Path = ROOT):
    return json.loads((root / relative_path).read_text(encoding="utf-8"))


def summarize(root: Path = ROOT) -> dict:
    """Validate the 12-cell design and expose the recorded complete-case estimate.

    The historical key `secondary` contains the final 12-cell estimator. The
    `primary` key belongs to an earlier two-dataset design. Neither key's name
    determines which estimate represents the final experiment.
    """
    result = read_json("results/behavioral/final_analysis_results.json", root)
    headline = read_json("results/figure_inputs/headline_metrics.json", root)
    estimate = result["complete_case"]["secondary"]
    expected = {f"{dataset}|{model}" for dataset in DATASETS for model in MODELS}
    if set(estimate["cell_means"]) != expected or set(estimate["cell_n"]) != expected:
        raise ValueError("The recorded result does not contain the expected 12 cells")
    if any(n <= 0 for n in estimate["cell_n"].values()):
        raise ValueError("An empty cell cannot contribute to the balanced estimate")
    macro = fmean(estimate["cell_means"].values())
    if abs(macro - estimate["macro_average"]) > 1e-12:
        raise ValueError("Recorded cell means disagree with the macro estimate")
    if round(macro, 3) != headline["primary_contrast"]["mean_shift_points"]:
        raise ValueError("Headline disagrees with the underlying recorded estimate")
    n_pairs = sum(estimate["cell_n"].values())
    if n_pairs != headline["primary_contrast"]["n_matched_pairs"]:
        raise ValueError("Recorded matched-pair counts disagree")
    models = {}
    for key, label in MODELS.items():
        models[key] = {
            "name": label,
            "mean_shift": fmean(estimate["cell_means"][f"{d}|{key}"] for d in DATASETS),
            "matched_pairs": sum(estimate["cell_n"][f"{d}|{key}"] for d in DATASETS),
        }
    return {
        "basis": "complete cases, equal weight across 12 dataset-by-scorer cells",
        "contrast": "no_history - self_low_2",
        "mean_shift": macro,
        "ci95": [estimate["ci_95"]["ci_low"], estimate["ci_95"]["ci_high"]],
        "matched_pairs": n_pairs,
        "tasks": headline["counts"]["tasks"],
        "judgments": headline["counts"]["logical_judgments"],
        "models": models,
        "context_unmentioned": {
            "count": headline["silence"]["headline_n_silent"],
            "denominator": headline["silence"]["headline_denominator"],
            "basis": "self-low justifications on which both primary annotators agreed",
        },
    }


def matched_example(root: Path = ROOT) -> dict:
    """Return a recorded, explicitly outcome-selected example with intact answer bytes."""
    candidates = read_json("results/figure_inputs/real_example_candidates.json", root)
    item = next(e for e in candidates["examples"]
                if e["dataset"] == "mtbench" and str(e["task_id"]) == "101"
                and e["scorer"] == "llama")
    if hashlib.sha256(item["frozen_answer"].encode()).hexdigest() != item["answer_sha256"]:
        raise ValueError("Example answer no longer matches its recorded hash")
    return item


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, help="show one scorer's recorded summary")
    parser.add_argument("--example", action="store_true", help="show the recorded race example")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()
    result = matched_example() if args.example else summarize()
    if args.model and not args.example:
        result = result["models"][args.model]
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if args.example:
        print("RECORDED EXAMPLE | MT-Bench 101 | Llama 3.1 8B")
        print("Chosen after inspecting outcomes; illustrative, not an effect-size estimate.\n")
        print("Question:", result["task_question"])
        print("Same answer in every condition:", result["frozen_answer"])
        for key, condition in result["conditions"].items():
            print(f"\n{key}: {condition['score']:g}/10")
            print("History:", condition["contextual_sentence"] or "None")
            print("Recorded justification:", condition["justification"])
        return
    if args.model:
        print(f"{result['name']}: {result['mean_shift']:+.3f} points, "
              f"{result['matched_pairs']} matched pairs, equal weight across three datasets")
        return
    print("SILENT INFLUENCE | Recorded results")
    print(f"{result['tasks']} tasks | 4 scorers | {result['judgments']:,} judgments")
    print(f"\nScore decrease: {result['mean_shift']:.3f} points on a 0-10 scale")
    print(f"Recorded 95% CI: [{result['ci95'][0]:.3f}, {result['ci95'][1]:.3f}]")
    print(f"Matched pairs: {result['matched_pairs']}; {result['basis']}")
    for model in result["models"].values():
        print(f"  {model['name']:<16} {model['mean_shift']:+.3f}  n={model['matched_pairs']}")
    silence = result["context_unmentioned"]
    print(f"\nContext unmentioned: {silence['count']}/{silence['denominator']} "
          f"({100 * silence['count'] / silence['denominator']:.1f}%)")
    print("Denominator:", silence["basis"])
    print("\nThis reads saved results. It performs no model inference or new bootstrap.")


if __name__ == "__main__":
    main()
