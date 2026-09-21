# Claim to artifact map

Recorded findings traced to source artifacts and generating scripts. Paths are relative
to this package. This map retains the research record's status labels; complete-case
coverage and exploratory selection limits are explained in `docs/RESULTS.md`.

Status column: **C** confirmatory, **D** descriptive, **E** exploratory.

---

## 1. Behavioural results

| # | Claim | Value | 95% CI | n | St. | Source artifact | Generating script |
|---|---|---|---|---|---|---|---|
| 1 | Primary effect, `no_history − self_low_2`, 12 cells at 1/12 | **+1.170** | [1.099, 1.243] | 900 pairs | C | `results/behavioral/final_analysis_results.json` → `complete_case.secondary` | `code/scripts/analyze_final_study.py` |
| 2 | Task-level fraction positive | 94.0% | — | 233 tasks | C | same → `complete_case.task_level_distribution` | same |
| 3 | Task-level fraction ≥ +1.0 | 65.2% | — | 233 | C | same | same |
| 4 | Task-level fraction ≥ +2.0 | 15.5% | — | 233 | C | same | same |
| 5 | Task-level median (IQR) | +1.13 (0.75–1.63) | — | 233 | D | same | same |
| 6 | By scorer | gemma +0.453 · olmo32b +0.908 · llama +1.595 · qwen +1.724 | see note below | 4 scorers | C | `results/tables/t2_primary_by_scorer.csv` | `code/analysis/make_a9_tables.py` |
| 7 | By dataset | mtbench +1.026 · wildbench +1.138 · arena_hard +1.345 | see note below | 3 datasets | C | `results/tables/t3_primary_by_dataset.csv` | same |
| 8 | Scorer × dataset grid | 12 cells | — | 12 | C | `results/tables/t4_primary_scorer_x_dataset.csv` | same |
| 9 | Robustness R1, 10% trimmed macro | +1.106 | [1.048, 1.181] | 12 cells | C | `final_analysis_results.json` → `complete_case.robustness.R1_trimmed_mean` | `analyze_final_study.py` |
| 10 | Robustness R2, leave-one-task-out range over 234 refits | 0.024 | — | 234 refits | C | same → `complete_case.robustness.R2_leave_one_task_out` | same |
| 11 | Sensitivity S1, primary without the 32B scorer | +1.257 | [1.188, 1.329] | 9 cells | C | same → `complete_case.S1_three_scorer_sensitivity` | same |
| 12 | 32B-scorer replication | +0.908 | — | 218 pairs | C | same → `complete_case.pooled_summaries.scorer_wise` | same |
| 13 | Cumulative effect-size table | thresholds 1.0–3.0 | — | 233 | D | `results/tables/t9_cumulative_effect_sizes.csv` | `code/analysis/cumulative_effects.py` |
| 14 | 32B descriptive audit | quantiles, top/bottom 20 | — | 218 | D | `results/tables/t11`–`t13` | `code/analysis/olmo_descriptive_audit.py` |

The scorer and dataset means above give equal weight to cells. The scorer table also
contains a separate pair-weighted estimate and interval: for OLMo 32B, 0.9007
[0.7526, 1.0552]. These intervals must not be attached to the equal-cell means.

### Diagnostic context conditions

Pooled, pair-weighted, **unadjusted for multiplicity**, labelled non-confirmatory in the
analysis output. Source for all eight rows: `final_analysis_results.json` → `complete_case.diagnostics`,
tabulated in `results/tables/t6_diagnostic_contrasts.csv`.

| Contrast | Mean | 95% CI | n |
|---|---|---|---|
| `no_history − self_low_2` | +1.169 | [+1.099, +1.243] | 900 |
| `no_history − other_low_2` | +0.592 | [+0.534, +0.651] | 681 |
| `no_history − unrelated_low_2` | +0.894 | [+0.816, +0.973] | 683 |
| `no_history − verbal_negative` | +1.193 | [+1.105, +1.280] | 683 |
| `other_low_2 − self_low_2` | +0.656 | [+0.592, +0.720] | 687 |
| `unrelated_low_2 − self_low_2` | +0.363 | [+0.291, +0.435] | 688 |
| `self_high_10 − self_low_2` | +2.282 | [+2.200, +2.364] | 688 |
| `self_high_10 − no_history` | +1.009 | [+0.950, +1.066] | 681 |

The four non-primary conditions were not run for the 32B scorer, so their contrasts rest on three
scorers rather than four; the `n` column reflects this.

### Parsing and validity

| Quantity | Value | Source |
|---|---|---|
| Records in the final study | 4,680 | `results/behavioral/merged_raw_results.jsonl` |
| A5-valid records | 4,584 (97.9%) | `results/tables/t7_validity_by_scorer_condition.csv` |
| Parse-failure audit | per-record | `results/behavioral/parse_failure_audit.csv`, `parse_failure_report.md` |
| Integrity check | pass | `code/scripts/merged_integrity.py` |

---

## 2. Silence annotation

| # | Claim | Value | Source artifact | Generating script |
|---|---|---|---|---|
| 15 | `self_low_2` rationales with no reference to the supplied history | **98.4%** (898/913) | `results/silence/silence_summary.json` | `silence/merge_silence.py` |
| 16 | Same, restricted to items whose own delta was ≥ 2 points | 97.9% (284/290) | same | same |
| 17 | `no_history` false-positive floor | 0.11% (1/923) | same | same |
| 18 | J1 vs J2, four-way label | 98.4%, κ = 0.532 | `results/silence/agreement.json` | same |
| 19 | J1 vs J2, binary context mention | 98.5%, κ = 0.560 | same | same |
| 20 | Discordant items excluded, unadjudicated | 30 | `results/silence/disagreements_for_adjudication.csv` | same |
| 21 | J3 integrity: 1,872/1,872 items, unique ids, parse success | 1,869 / 1,872 = 99.84% | `results/silence/j3_agreement_report.json` | `silence/analyze_J3.py` |
| 22 | J3 vs the frozen J1/J2 consensus | 99.78%, κ = 0.866 | same | same |
| 23 | Three-judge unanimity | 1,829 / 1,863 | same | same |
| 24 | Human inter-annotator, four-way | 99.17%, κ = 0.830, 1 disagreement | `results/silence/human_vs_judges.json` | `silence/compare_human.py` |
| 25 | Human inter-annotator, binary context | 100.0%, κ = 1.000 | same | same |
| 26 | J3 vs both human annotators, binary context | 100.0% on all 120 items | same | same |
| 27 | J3 by condition after unblinding | `self_low_2` 1.82% · `no_history` 0.11% | `results/silence/j3_agreement_report.json` → `unblinded_rates` | `silence/analyze_J3.py` |

Rubric: `silence/judge_prompt.py`, sha256
`21518e56188743049594791345b6a3691e78b8b0539da3d8107e71bacd4013be`, byte-identical for all
three judges. Blinded inputs: `silence/blinded_items_J1.jsonl` (1,872 unique items, fields
exactly `item_id` and `rationale_text`).

**One cross-reference to note.** The `human_validation` block inside
`results/silence/j3_agreement_report.json` is an inventory check that `analyze_J3.py` performs
on the file names `human_validation_A.csv` / `human_validation_B.csv`. Those are the **blank
templates**, which are not shipped, so the block reports them as absent and
`comparison_possible: false`. That is correct and expected: the real human comparison uses the
completed files (`human_validation_{A,B}_completed.csv`) and lives in
`results/silence/human_vs_judges.json`, produced by `silence/compare_human.py`. No agreement
statistic in either file depends on that block.

The single human four-way disagreement, `sil_5162f0bf59bd4305`, is **unresolved**: one
annotator labelled it `A`, the other `U`, both marked context mentioned and both quoted the
same span. No adjudicated label has been assigned; the item is excluded from human-consensus
figures and is marked `UNRESOLVED` in `results/silence/human_vs_judges.items.csv`.

---

## 3. Mechanistic results (Llama-3.1-8B)

All rows exploratory. Task selection was outcome-dependent throughout, and the 72-task
extension was specified **after** the 24-task control result; its manifest records
`preregistered_before_that_result: false`.

| # | Claim | Value | 95% CI | n | Source artifact | Generating script |
|---|---|---|---|---|---|---|
| 28 | Jacobian-Lens JSD peak within the frozen eligible band L4–L27 | **L24, 0.316 bits** (sd 0.149) | — | 12 discovery tasks | `results/mechanistic/readout_layer_summary.json` | `mechanistic/run_readout.py` |
| 29 | 24-task patching, `self_low_2 → no_history` | +0.170 | [0.032, 0.317] | 72 calls | `results/mechanistic/validation_report.json` | `mechanistic/run_validation.py` |
| 30 | 24-task patching, `no_history → self_low_2` | +0.233 | [0.040, 0.424] | 72 calls | same | same |
| 31 | **72-task extension**, `self_low_2 → no_history` | **+0.220** | [0.060, 0.396] | 72 tasks | `results/mechanistic/ext72_report.json` | `mechanistic/run_ext72.py` |
| 32 | **72-task extension**, `no_history → self_low_2` | **+0.189** | [0.086, 0.300] | 72 tasks | same | same |
| 33 | Layer-2 early control, both directions | −0.001 · +0.019 | [−0.048, 0.042] · [−0.094, 0.117] | 72 tasks | same | same |
| 34 | Paired L24 − L2 advantage | +0.221 · +0.170 | [0.066, 0.395] · [0.034, 0.317] | 61 · 61 | same | same |
| 35 | Identity controls, no-op and same-condition | 144/144 exact, both | — | 72-task set | same | same |
| 36 | Jacobian tokens, `self_low_2 − no_history` @ L24, promoted | `' brief'` +5.59, `' Brief'` +4.62, `' briefly'` +4.62 | — | 72 | `results/mechanistic/jlens_token_summary.json`, `results/figure_inputs/jacobian_tokens.csv` | `mechanistic/analyze_jlens_tokens.py` |
| 37 | Same contrast, suppressed | `' score'` −1.74 (97%), `' Score'` −1.65 (97%) | — | 72 | same | same |
| 38 | `self_high_10 − self_low_2` @ L24, valence axis | `' excellent'` +3.96 · `' disappointing'` −2.25 | — | 72 | same | same |
| 39 | `self_low_2 − unrelated_low_2` @ L24, self-reference axis | `' feedback'` +1.94 · `' your'` +1.70 · `' criticism'` +1.68 | — | 72 | same | same |
| 40 | Full 31-layer tables, 3 contrasts × 10 promoted + 10 suppressed | 1,860 rows | — | 72/layer | `results/mechanistic/jlens_layer_tables/` | `mechanistic/build_layer_tables.py` |

Token strings are BPE fragments, not words or concepts.

### The derived `self_high_10 - no_history` contrast

Main-paper Table 3 reports a **high-history versus no-history** vocabulary contrast. That
contrast was not stored directly. It is recovered by exact algebraic composition of two
retained raw contrasts,

```
(self_high_10 - self_low_2) + (self_low_2 - no_history) = self_high_10 - no_history
```

which holds term by term because every quantity is a difference of log-probabilities at the
same task, layer, position, and vocabulary index; `self_low_2` cancels. No model was loaded and
no value was re-estimated.

| Artifact | Contents |
|---|---|
| `results/mechanistic/jlens_derived/high_minus_no_history_L24_per_task.csv` | 2,880 rows: 72 tasks x 40 locked-layer tokens, with task id, dataset, token id, token string, signed projected difference, orientation, layer, position |
| `results/mechanistic/jlens_derived/high_minus_no_history_L24_summary.csv` | 40 rows: mean signed delta, sign consistency, n, token id and string, sorting rule |
| `results/mechanistic/jlens_derived/DERIVATION_PROVENANCE.json` | source-tensor SHA-256 values, orientation, formula, output hashes |
| `mechanistic/derive_high_minus_no_contrast.py` | deterministic derivation, with assertions on the four printed values |

The two source tensors are 546 MB each and are **not** shipped; their SHA-256 values and the
verified archive that holds them are recorded in the provenance file and in `OMISSIONS.md`. The
per-task CSV independently permits recomputing every displayed mean:

```bash
python mechanistic/derive_high_minus_no_contrast.py --verify-only
```

re-derives the means from the shipped rows and asserts the four values the main paper prints,
failing on any drift.

Two further completed extensions returned negative results and are reported in
**`EXTENDED_RESULTS.md`**: the single-direction steering and ablation control, and the
Gemma / Qwen cross-model single-position patching replication.

### Raw records behind every mechanistic report

Each report above is recomputable from the small records shipped alongside it. The analysis
stages that consume them need no GPU.

| Stage | Raw records shipped | Consumed by |
|---|---|---|
| Layerwise discovery | `discovery/readout_per_task_layer.jsonl`, `discovery/SELECTED_WINDOW.json` | `mechanistic/run_readout.py` output; feeds `readout_layer_summary.json` |
| 24-task validation | `validation/validation_records.jsonl`, `validation_meta.json` | `mechanistic/analyze_validation.py` |
| 72-task extension | `ext72/ext72_records.jsonl`, `ext72_meta.json` | `mechanistic/analyze_ext72.py` |
| Steering and ablation | `control/DIRECTION_FREEZE.json`, `control/steering_direction.pt`, `control/control_records.jsonl`, `control_meta.json` | `mechanistic/analyze_control.py` |
| Cross-model | `crossmodel/discovery_{gemma,qwen}_per_task_layer.jsonl`, `SELECTED_LAYER_{gemma,qwen}.json`, `validation_{gemma,qwen}.jsonl`, `validation_meta_{gemma,qwen}.json`, `crossmodel_discovery_12.json` | `mechanistic/analyze_crossmodel.py` |
| Jacobian tokens | `jlens/csv/` (93 per-layer token CSVs), `heatmap_payload.json`, `jlens_tokens_meta.json`, `jlens_tokens_raw_meta.json`, `vocab_strings_repaired.json` | `mechanistic/analyze_jlens_tokens.py`, `build_layer_tables.py` |
| Lens implementation | `third_party/jacobian-lens/` at commit `581d398613e5602a5af361e1c34d3a92ea82ba8e`, plus `jacobian_lens_provenance_2026-08-18.json` | `mechanistic/run_readout.py`, `run_jlens_tokens.py` |
| Vocabulary mapping | `mechanistic/dump_vocab.py` (byte-exact) produced it; the repaired mapping is shipped | `analyze_jlens_tokens.py --tokenizer-vocab` |

The three 546 MB raw delta tensors and the three ~16 MB aggregates they feed are **not**
shipped; see `OMISSIONS.md` for sizes, hashes, and the regeneration command. Every token
result reported in the paper comes from the shipped CSVs and summaries, not from those
tensors.

### Orchestration

`code/orchestration/archived_run_wrappers/` holds the scripts that actually executed each
production stage, byte-exact, and is the authoritative record of the real command lines.
`code/orchestration/production_environment.json` is the environment captured by the
behavioural run itself.

---

## 4. Figures

| Figure | File | Built by | Inputs |
|---|---|---|---|
| Design overview | not regenerated here (schematic) | — | — |
| Behavioural shift and silence | `figures/paper/fig2_results_final.pdf` | `code/figures/make_fig2_results_final.py` | `results/figure_inputs/headline_metrics.json`, `delta_distribution.csv` |
| Matched MT-Bench example | `figures/paper/` (see script) | `code/figures/make_fig3_matched_example.py` | `results/figure_inputs/real_example_candidates.json` |
| Layerwise localization and causal validation | `figures/paper/fig4_mechanistic_evidence_v3.pdf` | `code/figures/make_fig4_mechanistic_evidence_v3.py` | `results/mechanistic/readout_layer_summary.json`, `results/figure_inputs/mechanistic_summary.json` |
| Same, lighter palette | `figures/paper/fig4_mechanistic_evidence_v4.pdf` | `code/figures/make_fig4_mechanistic_evidence_v4.py` | same |
| Supporting analysis figures f1–f6 | `figures/analysis/` | `code/analysis/make_a9_figures.py`, `make_ecdf_figure.py`, `make_olmo_figure.py` | `results/behavioral/final_analysis_results.json` |

Each figure builder asserts its displayed values against the source artifact before drawing
and aborts on drift, so a figure cannot silently disagree with the table it came from.

---

## 5. Caveats that travel with these numbers

1. **Measurement basis.** The paper reports the documented **complete-case** basis. A queue of
   36 score-recovery items remains unadjudicated; those items are not included in any estimate
   reported in the paper or in this package, and no adjudication was performed here.
2. **Diagnostic contrasts are unadjusted** for multiplicity and are labelled non-confirmatory
   in the analysis output.
3. **Mechanistic rows are exploratory**, with outcome-dependent task selection throughout.
4. **The 72-task and 24-task mechanistic pools are not like-for-like**: the 72-task pool has
   no endpoint band and no delta threshold.
5. **Differential attrition is not neutral.** The two primary conditions carry the highest
   invalid rates (`no_history` 3.21%, `self_low_2` 2.46%), and the 32B scorer — which shows
   the smallest effect — the highest of any scorer at 5.34%.
6. **Silence measures explicit textual reference**, not awareness, intent, or influence. A
   rationale that never mentions the inserted sentence may still have been shifted by it.
