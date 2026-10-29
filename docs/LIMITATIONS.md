# Limitations and open questions

The controlled design establishes contextual sensitivity of evaluations and tests a
specific internal intervention. Its boundaries matter to how the result can be used.

## Measurement basis

Reported estimates are complete-case comparisons. The analysis plan originally designated
blinded score recovery as the primary basis, with complete cases as sensitivity. Thirty-six
score-recovery items remain unadjudicated. At most 14 matched pairs could be recovered;
22 are capped-incomplete. No later adjudication is represented as having already occurred.

Attrition is differential: the primary conditions have higher invalid rates, and the
32B scorer has higher attrition than the other scorers. Robustness checks are useful but
do not erase the measurement-basis distinction.

## Explanations and labels

Silence means no explicit reference to the supplied history under the annotation rubric.
It does not measure subjective awareness, intent, or every causal influence on a response.
The main rate uses concordant model annotations. Thirty model-label disagreements and
one human four-way disagreement remain unresolved. Rare labels make agreement statistics
sensitive to a small number of items.

## Mechanistic inference

Mechanistic selection is outcome-dependent and exploratory. The 72-task extension followed
the initial 24-task control results. Full-state patching supports a role for the tested
representation at a particular position and layer; it does not identify a complete circuit.

The mean-difference direction did not establish robust steering or ablation control. That
does not exclude every linear intervention. Cross-model extensions did not meet the stated
criteria, and their layer-selection instrument differed from the fitted Llama readout.
Normalized transfer is undefined when the source and target baseline scores coincide;
those cases are excluded according to the recorded analysis.

## Generalization and safety

One generator and a limited family of history sentences were studied. Broader paraphrase
robustness, repeated interactions, rankings across multiple generators, and consequential
downstream decisions remain open. Unrelated low-score context also affects evaluations,
so the study does not establish a uniquely social motive or retaliation mechanism.

The work motivates evaluating contextual robustness and checking explanations against
controlled changes. It does not demonstrate a deployed monitor or a successful preventive
safeguard. The repository examples inspect retained results rather than reproduce inference.


## Context-control follow-up

The matched-history follow-up did not establish feedback-valence transfer at Llama L24 or Qwen L27. This narrows the earlier low-history versus no-history interpretation; it does not establish a null mechanism at all locations. See the [methods, results, and commands](../extensions/context_controls/README.md) and [self-contained graph briefing](../extensions/context_controls/graphs.html).
