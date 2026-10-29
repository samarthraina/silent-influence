# Context controls and matched-history patching

The behavioral effect persists, but the selected internal states do not reliably transfer the positive-versus-negative feedback effect. Adding an explicit scoring rubric has different effects in the two models.

This release contains the completed follow-up experiments, frozen manifests, raw outputs, analysis code, tests, and a self-contained [HTML results briefing](graphs.html). Download the HTML and open it in a browser; no server or external assets are needed. The [original study](../../README.md#what-we-found) remains separate.

## Results

| Experiment | Llama 3.1 8B | Qwen3 8B |
|---|---:|---:|
| Positive minus negative history, unpatched | +2.84 points, 72 tasks | +3.23 points, 72 tasks |
| History effect, original → explicit rubric, matched tasks | 1.30 → 2.21, n = 29 | 1.77 → 0.73, n = 30 |
| Rubric attenuation, original minus explicit, 97.5% CI | −0.91 [−1.65, −0.21] | +1.03 [0.30, 1.80] |
| Selected layer minus L2, positive → negative, normalized, 97.5% CI | −0.021 [−0.149, 0.087], n = 67 | +0.023 [−0.040, 0.087], n = 68 |
| Selected layer minus L2, negative → positive, normalized, 97.5% CI | −0.007 [−0.116, 0.135], n = 67 | +0.022 [−0.007, 0.066], n = 68 |

Unpatched gaps are descriptive means, not pooled estimates from the original study. The calibration rows use the same complete tasks across both rubric arms. Marginal cell averages can use different denominators. The adjusted intervals cover two primary contrasts within each study, not every comparison across this release.

**Interpretation.** Behavioral dependence on the supplied history remains clear in these assays. Rubric clarification reduces it in Qwen and increases it in Llama, so calibration is a model-dependent contributor, not a complete account. Both matched-history patching studies are null at their selected sites. A confidence interval crossing zero does not establish equivalence or rule out effects at other tokens, layers, components, or readouts.

## What was tested

**Rubric calibration:** 30 fixed tasks, balanced across three datasets, × 2 models × 2 rubrics × 3 contexts = 360 units. Contexts are no history, self-low (2/10), and unrelated-low (2/10). The explicit arm inserts a fixed accuracy/completeness rubric into the original prompt. Question, frozen answer, history sentence, and output instruction remain identical. No reference answers or instruction to ignore history are added. The manipulation also changes prompt length and framing. See the [exact rubric and renderer](src/rba/calib.py), [sample metadata](artifacts/sample/sample_manifest_v1.json), and [run manifest](artifacts/calibration/run_manifest_v1.jsonl).

The primary per-task contrast is `(baseline − self-low)_original − (baseline − self-low)_explicit`. Positive values indicate attenuation. The task bootstrap uses 10,000 draws and seed 20261028. Complete-case estimates and bounds for missing planned outcomes are both retained. Llama has one capped output, leaving 29 complete primary contrasts; Qwen has 30. No invalid output is scored as zero.

**Matched-history patching:** the existing 72-task extension set, × 10 units per task, for each model. Both prompts contain history, differing in whether the prior self-directed rating is 10/10 or 2/10. At the final native input token, transplant the full hidden state from one condition into the other. Test both directions at Llama layer 24 or Qwen layer 27 and at the layer-2 control. Layer numbers are hidden-state indices: L24 is decoder block 23's output, L27 is block 26's output. The sites were inherited from earlier discovery, not newly selected on these outcomes. See [design and estimators](src/rba/mhp.py), [Llama manifest](matched_history_patching/mhp_manifest_v1.jsonl), and [Qwen manifest](matched_history_patching_qwen/mhp_qwen_manifest_v1.jsonl).

Each task has two unpatched baselines, four cross-condition patches, two no-op hooks, and two same-state patches. All 288 identity checks per model reproduce the corresponding baseline token hash. Llama has 718 valid and 2 capped outputs; Qwen has 720 valid outputs. The primary contrast is selected-layer normalized movement minus L2 movement on the same complete tasks. Movement is `(patched − target)/(source − target)`. It is neither a mediation fraction nor a percentage of decisions changed. Four zero-gap tasks per model are excluded from normalization. Bootstrap: 10,000 draws, seed 20261029.

The 71-task sensitivity excludes `arena_hard/2da7e53308a547d6`, which had engineering-smoke exposure before the full run. This exclusion does not change the qualitative result. The absolute-gap ≥ 1 sensitivity is also included. The legacy JSON field `excluded_tasks_pending_identity_investigation` holds the smoke exclusion in that sensitivity branch; no identity check failed.

## Reproduce the saved analyses on a CPU

From the repository root, Python 3.10+ and its standard library are sufficient:

```bash
python -B extensions/context_controls/scripts/verify_results.py
python -B extensions/context_controls/scripts/analyze_results.py
python -B extensions/context_controls/scripts/verify_results.py --compare-reanalysis
```

The first command independently checks all 1,800 final units, payload hashes, planned coverage, identity controls, and primary point estimates. The second recomputes all estimates and intervals into `extensions/context_controls/outputs/analysis/`, leaving recorded results untouched. The final command compares every field with the saved analysis, allowing floating-point differences up to 1e-12. No weights, credentials, network, or GPU are used.

With the root test dependencies installed:

```bash
python -B -m pytest extensions/context_controls/tests -q -p no:cacheprovider
```

The release tests exercise prompt invariance, validity and missingness, resume integrity, analysis, identity controls, and execution gates. They use mock generation or small CPU tensors, never real inference. Human annotation workflows and their private linkage files are outside this extension.

## Start here for further mechanistic work

1. Open [graphs.html](graphs.html), then inspect [Llama results](results/analysis/study_llama.json) and [Qwen results](results/analysis/study_qwen.json).
2. Read [the patching executor](scripts/run_mhp.py), [hook implementation](src/rba/legacy/patching.py), and [analysis](src/rba/mhp.py). The existing experiment patches only the final-input position at two layers per model; it is not a circuit search.
3. Use the original [mechanistic pipeline](../../mechanistic/) for earlier discovery and interventions. The earlier Llama positive intervention compared low history with no history. It cannot by itself identify a feedback-valence mechanism, because history presence also changes.
4. Freeze a new discovery/validation split and a targeted hypothesis before any new layer/token/component search. Keep these completed null results in the evidence record. Stronger evidence would connect a reproducible behavioral contrast to a specific causal component and validate the intervention on tasks not used for selection.

No new mechanistic hypothesis has been tested by this release. Frontier browser demonstrations are also outside its results.

## New GPU runs

Inference entry points are [run_calibration.py](scripts/run_calibration.py) and [run_mhp.py](scripts/run_mhp.py). They start blocked. Researchers must record their own execution approval in `artifacts/EXECUTION_GATES_v1.json` and create a new rental ledger with an approved stage allowance. The published file contains no previous approval or private billing data. Offline analysis does not use these gates.

Use fresh output directories under `outputs/`; never append to the released raw records. `Ledger` in [budget.py](src/rba/budget.py) supports `record_prior_spend`, an explicit `stage_caps` mapping, `open`, and `close`, or a bounded stage-specific `record_provisional_authorization`. Record rental start before setup and confirmed release after stopping the instance. These are accounting checks, not automatic provider shutdown. The historical default ceiling is 30 GPU hours with a 4-hour reserve; future studies need their own explicit resource plan.

For calibration, required gates are `gpu_budget_confirmed` and `research_execution_approved`; CLI arguments include ledger path, fresh store, stage cap, projected unit seconds, and timeout. For patching, required gates are `gpu_budget_confirmed` plus `mhp_spec_reviewed` or `mhp_qwen_spec_reviewed`; use `--model`, `--mode study`, `--out`, `--ledger`, `--stage`, `--stage-cap-hours`, and `--projected-task-seconds`. Each confirmed gate requires `evidence` and `confirmed_by`. `--help` lists all options without loading a model.

The runs used one A100 80 GB, bf16, SDPA, greedy generation, seed 42, batch size 1, and at most 512 new tokens. Qwen thinking was disabled. Model IDs and immutable revisions are in the manifests. [Recorded versions](results/environment/versions.json), [per-run metadata](results/environment/), and [GPU dependency pins](requirements-gpu.txt) describe the environment; installation still requires a compatible CUDA stack and access to the weights. The follow-up used torch 2.14.1+cu126 versus 2.12.0+cu126 in the original study. Same-score/text comparisons to historical outputs are provenance checks, not a claim of exact reproduction across environments.

## Provenance

Raw JSONL output files and frozen run manifests are preserved byte for byte. Public adaptations resolve inputs within this repository, neutralize administrative names, reset approvals, and keep future outputs separate. Calibration creates a separate execution manifest with current source hashes for new runs; the historical manifest is unchanged. The public patching entry point adds prompt-hash and pre-load budget checks and accepts an explicit stage cap. These changes do not alter the recorded experiment or its estimates.

[PUBLIC_PROVENANCE.json](PUBLIC_PROVENANCE.json) records source/adapted hashes. The root [artifact manifest](../../ARTIFACT_MANIFEST.json) covers the released files. Original code is under the root MIT license; benchmark text and generated records retain the terms in [third-party notices](../../THIRD_PARTY_NOTICES.md).
