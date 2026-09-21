# Results and denominators

The public examples and graphics use retained result artifacts. They do not execute new
model runs or estimate new confidence intervals. All score changes below are in points on
a 0–10 scale unless explicitly described as normalized transfer.

## Behavioral result

The primary contrast is `no_history - self_low_2`. Positive values mean that attributed
low-rating history lowered the current score. The estimate gives equal weight to each of
12 dataset-by-scorer cells: three datasets and four scorers.

| Quantity | Result | Source |
|---|---|---|
| Balanced mean decrease | 1.170, 95% CI [1.099, 1.243] | [Final analysis](../results/behavioral/final_analysis_results.json), `complete_case.secondary` |
| Complete pairs | 900 of 936 possible | Same file, `cell_n` |
| Positive task-level average | 219/233 = 94.0% | [Headline metrics](../results/figure_inputs/headline_metrics.json) |
| Task average ≥1 / ≥2 points | 152/233 / 36/233 | Same file |
| Trimmed robustness | 1.106 [1.048, 1.181] | [Robustness table](../results/tables/t8_robustness.csv) |
| Without the 32B scorer | 1.257 [1.188, 1.329] | Same table |

The confidence interval uses the recorded task-clustered, dataset-stratified bootstrap,
with 10,000 replicates and seed 20260818. Scorer means in the README graphic average the
three dataset means equally. They do not use the pair-weighted intervals from another
column of the scorer table.

**Historical naming:** `complete_case.secondary` stores the final 12-cell contrast. The
`primary` field belongs to an earlier two-dataset design. The string “all 578 tasks” in
the historical metadata identifies the generation pool, not the final scoring count.
The final balanced scoring experiment has 234 tasks. One has no valid pair on any scorer,
so the task-level distribution has 233 entries.

## Context mention and human validation

The primary-condition annotation set has 1,872 records. J1 and J2 both parse on 1,866;
they agree on 1,836. Thirty disagreements remain unadjudicated. The headline silence rate
uses 898/913 self-low records on which both judges agreed. Among items with a decrease of
at least two points for that individual scorer, 284/290 (97.9%) remain unmentioned.

J3 covers 1,872 unique records with 1,869 successfully parsed. On a blinded 120-item human
set, four-way agreement is 119/120 (κ = 0.830), and binary context-mention agreement is
120/120 (κ = 1.000). One A-versus-U label remains unresolved; both humans mark context
mentioned. Use [human_vs_judges.json](../results/silence/human_vs_judges.json) for this
completed comparison, rather than the J3 report's older template-inventory block.

## Controls and interpretation

The [diagnostic contrasts](../results/tables/t6_diagnostic_contrasts.csv) include unrelated
low history, other-directed low history, verbal negativity, and high history. Unrelated
low history decreases scores by 0.894 [0.816, 0.973]; verbal negativity decreases them by
1.193 [1.105, 1.280]. High history increases scores by 1.009 [0.950, 1.066] relative to no
history. These intervals are unadjusted for multiple comparisons. Controls use three
scorers, because the 32B arm only includes the primary contrast.

The results do not isolate a universal social motive. Generic anchoring remains relevant,
and the self-versus-unrelated contrast reverses sign for Gemma.

## Internal interventions

The Llama study has 12 discovery tasks, a disjoint 24-task validation set, and a 72-task
extension. Layer 24 was selected within the eligible band L4–L27, at the final input
position, using Jacobian Lens distribution divergence. The 72-task extension was specified
after the initial control result and is exploratory.

On the extension, normalized full-state transfer is 21.97% [5.97, 39.63] for low → no
history and 18.89% [8.60, 29.98] for no history → low. Early-layer controls are −0.10%
[−4.82, 4.18] and 1.93% [−9.35, 11.74]. Paired L24-minus-L2 differences are 22.07%
[6.65, 39.50] and 16.96% [3.39, 31.74], with 61 paired tasks per direction. Zero baseline
gaps are excluded from normalized measures. All 72 tasks contribute to the extension's
experimental design, not necessarily to each normalized statistic.

Read the [mechanistic summary](../results/figure_inputs/mechanistic_summary.json) alongside
[extended results](../EXTENDED_RESULTS.md). The tested mean-difference steering and ablation
directions did not establish robust control. Gemma/Qwen extensions did not meet the stated
criteria, and used model-specific logit-lens selection rather than the fitted Llama lens.
