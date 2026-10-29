# Reproducibility

The **analysis path** uses saved results to rebuild tables, figures, and annotation
summaries on a CPU. The **production path** reruns generation, scoring, annotation, or
patching and requires model weights and suitable GPUs. Some upstream inputs are omitted;
see [OMISSIONS.md](OMISSIONS.md) before attempting a full reconstruction.

For this public package, the two standard-library examples, checksum verifier, and local
release test suite were exercised. The suite passed **634 tests with 9 documented
exclusions**. No models were downloaded and no new research experiments were run.

The analysis and production commands below originate in the retained research package.
That package records that section 1 was exercised from a fresh extraction and section 2
was checked against script argument parsers and the executed wrappers. Those historical
checks are distinct from the checks performed while preparing this repository.

---

## 0. Environment

```bash
python -m pip install -r requirements-analysis.txt
python verify_package.py
```

`verify_package.py` checks the file inventory and SHA-256 of every shipped artifact against
`ARTIFACT_MANIFEST.json` and exits non-zero on any mismatch. Python 3.10 or newer.

The core analysis inputs are shipped **uncompressed**. Upstream-only scripts and omitted
inputs are listed in `OMISSIONS.md`. Two retained result exports are gzipped:
`results/behavioral/results.csv.gz`, a convenience export no script reads, and
`results/behavioral/per_scorer_llama.jsonl.gz`, which `mechanistic/test_mech_adapter.py`
opens through `gzip.open`.

`OMISSIONS.md` lists everything deliberately left out, with sizes, hashes, and the command
that regenerates it.

---

## 1. Analysis path (CPU, no weights, no network)

### 1.1 Behavioural tables

```bash
python code/analysis/make_a9_tables.py
```

No arguments. Reads `results/behavioral/final_analysis_results.json`; writes
`results/tables/t1_primary_headline.csv` through `t8_robustness.csv`.

```bash
python code/analysis/cumulative_effects.py
python code/analysis/olmo_descriptive_audit.py
```

No arguments. Both read `results/behavioral/merged_raw_results.jsonl` and write `t9`–`t13`.
`cumulative_effects.py` also writes `_ecdf_series.npy` at the package root; that file is an
output, is read by nothing, and is not shipped.

### 1.2 Behavioural figures

```bash
python code/analysis/make_a9_figures.py
python code/analysis/make_ecdf_figure.py
python code/analysis/make_olmo_figure.py
```

No arguments. Output: `figures/analysis/f1_primary_12_cells.pdf` … `f6_olmo_descriptive.pdf`.

### 1.3 Paper figures

```bash
python code/figures/make_fig2_results_final.py
python code/figures/make_fig4_mechanistic_evidence_v3.py
python code/figures/make_fig4_mechanistic_evidence_v4.py
python code/figures/make_fig3_matched_example.py
```

No arguments. Inputs `results/figure_inputs/*` and
`results/mechanistic/readout_layer_summary.json`; outputs into `figures/paper/`. Each builder
asserts its displayed values against the source artifact and aborts on drift.

`make_fig3_matched_example.py` builds a vector matched-example figure. It does **not**
reproduce the raster the research paper uses; see `figures/paper_exact/PROVENANCE.md`.

`code/figures/build_figure_inputs.py` is shipped as provenance for `results/figure_inputs/`.
It expects the full upstream workspace layout and does not run against this package.

### 1.4 Silence annotation results

Note the flag names: `merge_silence.py` takes `--out-dir`, the other two take `--out`.

```bash
python silence/merge_silence.py --j1 silence/judge_J1_raw.jsonl --j2 silence/judge_J2_raw.jsonl --key silence/silence_key.jsonl --out-dir results/silence
```
```bash
python silence/analyze_J3.py --j1 silence/judge_J1_raw.jsonl --j2 silence/judge_J2_raw.jsonl --j3 silence/judge_J3_gptoss_raw.jsonl --items silence/blinded_items_J1.jsonl --key silence/silence_key.jsonl --human-dir silence/human_validation --out results/silence/j3_agreement_report.json
```
```bash
python silence/compare_human.py --human-a silence/human_validation/human_validation_A_completed.csv --human-b silence/human_validation/human_validation_B_completed.csv --items silence/blinded_items_J1.jsonl --j1 silence/judge_J1_raw.jsonl --j2 silence/judge_J2_raw.jsonl --j3 silence/judge_J3_gptoss_raw.jsonl --out results/silence/human_vs_judges.json
```

`merge_silence.py` computes every agreement statistic **before** it joins the key; the
ordering is enforced in the script. `compare_human.py` verifies each annotated
`rationale_text` character for character against the blinded item before comparing any label.

### 1.5 Merged behavioural integrity

```bash
python code/scripts/merged_integrity.py
```

Re-derives the expected unit sets over all 4,680 records and prints
`MERGED_INTEGRITY_PASS: True`.

### 1.6 Vendored Jacobian Lens import check

```bash
PYTHONPATH=third_party/jacobian-lens python -c "import jlens; print(jlens.JacobianLens)"
```

### 1.7 Tests

Install the test dependencies as well as the analysis dependencies. Tests use small CPU
tensors and a mocked generation path; they do not load model weights.

```bash
python -m pip install -r requirements-test.txt
python tools/run_tests.py
```

Verified locally with Python 3.12: **634 passed, 9 deselected**, exit code 0. The runner is
portable across macOS, Linux, and Windows and includes eight checks added for the public
examples and integrity verifier. The nine exclusions are listed in `release_tests.txt`
and individually explained in [the test guide](code/tests/README_TESTS.md).

The original package recorded 626 passing tests with the same nine exclusions. Running
`python -m pytest code/tests -q` without those exclusions additionally attempts historical
checks that need working notes and a withheld freeze record. Those inputs are not in this
release; failure of those checks does not indicate a new model result. In addition, two
credential-like strings are redacted from four earlier prompt pools. Historical freeze
hashes retain the original values and do not match those public copies. See
`PUBLIC_REDACTIONS.json`; final scoring inputs and results are unchanged.

---

## 2. Production path (GPU, model weights required)

### 2.1 Models and pinned revisions

| Role | Key | Model | Revision |
|---|---|---|---|
| Agent A, generator | `olmo3` | `allenai/Olmo-3-7B-Instruct` | `6e5971d9eba42665f5bd5a0fcf047f299ce1dccc` |
| Agent B, scorer | `llama` | `meta-llama/Llama-3.1-8B-Instruct` | `0e9e39f249a16976918f6564b8830bc894c89659` |
| Agent B, scorer | `qwen` | `Qwen/Qwen3-8B` | `b968826d9c46dd6066d109eabc6255188de91218` |
| Agent B, scorer | `gemma` | `google/gemma-2-9b-it` | `11c9b309abf73637e4b6f9a3fa1e92e615547819` |
| Agent B, scorer | `olmo32b` | `allenai/Olmo-3.1-32B-Instruct` | `ac0587e4a7744a551c059d8cd17ba220bc940dae` |
| Silence judge J1 | — | `Qwen/Qwen3-8B` | as above |
| Silence judge J2 | — | `google/gemma-2-9b-it` | as above |
| Silence judge J3 | — | `openai/gpt-oss-20b` | `6cee5e81ee83917806bbde320786a8fb61efebee` |
| Jacobian Lens (fitted) | — | `neuronpedia/jacobian-lens` | `a4114d7752d11eb546e6cf372213d7e75526d3a1` |

`google/gemma-2-9b-it` is gated and needs an accepted licence on its model page.

### 2.2 Reference software record, and stage-specific hardware

The authoritative reference software record is
`code/orchestration/production_environment.json`, captured during the **A100 OLMo-32B scoring
stage**. The behavioural evaluation was executed as separate single-GPU jobs on
stage-specific hardware: the OLMo-32B scorer used an NVIDIA A100-SXM4-80GB, Llama-3.1-8B and
Qwen3-8B used RTX 3090 devices, and Gemma-2-9B-IT used an RTX 4090. Across these scoring
stages, the pinned model revisions, prompts, decoding policy, batch-size constraints, and core
software versions were reproduced. The J3 silence judge used a separate RTX A6000 environment
under vLLM and is documented independently in section 2.6.

Software versions as captured in that record:

| | |
|---|---|
| Python | 3.12.13 (conda-forge, GCC 14.3.0) |
| Platform | Linux 5.15.0, glibc 2.39 |
| torch | **2.12.0+cu126** |
| transformers | **5.15.0** |
| accelerate | 1.14.0 |
| safetensors | 0.8.0 |
| huggingface_hub | 1.18.0 |
| numpy | 2.4.6 |
| GPU of the captured stage | 1 × NVIDIA A100-SXM4-80GB |

The last row is **the device represented by this particular captured environment**, the
OLMo-32B scoring stage. It is not the only GPU used in the study. Verified devices per stage:

| Stage | Verified device | Source archive |
|---|---|---|
| Scoring, OLMo-3.1-32B | NVIDIA A100-SXM4-80GB | `a100` |
| Scoring, Llama-3.1-8B | NVIDIA GeForce RTX 3090 | `llama` |
| Scoring, Qwen3-8B | NVIDIA GeForce RTX 3090 | `qwen` |
| Scoring, Gemma-2-9B-IT | NVIDIA GeForce RTX 4090 | `gemma` |
| Silence judge J3 | NVIDIA RTX A6000, 48 GB | `j3_gptoss` |
| Silence judges J1, J2 | not recorded | `silence` |
| Llama mechanistic | not recorded | `mech_llama` |
| Cross-model mechanistic | not recorded | `crossmodel` |

Rows marked "not recorded" have archives that capture peak GPU memory but no device string.
No device is inferred for them.

**`torch 2.12.0+cu126` is a CUDA-specific build, not the default PyPI wheel.** The `+cu126`
local version identifier is not resolvable from PyPI, and `pip install torch==2.12.0` will
fetch whatever CUDA variant is current for your platform, which will not reproduce this
environment. Install it from the CUDA 12.6 index:

```bash
pip install torch==2.12.0 --index-url https://download.pytorch.org/whl/cu126
```

`production_environment.json` itself is left byte-exact: it is a valid historical record of
its own stage.

### 2.3 Decoding, held invariant across all conditions

Greedy, `do_sample=False`, seed 42, batch size 1. Token ceiling 512 for the three 8–9B scorers
and 2048 for the 32B scorer. The parser is identical across conditions.

### 2.4 Task selection is two distinct stages

These are different selectors and are often confused:

```bash
# stage 1: build the 578-task GENERATION POOL (Agent A writes one answer per task)
python code/scripts/select_final_tasks.py
```

`select_final_tasks.py` takes **no command-line arguments**; its inputs and seed are module
constants, and the seed appears in the output filename
(`data/prompts/final_tasks_seed20260817.json`). It needs a pilot artifact that is not shipped:
set `SI_PILOT_FROZEN`, or place the file at `code/data/pilot/frozen_olmo_answers.json`. That
path affects only provenance reporting about previously-used task ids.

```bash
# stage 2: select the 234-task SCORING MANIFEST used by the final study
python code/scripts/select_a9_scoring_tasks.py --manifest-file <manifest.json> --out <dir>
```

Flags: `--manifest-file --out --skip-hash-check`.

### 2.5 Generation and scoring

**Neither script accepts `--config`.** Both take explicit flags.

```bash
python code/scripts/generate_final_candidates.py --out <dir> --candidates-out <file>
```

Full flag set: `--dry-run --limit --stub --manifest-file --skip-hash-check --out
--candidates-out`.

```bash
python code/scripts/verify_exact_generation_gate.py --smoke-tasks <n> --out <dir>
```

```bash
python code/scripts/run_final_scoring.py --scorers llama --pin-batch-size 1 --out <dir>
```

Full flag set: `--candidates-file --out --task-selection --pin-batch-size --olmo-gate
--calibration --scorers --batching-verdict --batch-size --skip-hash-check --no-resume --limit
--dry-run --stub`. This is exactly what the archived wrappers ran, once per scorer, with
`--pin-batch-size 1` and no `--calibration`.

```bash
python code/scripts/verify_final_preflight_gate.py --manifest-file <manifest.json> --out <dir>
```

```bash
python code/scripts/analyze_final_study.py --records-complete-case <raw.jsonl> --out <dir>
```

Full flag set: `--records-adjudicated --records-complete-case --out --n-bootstrap
--skip-figures`.

### 2.6 Silence annotation

J1 requires the model, the revision, and `--disable-thinking`; without the last flag Qwen3's
thinking mode consumes the token budget and nothing parses.

```bash
python silence/run_silence_judge.py --judge J1 --disable-thinking --model Qwen/Qwen3-8B --revision b968826d9c46dd6066d109eabc6255188de91218 --items silence/blinded_items_J1.jsonl --out silence/judge_J1_raw.jsonl
```
```bash
python silence/run_silence_judge.py --judge J2 --model google/gemma-2-9b-it --revision 11c9b309abf73637e4b6f9a3fa1e92e615547819 --items silence/blinded_items_J2.jsonl --out silence/judge_J2_raw.jsonl
```
```bash
python silence/run_j3_gptoss.py --items silence/blinded_items_J1.jsonl --out silence/judge_J3_gptoss_raw.jsonl --revision 6cee5e81ee83917806bbde320786a8fb61efebee --dtype bfloat16 --gpu-util 0.92 --batch-size 10 --seed 20260821
```

All three are resumable and open only the blinded items and the rubric.

### 2.7 Mechanistic pipeline

Every mechanistic command needs four things on `PYTHONPATH`: the study source, the study
scripts, the `mechanistic/` directory, and the vendored Jacobian Lens.

```bash
export PYTHONPATH=code/src:code/scripts:mechanistic:third_party/jacobian-lens
```

On Windows use `set PYTHONPATH=code\src;code\scripts;mechanistic;third_party\jacobian-lens`.

```bash
python mechanistic/build_mech_manifest.py
```
```bash
python mechanistic/run_readout.py --manifest mechanistic/manifest/mech_task_manifest.json --candidates code/data/candidates/final_olmo_answers.json --out-dir <out>/discovery
```
Flags: `--manifest --candidates --out-dir --lens-repo --lens-file --lens-revision --layer-lo
--layer-hi`. The three `--lens-*` defaults are the pinned fitted-lens repo, file, and revision
in section 2.1.

```bash
python mechanistic/run_validation.py --manifest mechanistic/manifest/mech_task_manifest.json --candidates code/data/candidates/final_olmo_answers.json --window-file <out>/discovery/SELECTED_WINDOW.json --out-dir <out>/validation
```
Flags: `--manifest --candidates --window-file --out-dir --early-layer`.

```bash
python mechanistic/build_direction.py --manifest mechanistic/manifest/mech_task_manifest.json --candidates code/data/candidates/final_olmo_answers.json --window-file <out>/discovery/SELECTED_WINDOW.json --out-dir <out>/control_discovery
```
```bash
python mechanistic/run_control_validation.py --manifest mechanistic/manifest/mech_task_manifest.json --candidates code/data/candidates/final_olmo_answers.json --freeze <out>/control_discovery/DIRECTION_FREEZE.json --direction <out>/control_discovery/steering_direction.pt --out-dir <out>/control_validation
```
```bash
python mechanistic/build_ext72_manifest.py
python mechanistic/run_ext72.py --manifest mechanistic/manifest/mech_ext72_manifest.json --candidates code/data/candidates/final_olmo_answers.json --freeze <out>/control_discovery/DIRECTION_FREEZE.json --direction <out>/control_discovery/steering_direction.pt --out-dir <out>/ext72
```
```bash
python mechanistic/dump_vocab.py --out <out>/jlens_tokens/vocab_strings.json
python mechanistic/run_jlens_tokens.py --manifest mechanistic/manifest/mech_ext72_manifest.json --candidates code/data/candidates/final_olmo_answers.json --out-dir <out>/jlens_tokens
```
```bash
python mechanistic/analyze_jlens_tokens.py --in-dir <out>/jlens_tokens --out-dir <out>/jlens_tokens_analysis --tokenizer-vocab results/mechanistic/jlens/vocab_strings_repaired.json
python mechanistic/build_layer_tables.py --tensor-dir <out>/jlens_tokens --vocab results/mechanistic/jlens/vocab_strings_repaired.json --out-dir <out>/jlens_layer_tables
```
```bash
python mechanistic/run_crossmodel.py --stage discovery --scorer gemma --manifest mechanistic/manifest/crossmodel_discovery_12.json --candidates code/data/candidates/final_olmo_answers.json --out-dir <out>
python mechanistic/run_crossmodel.py --stage validation --scorer gemma --manifest mechanistic/manifest/mech_ext72_manifest.json --candidates code/data/candidates/final_olmo_answers.json --out-dir <out> --layer-file <out>/SELECTED_LAYER_gemma.json
```
Repeat with `--scorer qwen`. Gemma must fully unload before Qwen loads; the archived wrapper
runs them as separate processes for that reason.

The analysis stages consume the shipped records directly and need no GPU:
`analyze_validation.py`, `analyze_ext72.py`, `analyze_control.py`, `analyze_crossmodel.py`.

---

## 3. Statistical specification

- Estimator: equal-dataset × equal-scorer macro average over 12 cells, each weighted 1/12.
- Interval: task-clustered, dataset-stratified bootstrap, 10,000 replicates, seed 20260818.
  Configuration in `results/behavioral/bootstrap_config.json`.
- Measurement basis: complete-case. Output validity follows the cap-aware A5 rule in
  `code/src/silent_influence/output_validity.py`; `capped_incomplete` outputs never enter
  score recovery.
- Diagnostic contrasts are unadjusted for multiplicity and labelled non-confirmatory in the
  analysis output.
- A queue of 36 score-recovery items is unadjudicated. Those items enter **no** estimate
  reported in the paper or shipped here, and no adjudication was performed for this package.


## Context-control follow-up

The context-control extension includes 1,800 raw final units, exact manifests, CPU-only reanalysis, and gated inference entry points. See the [methods, results, and commands](extensions/context_controls/README.md) and [self-contained graph briefing](extensions/context_controls/graphs.html).
