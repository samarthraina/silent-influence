# A guide to the implementation

Start with the two standard-library examples, then follow a single recorded claim into
the code that produced it. The repository retains the original research layout so existing
relative paths and recorded artifacts remain interpretable.

## 1. Control the experiment

[`scaled_conditions.py`](../code/src/silent_influence/scaled_conditions.py) defines the six
conditions as immutable dataclass instances and constructs the scoring prompt. It uses
concatenation so braces in a candidate answer are never interpreted as formatting syntax.

[`compare_prompts.py`](../examples/compare_prompts.py) renders the same real question and
answer twice, then checks that removing exactly the history block restores the baseline.

[`final_study_messages.py`](../code/src/silent_influence/final_study_messages.py) handles
the model-specific message envelope. The OLMo scorer requires an explicit empty system
message to prevent its template from inserting additional content. Prompt text and message
wrapping are separate concerns.

## 2. Handle imperfect outputs explicitly

[`output_validity.py`](../code/src/silent_influence/output_validity.py) and
[`final_score_recovery.py`](../code/src/silent_influence/final_score_recovery.py) distinguish
valid scores, parse failures, and cap-truncated records. Missing values are not guessed.
[`records.py`](../code/src/silent_influence/records.py) supports keyed records and resumable
execution so interrupted runs do not silently duplicate units.

## 3. Match before aggregating

[`analyze_final_study.py`](../code/scripts/analyze_final_study.py) performs matched
comparisons, stratification, bootstrap uncertainty, attrition reporting, and robustness
analyses. It retains earlier design fields as history. For the final 234-task study the
balanced 12-cell result is stored in `complete_case.secondary`; the field name `primary`
alone must not be used to select the final estimate.

[`explore_results.py`](../examples/explore_results.py) is a short entry point for reading
those results. It checks cell membership, counts, and consistency before displaying an
estimate. It does not rerun the bootstrap.

## 4. Measure what explanations mention

[`merge_silence.py`](../silence/merge_silence.py) computes inter-annotator agreement before
joining the condition key. [`compare_human.py`](../silence/compare_human.py) verifies text
and item identity before comparing the completed human annotations. The condition key is
included for reproducibility; it was withheld from the annotation process until agreement
was computed.

## 5. Intervene on the representation

The [`mechanistic/`](../mechanistic/) directory contains task manifests, readout discovery,
activation patching, and controls. Identity controls, early-layer controls, and the tests
of a learned direction are essential parts of this code path. The original reference
Jacobian Lens is kept in [`third_party/`](../third_party/), with its license and provenance.

## 6. Follow a figure back to evidence

[`tools/build_assets.py`](../tools/build_assets.py) renders the repository graphics from
saved numerical artifacts. The original paper figure builders remain in
[`code/figures/`](../code/figures/). Existing example rasters and new vector examples have
different production paths; neither is a statistical sample selected independently of
outcomes.

## Development checks

```bash
python -m pip install -r requirements-test.txt
python tools/run_tests.py
python verify_package.py
```

The first command installs CPU test dependencies, including PyTorch for small synthetic
tensors. No model weights are downloaded by the tests. The nine documented exclusions
require research records outside this release; they are not silently marked as passing.
Default CI runs the same command. Passing locally does not imply that a remote CI run has
already occurred.

For intentional release changes, update files first, inspect the diff, and explicitly run
`python tools/build_manifest.py`. Integrity verification never rewrites its own baseline.

## Execution boundaries

The public examples and verifier are portable standard-library Python. Most model runners
require a separately prepared GPU environment. Historical selectors that require the
pilot workspace are provenance tools rather than quick-start entry points. See
[reproduction](../REPRODUCIBILITY.md) and [omissions](../OMISSIONS.md) before executing them.


## Context-control follow-up

The context-control extension contains the calibration renderer, matched-history patching executor, resumable record storage, tests, and reproducible analyses. See the [methods, results, and commands](../extensions/context_controls/README.md) and [self-contained graph briefing](../extensions/context_controls/graphs.html).
