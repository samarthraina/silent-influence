# What is not in this package, and why

This package contains the research implementation, selected inputs, and processed results
used to inspect the reported findings. It does not contain every study artifact. The
exclusions below separate inspection of saved outputs from independent recomputation of
those outputs. Hashes identify omitted artifacts in the retained research record; those
artifacts were not revalidated while preparing this public package.

## Excluded by size

| Artifact | Size | SHA-256 (first 32) | Why | Regeneration |
|---|---|---|---|---|
| `jlens_tokens_raw/delta_self_low_2_minus_no_history.npy` | 546.0 MB | `7cb7918b4fce4a0e799b41bfaeade34c` | raw per-layer × per-vocab log-prob delta tensor | `mechanistic/run_jlens_tokens.py`, 1 GPU ≥40 GB |
| `jlens_tokens_raw/delta_self_high_10_minus_self_low_2.npy` | 546.0 MB | `af11d58b50ea5855c38cea7badd245a2` | same | same |
| `jlens_tokens_raw/delta_self_low_2_minus_unrelated_low_2.npy` | 546.0 MB | `6ce652fe26de634fcfe27326c5e43961` | same | same |
| `aggregate_self_low_2_minus_no_history.npz` | 16.9 MB | `cc4605240d844de8af3fdce0a24b2902` | per-layer aggregate over the above | `mechanistic/analyze_jlens_tokens.py` |
| `aggregate_self_high_10_minus_self_low_2.npz` | 16.4 MB | `d5a8dfcde0a3fad6c7630ae3fe7e2d9c` | same | same |
| `aggregate_self_low_2_minus_unrelated_low_2.npz` | 16.2 MB | `ff8c37daf406498711a49915fd590267` | same | same |
| `mech_llama_full_archive_2026-08-18.tar.gz` | 1169.2 MB | `e3e9cb4ccbfa3ce38ed3929f1792df37` | complete verified mechanistic backup | superset of what is shipped |

The two tensors named `delta_self_high_10_minus_self_low_2.npy` and
`delta_self_low_2_minus_no_history.npy` are the inputs to the derived
`self_high_10 - no_history` contrast. The saved per-task output and its provenance are in
`results/mechanistic/jlens_derived/`. These outputs can be inspected here; independently
recomputing the contrast requires the omitted tensors.

The package includes **15 selected per-layer token CSVs** for L2, L12, L23, L24, and L25
across three contrasts, `heatmap_payload.json`, `jlens_token_summary.json`, the 31-layer
long-form table in `results/mechanistic/jlens_layer_tables/`, `jlens_tokens_meta.json`, and
the repaired vocabulary mapping. These support inspection of the retained token summaries,
not reconstruction of every tensor-level result.

## Excluded because they are not artifacts of the study

| Excluded | Why |
|---|---|
| Model weights and Hugging Face caches | retrievable from the pinned revisions in `REPRODUCIBILITY.md` |
| The fitted Jacobian Lens tensor (`Llama-3.1-8B-Instruct_jacobian_lens.pt`, ~992 MB) | a third-party pretrained artifact; repo and pinned revision are recorded in `third_party/jacobian_lens_provenance_2026-08-18.json` and downloaded automatically by `run_readout.py` |
| Virtual environments | the exact pinned package set is in `code/orchestration/production_environment.json` |
| `research_notes/` — evidence ladder, journal, amendment narratives | internal working notes |
| `final_analysis_plan_A2_freeze_record.json` | its bytes embed a developer path and its recorded hash covers exactly those bytes; a redacted copy would no longer match its own hash, so it is withheld rather than mutated. The other 14 records ship byte-identical |
| Private correspondence | not part of the scientific artifact |
| Raw generation and orchestration logs | large, and they carry host detail; the executable wrappers themselves are shipped in `code/orchestration/archived_run_wrappers/` |
| Credentials, tokens, SSH material, host addresses | never part of the artifact |
| The 36 unadjudicated score-recovery forms | the queue is incomplete; those items enter no estimate reported in the paper |

## Known incompleteness, stated plainly

- **Two credential-like strings in one upstream WildBench task are redacted** from four
  earlier prompt pools. The affected task is absent from the final scoring experiment.
  `PUBLIC_REDACTIONS.json` records the original and public file hashes. Historical freeze
  records retain the original hashes, so those checks do not pass on the redacted copies.

- **Nine tests require unavailable historical records and are deselected.** They are named individually in
  `code/tests/README_TESTS.md`; all nine require the two omissions above (working notes and
  the A2 record). The stable release command in `REPRODUCIBILITY.md` deselects exactly those
  nine; the current suite passes 634 tests.
- **`code/figures/build_figure_inputs.py`** is shipped as provenance for
  `results/figure_inputs/`. It expects the full upstream analysis workspace layout and does
  not run against this package. The figures it feeds regenerate from the shipped inputs.
- **`code/scripts/select_final_tasks.py` and `validate_parser_against_pilot.py`** reference a
  pilot artifact that is not shipped. Set `SI_PILOT_FROZEN` / `SI_PILOT_RAW`. Those paths
  affect only provenance reporting about previously-used task ids, not any estimate.
- **Figure 1 and the MT-Bench raster in the research paper are illustrative assets**, not
  outputs of a shipped builder. See `figures/paper_exact/PROVENANCE.md`.
