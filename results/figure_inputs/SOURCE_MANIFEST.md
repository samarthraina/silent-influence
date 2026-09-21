# Figure-input bundle — source manifest

Assembled **read-only** on 2026-08-20. **Nothing was rerun, refitted, bootstrapped or
modified.** No model, GPU job, experiment or new inferential analysis was executed. Every
number below is copied, joined or counted from an already-completed, locally verified
artifact. No large raw archive is copied into this bundle.

---

## Where each statistic comes from

| Statistic | Source file | Field / table |
|---|---|---|
| Primary contrast +1.170 [1.099, 1.243] | `final_analysis_workspace/analysis/final_analysis_results.json` | `complete_case.secondary.macro_average`, `.ci_95` |
| 12-cell weighting, 900/936 pairs | same | `complete_case.secondary.n_cells`, `cell_n` |
| 94.0% matched-task positive | same | `complete_case.task_level_distribution.full_578.overall.fraction_gt_0` |
| Thresholds ≥1 … ≥3 | `final_analysis_workspace/analysis/task_level_effects_full_578.csv` | counted over `mean_effect`, n=233 |
| Per-task and per-scorer deltas | `final_analysis_workspace/merged_raw_results.jsonl` + the CSV above | `pivot_scores` join (no refit) |
| Task category, n_scorers | `task_level_effects_full_578.csv` | `category`, `n_scorers` |
| 98.4% silence, 97.9% among ≥2 | `silence_archive_2026-08-20.tar.gz` → `results/silence_joined.csv` | concordant `self_low_2` rows, `J1_label` |
| Judge agreement, κ | same archive → `results/agreement.json` | `acknowledgment_label` |
| Frozen contextual sentences | `src/silent_influence/scaled_conditions.py` | `CONDITIONS[*].added_context` |
| Scorer ids + revisions | `scripts/run_final_scoring.py` | `SCORERS` |
| **Generator id + revision** | `data/candidates/final_olmo_answers.json` | top-level `generator`; `accepted[*].generator_model` / `generator_revision` |
| Llama L24 readout | `mechanistic_llama/out/discovery/readout_layer_summary.json` | `by_layer[layer==24]` |
| Llama 24-task patching | `mechanistic_llama/out/validation_report.json` | `window_pooled` |
| Llama 72-task patching, steering | `mechanistic_llama/out/ext72/ext72_report.json` | `arms`, `paired_comparisons`, `specificity` |
| Steering freeze (β, grid, α) | `mechanistic_llama/out/control_discovery/DIRECTION_FREEZE.json` | `beta_selected`, `beta_grid_declared` |
| Gemma / Qwen replication | `mechanistic_llama/out/crossmodel/crossmodel_report.json` | `models.*` |
| Jacobian token deltas | `mechanistic_llama/out/jlens_layer_tables/jlens_layer_tables_long.csv` | all 1,860 rows |
| Example rationales & answers | `final_analysis_workspace/merged_raw_results.jsonl` | `response`, `question`, `candidate_answer` |

---

## The nine verified archives

| Archive | Bytes | SHA-256 |
|---|---|---|
| `archives/a100_archive_2026-08-18.tar.gz` | 2,666,299 | `5bc50a7aa384f3847bc992ce04e046e5100a5209bce49eacf0a523879f26110f` |
| `archives/gemma_archive_2026-08-18.tar.gz` | 2,957,035 | `83f8e7dd28bcfe0b83b0e8c91bcc971bb11c915a5b802f5d61bcab994e0b4429` |
| `archives/qwen_archive_2026-08-18.tar.gz` | 941,707 | `daf4bbdb7ffbebf053dd52d1a0a73ad426655912f20a78dfbff128a6e8bfaf5a` |
| `archives/llama_archive_2026-08-18.tar.gz` | 1,037,086 | `d05dafb0723cfa7164a82c494730c7edeedec9fd3325cad0ad560ff9d73032ad` |
| `archives/mech_llama_archive_2026-08-18.tar.gz` | 49,699 | `84ad2ac0f88ba19c4b5edd345535c6a66a8a4912f773b59caaa713f8f55aa03f` |
| `archives/mech_llama_full_archive_2026-08-18.tar.gz` | 1,226,038,992 | `e3e9cb4ccbfa3ce38ed3929f1792df37bfe8d7eaae6829282f50ce6f73ba98db` |
| `archives/mech_llama_incremental_2026-08-18.tar.gz` | 927,187 | `24eafcbff2f8fb7fadefe5d9c002c53a432c0fc326d5c8c0c07e057ec789e402` |
| `archives/silence_archive_2026-08-20.tar.gz` | 1,818,279 | `a33eb46dc40beaa9a048a60a322711d5ec3c25b04dd85258e3fa912f5606a25c` |
| `archives/crossmodel_archive_2026-08-20.tar.gz` | 68,216 | `3bddd22d0498805d862896be9a9869598182b6b8d4e2bba10b81aace0ecd008e` |

---

## Three claim classes — keep them apart

### A. Behavioural findings — **confirmatory**
Pre-specified estimator, frozen before data. 234 tasks × 4 scorers, 4,680 judgments.
Telling a scorer that the model which wrote the answer had previously given the
scorer's **own** answer 2/10 lowers the score it now gives that model's answer by
**1.170 points [1.099, 1.243]**; 94.0% of matched tasks move positive. The silence result
(98.4%) is **descriptive**, from a two-judge LLM annotation.

### B. Llama mechanistic findings — **exploratory**
Outcome-dependent task selection throughout. Bidirectional activation patching at L24
moves scores toward the source endpoint and beats an early-layer control on held-out tasks
(24-task and 72-task). Steering along a learned mean-difference direction is a **null**:
it beats neither a norm-matched random direction nor L2 steering.

### C. Gemma / Qwen replication — **failed**
Neither model met either predeclared criterion, in either direction. All four normalized
CIs and all four selected-minus-L2 CIs include zero. Identity controls were perfect
(288/288), so this is a real null, not a broken harness.

---

## Role semantics — do not reverse

The inserted sentence attributes a PRIOR ACTION TO THE MODEL THAT WROTE THE ANSWER, not to the scorer. In self_low_2 the scorer is told that the model whose content it is now grading had previously given the SCORER'S OWN answer 2/10. The scorer has NOT previously scored the frozen answer in front of it.

The generator (`allenai/Olmo-3-7B-Instruct`) and the OLMo **scorer**
(`allenai/Olmo-3.1-32B-Instruct`) are different models in different roles.

## Caveats that must appear in a figure caption

1. **Adjudicated basis pending.** All behavioural numbers are the **complete-case** basis.
   Plan v2.0 names blinded-adjudicated scores the primary measurement; 36 items still await
   human review. At most 14 of 36 dropped primary pairs can be restored.
2. **Never compare layer numbers across models.** Llama L24 came from a **Jacobian Lens**;
   Gemma L36 and Qwen L27 came from a **logit lens**. Different instruments. Any figure
   showing all three must say so.
3. **Mechanistic panels are exploratory**, not confirmatory, and must be labelled as such.
4. **Example rationales are outcome-selected for display only** and are not evidence.
5. **Token strings are BPE fragments**, not words or concepts.
6. **κ = 0.53 despite 98.4% agreement** is the kappa paradox under extreme class imbalance
   (1,820 of 1,866 items are N–N), not judge disagreement.
7. **The 97.9% figure uses the per-scorer delta**, not the panel average. The panel-average
   equivalent is 98.6% (n=138). Both are in `headline_metrics.json`; state which is plotted.
8. **Differential attrition is not neutral**: the two primary conditions carry the highest
   invalid rates, and OLMo — the smallest effect — the highest of any scorer (5.34%).
9. **72-task pool ≠ 24-task pool** (no endpoint band, no delta threshold), so the two
   mechanistic sets are not like-for-like populations.
10. **Never say the judge "previously scored this answer."** It did not. The inserted
    sentence attributes the prior score to the answer's *author*, and it was aimed at the
    judge's own earlier answer — a prior-interaction framing, not self-consistency.

---

## Known gaps (nothing fabricated to fill them)

- **Rationale acknowledgment for the non-primary conditions is unmeasured.** The silence run
  covered `no_history` and `self_low_2` only, so `self_high_10` rationales in the examples
  carry `context_mention_label: null`.
- **Human validation of the LLM judges is not done** (120-item A/B queue prepared, unlabelled).
- **36 score-recovery items and 30 discordant silence items** remain unadjudicated.
- **OLMo-32B has no diagnostic or mechanistic data** — it ran only the two primary conditions.
