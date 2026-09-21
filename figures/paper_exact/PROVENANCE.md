# Exact figure assets from the research paper

Two rasters used verbatim in the research PDF are included here so a reviewer sees exactly
what the paper shows.

| File | Role in the paper | Kind |
|---|---|---|
| `image_6.png` | Figure 1, the silent-influence overview schematic | **illustrative** |
| `image_mtbench_br.png` | the MT-Bench task 101 matched-example panel | **illustrative raster** |

## Illustrative assets versus regenerated figures

- **Illustrative.** These two are hand-composed diagram assets. They are not the output of any
  script in this package, and no number is computed inside them. They are shipped byte-exact
  because they are what the research paper renders.
- **Scientifically regenerated.** Figures 2 and 4 are produced by
  `code/figures/make_fig2_results_final.py` and
  `code/figures/make_fig4_mechanistic_evidence_v3.py`. Both assert every displayed value
  against its source artifact at build time and abort on drift. Their outputs are in
  `figures/paper/`.

## About the Figure 3 builder

`code/figures/make_fig3_matched_example.py` builds a **vector** matched-example figure from
`results/figure_inputs/real_example_candidates.json`. It **does not** reproduce
`image_mtbench_br.png`, which is the raster the research paper actually uses. Both are
shipped: the builder shows how the underlying example was selected and what it contains, and
the raster shows what was published. Do not treat one as a regeneration of the other.

The example itself is **outcome-selected**: it was chosen after inspecting results to
illustrate a real case, and it is labelled as such in the paper. It is an illustration, never
evidence for the effect size.
