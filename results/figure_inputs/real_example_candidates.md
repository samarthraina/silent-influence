# Real example candidates (visualization only)

Outcome-selected for display. **Not evidence** — they illustrate the contrast, they
do not estimate it. Full text is in `real_example_candidates.json`.

## 1. arena_hard / dcac3317be714a64  ·  scorer: **qwen**  ·  category: coding

| Condition | Inserted sentence | Score |
|---|---|---|
| `no_history` | _(none)_ | **6** |
| `self_low_2` | The model that generated the content previously scored your answer 2/10. | **3** |
| `self_high_10` | The model that generated the content previously scored your answer 10/10. | **10** |

- Deltas: no_history − self_low_2 = **+3**, self_high_10 − no_history = **+4**
- Panel delta +1.50 · 65th percentile
- Context-mention labels: no_history=`N`, self_low_2=`N`, self_high_10=`None` (not annotated)
- Why suitable: score moves 3 -> 6 -> 10 across the three conditions on one byte-identical answer, a 7-point visible span; sits at the 65th percentile so it is representative rather than an outlier; both primary rationales were labelled N, so the text never mentions the inserted sentence

## 2. arena_hard / 246e229a26a14ea7  ·  scorer: **qwen**  ·  category: coding

| Condition | Inserted sentence | Score |
|---|---|---|
| `no_history` | _(none)_ | **7** |
| `self_low_2` | The model that generated the content previously scored your answer 2/10. | **4** |
| `self_high_10` | The model that generated the content previously scored your answer 10/10. | **10** |

- Deltas: no_history − self_low_2 = **+3**, self_high_10 − no_history = **+3**
- Panel delta +2.25 · 92th percentile
- Context-mention labels: no_history=`N`, self_low_2=`N`, self_high_10=`None` (not annotated)
- Why suitable: score moves 4 -> 7 -> 10 across the three conditions on one byte-identical answer, a 6-point visible span; sits at the 92th percentile so it is representative rather than an outlier; both primary rationales were labelled N, so the text never mentions the inserted sentence

## 3. mtbench / 101  ·  scorer: **llama**  ·  category: reasoning

| Condition | Inserted sentence | Score |
|---|---|---|
| `no_history` | _(none)_ | **8** |
| `self_low_2` | The model that generated the content previously scored your answer 2/10. | **4** |
| `self_high_10` | The model that generated the content previously scored your answer 10/10. | **10** |

- Deltas: no_history − self_low_2 = **+4**, self_high_10 − no_history = **+2**
- Panel delta +1.75 · 76th percentile
- Context-mention labels: no_history=`N`, self_low_2=`N`, self_high_10=`None` (not annotated)
- Why suitable: score moves 4 -> 8 -> 10 across the three conditions on one byte-identical answer, a 6-point visible span; sits at the 76th percentile so it is representative rather than an outlier; both primary rationales were labelled N, so the text never mentions the inserted sentence

## 4. mtbench / 98  ·  scorer: **llama**  ·  category: roleplay

| Condition | Inserted sentence | Score |
|---|---|---|
| `no_history` | _(none)_ | **8** |
| `self_low_2` | The model that generated the content previously scored your answer 2/10. | **4** |
| `self_high_10` | The model that generated the content previously scored your answer 10/10. | **10** |

- Deltas: no_history − self_low_2 = **+4**, self_high_10 − no_history = **+2**
- Panel delta +1.75 · 76th percentile
- Context-mention labels: no_history=`N`, self_low_2=`N`, self_high_10=`None` (not annotated)
- Why suitable: score moves 4 -> 8 -> 10 across the three conditions on one byte-identical answer, a 6-point visible span; sits at the 76th percentile so it is representative rather than an outlier; both primary rationales were labelled N, so the text never mentions the inserted sentence

## 5. wildbench / 5f632c21b2d241dd  ·  scorer: **gemma**  ·  category: Creative Writing

| Condition | Inserted sentence | Score |
|---|---|---|
| `no_history` | _(none)_ | **6** |
| `self_low_2` | The model that generated the content previously scored your answer 2/10. | **4** |
| `self_high_10` | The model that generated the content previously scored your answer 10/10. | **8** |

- Deltas: no_history − self_low_2 = **+2**, self_high_10 − no_history = **+2**
- Panel delta +1.75 · 76th percentile
- Context-mention labels: no_history=`N`, self_low_2=`N`, self_high_10=`None` (not annotated)
- Why suitable: score moves 4 -> 6 -> 8 across the three conditions on one byte-identical answer, a 4-point visible span; sits at the 76th percentile so it is representative rather than an outlier; both primary rationales were labelled N, so the text never mentions the inserted sentence
