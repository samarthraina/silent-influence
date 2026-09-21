"""Print the exact prompt difference for a recorded matched example."""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code/src"))
from silent_influence.scaled_conditions import render_prompt, resolve
from explore_results import matched_example


def main() -> None:
    example = matched_example()
    question, answer = example["task_question"], example["frozen_answer"]
    before = render_prompt(question, answer, resolve("no_history"))
    after = render_prompt(question, answer, resolve("self_low_2"))
    sentence = resolve("self_low_2").added_context
    if after.replace(sentence + "\n\n", "", 1) != before:
        raise ValueError("More than the history sentence changed")
    print("Exact study renderer; no model inference. Only the history block changes.\n")
    print("\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                    fromfile="no_history", tofile="self_low_2", lineterm="")))


if __name__ == "__main__":
    main()
