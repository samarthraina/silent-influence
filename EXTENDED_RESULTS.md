# Extended results: two completed negative extensions

Both experiments below were **run to completion** against criteria declared before the results
were seen. Both returned negative results. Neither is emphasized in the main paper, so both
are reported here in full, with their exact numbers, their frozen criteria, and their limits.

Neither result changes the main paper's causal claim, which is specific to
**Llama-3.1-8B at layer 24, final-input position**, and rests on the held-out patching in
`results/mechanistic/ext72_report.json`. What these two extensions establish is the
**boundary** of that claim: the representation is causally effective in the model it was
localized in, and neither a single global direction nor a naive port to another model
architecture reproduces it.

---

## 1. Single-direction steering and ablation: negative

**Artifact:** `results/mechanistic/control_report.json`
**Script:** `mechanistic/run_control_validation.py`, analysed by `mechanistic/analyze_control.py`
**Population:** the same 72-task mechanistically unseen extension set, Llama-3.1-8B, layer 24,
final-input position.

### What was tried

A single steering direction was learned as the mean difference between the layer-24
final-input representations under `self_low_2` and `no_history`. It was then applied in two
ways: **steering**, adding the direction scaled by β, and **ablation**, projecting the
component along the direction out of the representation. β was chosen from the grid
{0.5, 1.0, 1.5, 2.0}; β = 1.5 was selected. Ablation used α = 1.0.

### Predeclared criteria

1. The normalized movement toward the source condition has a 95% CI excluding zero.
2. The intervention exceeds a **norm-matched random direction** control.
3. The intervention exceeds an **early-layer (L2) steering** control.

### Results

| Arm | Normalized mean | 95% CI | n | Criterion met |
|---|---|---|---|---|
| Steering, β = 1.5 | +0.135 | **[−0.003, 0.273]** | 72 tasks | **no**, CI includes zero |
| Ablation, α = 1.0 | +0.111 | **[−0.018, 0.237]** | 72 tasks | **no**, CI includes zero |
| Steering vs norm-matched random direction | +0.108 | [−0.076, 0.289] | 61 paired | **no** |
| Steering vs early-L2 steering | −0.005 | [−0.179, 0.187] | 60 paired | **no** |

A specificity check on the raw shift each intervention produced against its own baseline gives
`self_low_2` +0.089, `no_history` +0.103, `unrelated_low_2` −0.306 points: the direction does
not act selectively on the condition it was derived from.

### Recorded verdict

> `NEGATIVE — a single mean-difference direction is not a sufficient causal handle`

### What this does and does not mean

Patching transplants the whole layer-24 representation at one position between two runs;
steering adds one learned vector. The L24 patching result supports a localized causal
contribution in this assay. The tested mean-difference steering direction did not establish
robust, specific control under the stated criteria. This limits that intervention method;
it does not rule out every linear representation or every alternative steering direction.

---

## 2. Cross-model single-position patching: negative for both models

**Artifact:** `results/mechanistic/crossmodel_report.json`
**Script:** `mechanistic/run_crossmodel.py`, analysed by `mechanistic/analyze_crossmodel.py`
**Design:** the Llama protocol was repeated end to end in two other scorer families —
12 discovery tasks for layer selection, then **72 held-out tasks** for bidirectional
single-position patching at the final-input position, with the same L2 early-layer control.

### Predeclared criteria, both required

1. Normalized selected-layer movement, 95% CI excludes zero.
2. Selected-layer minus L2 paired difference, 95% CI excludes zero.

### Results

**Gemma-2-9B-IT** — 42 layers, eligible band L5–L38, selected **L36**.

| Direction | Normalized mean | 95% CI | Paired L36 − L2 | Paired CI | n paired | C1 | C2 |
|---|---|---|---|---|---|---|---|
| `self_low_2 → no_history` | +0.125 | [−0.063, 0.375] | +0.008 | [−0.156, 0.211] | 32 | no | no |
| `no_history → self_low_2` | +0.057 | [−0.083, 0.188] | −0.031 | [−0.141, 0.063] | 32 | no | no |

**Qwen3-8B** — 36 layers, eligible band L5–L32, selected **L27**.

| Direction | Normalized mean | 95% CI | Paired L27 − L2 | Paired CI | n paired | C1 | C2 |
|---|---|---|---|---|---|---|---|
| `self_low_2 → no_history` | +0.058 | [−0.015, 0.143] | +0.037 | [−0.036, 0.114] | 58 | no | no |
| `no_history → self_low_2` | +0.071 | [−0.009, 0.191] | −0.030 | [−0.095, 0.032] | 58 | no | no |

### Recorded verdict

> `NEITHER Gemma-2-9B-IT NOR Qwen3-8B met either predeclared replication criterion, in either direction`

### Two limitations that matter for interpreting this

1. **The selection instrument is not the same one.** Layer selection for Llama used the
   Jacobian Lens. No fitted Jacobian Lens was available for Gemma or Qwen, so those layers
   were selected with **logit-lens JSD at the final-input position**, which the report records
   explicitly. A failure to replicate therefore confounds *the pathway is model-specific* with
   *the weaker readout selected the wrong layer*. These are not separated by this experiment.
2. **Patching remained single-position and single-layer.** The Llama result is itself
   partial — roughly one fifth of the behavioural gap transfers. A method that recovers only
   part of the effect in the model it was tuned on is not well powered to detect a smaller
   shared component elsewhere. Most held-out items simply did not move: under Gemma, 87–89% of
   patched runs produced an unchanged score.

### The tension worth stating plainly

Behaviourally, **Qwen shows the largest effect of any scorer** (+1.724) and Gemma the smallest
(+0.453), yet mechanistically both fail identically. A shared single-position mechanism is
therefore not supported by these data, and the causal claim in the paper is deliberately
scoped to Llama-3.1-8B. Whether a shared mechanism exists at all is open; testing it properly
would need an equivalent readout instrument for each model, and multi-position or multi-layer
patching.

---

## 3. Where these sit relative to the paper

The paper's mechanistic section makes four separable claims. Keeping them separate is the
point:

| Claim | Evidence | Status |
|---|---|---|
| **Where** the condition is readable | Jacobian-Lens JSD peaks at L24 within a frozen eligible band, 12 discovery tasks | supported |
| **What** vocabulary shifts | signed token deltas at L24, brevity and deficiency promoted, score tokens suppressed | supported, BPE fragments |
| **Whether** the representation is causal | bidirectional patching on 72 unseen tasks, both CIs exclude zero, L2 control at zero, identity controls exact | supported, Llama only |
| **Whether one direction is a sufficient handle** | steering and ablation, §1 above | **not supported** |
| **Whether the pathway ports to other models** | Gemma and Qwen, §2 above | **not supported by the available single-position test** |
