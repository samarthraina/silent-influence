# silent-influence

Pipeline for measuring how minimal inter-agent context changes an LLM's evaluative
behavior. The manipulated variable is a **dyadic prior score**: the model is told how the
model it is about to evaluate previously scored *its* answers.

Phase 1 is experimental-design calibration. It fixes the protocol empirically — dose
shape over the full 1–10 range, rubric sensitivity, output-ordering sensitivity, dataset
and model coverage — before any result is scaled.

## Design invariants

Across prior-score conditions, **only the injected numeral changes**. The system prompt,
instruction, answer label, rubric, task, candidate response, and output schema are byte
identical. This is enforced in code, not by convention:

- `src/silent_influence/render.py` is the only place prompt text is assembled.
- `assert_score_invariance()` renders the condition-independent skeleton with a sentinel
  in place of the numeral and proves every arm equals that skeleton with its value
  substituted. `scripts/run_phase1.py` calls it before generating anything.
- `tests/test_prompt_invariance.py` runs it over every rubric × protocol × template
  combination, and asserts that identity wording and competition framing never appear.

`no_history` is a separate baseline, not a neutral arm. It answers whether a history is
present at all, which is a different question from what the history says.

## Layout

```
configs/            models, datasets, and one file per Phase 1 module
data/prompts/       pinned prompt sets
data/candidates/    pinned candidate responses (held fixed across conditions)
src/silent_influence/
  conditions.py     prior-context conditions as data
  templates.py      dyadic history wordings; each has exactly one {score} slot
  rubrics.py        grounded / minimal / anchored_legacy
  protocols.py      score_only / score_then_justification / justification_then_score
  render.py         the single prompt composer + the invariance proof
  datasets.py       dataset-agnostic loading and deterministic stratified sampling
  candidates.py     pinned candidate responses
  backends.py       hf (transformers) and stub
  parsing.py        tolerant JSON parsing with a typed failure status
  records.py        unit identity, seeds, atomic JSONL, truncation repair
  grid.py           config -> explicit unit list
  runner.py         resumable executor
scripts/            run, render examples, preflight checks, analysis
tests/              invariance, parsing, persistence
```

## Experimental unit

One JSONL line per `(dataset, prompt_id, candidate_response_id, judge_model,
evaluated_model, prior_context_condition, prior_score_value, rubric_variant,
output_protocol, history_template, backend, replicate)`. Each line carries the exact
rendered system and user prompts, the raw model output, the parsed score and rationale,
a parse status, the seed, the generation parameters, and the model identity.

**Nothing is aggregated at write time.** Every aggregate is derived by
`scripts/analyze_phase1.py`, which groups by dataset, model, rubric and protocol before
averaging anything.

## Usage

```bash
python scripts/run_phase1.py --config configs/phase1_smoke.yaml --out results/smoke --dry-run
python scripts/run_phase1.py --config configs/phase1_smoke.yaml --out results/smoke
python scripts/preflight_checks.py --config configs/phase1_smoke.yaml \
    --records results/smoke/records.jsonl --rerun-stats results/smoke/rerun_stats.json
python scripts/analyze_phase1.py --records results/smoke/records.jsonl --plot
python scripts/render_examples.py --config configs/phase1_smoke.yaml --diff score_1 score_10
python -m pytest tests/ -q
```

Runs are resumable. Rerunning the same command executes only missing units; a unit is
identified by its experimental keys, so an interrupted run costs at most one cell.

## Adding a dataset

Add a block to `configs/datasets.yaml` with a path and a field mapping, pin candidate
responses for it with `scripts/pin_candidates.py`, then name it in a run config. No code
change is required.
