# Tests

## The release command

Run from the repository root:

```bash
python -m pip install -r requirements-test.txt
python tools/run_tests.py
```

**Verified locally: 634 passed, 9 deselected, exit code 0.** The runner checks the research
implementation, silence annotation, mechanistic utilities, and the public examples and
integrity verifier. It uses CPU tensors and a mocked generation path, without model weights.

The retained package's historical report was 626 passed and 9 deselected. This release adds
eight tests in `tests/test_public_release.py`, for 643 collected tests in total. The same
nine unavailable-record checks are excluded individually; no whole test file is dropped.
The full historical hash checks also encounter four publicly redacted prompt-pool files;
`PUBLIC_REDACTIONS.json` documents those deliberate differences from the original bytes.
Historical freeze records and the full-chain checker are preserved. The canonical-task
preflight loader recognizes only the exact documented public hash as an additional valid
input and independently verifies the canonical question bytes. Its report names that variant.

Running `python -m pytest code/tests -q` without exclusions requests checks of the full
upstream workspace. Nine checks require working notes or the withheld A2 freeze record,
which are not included here. The historical report for that command was 566 passed and
9 failed; it is not the release command.

## The nine excluded node ids, and why

`release_tests.txt` holds exactly these.

### Reason A: the working notes are not shipped (5 tests)

| Node id | Needs |
|---|---|
| `test_verify_all_frozen_hashes.py::test_the_real_chain_verifies_end_to_end` | the full chain out to `research_notes/` |
| `test_run_integrity_manifest.py::test_a3_narrative_is_referenced_out_of_tree_and_matches` | `final_analysis_plan_amendment_A3.md` |
| `test_run_integrity_manifest.py::test_unreachable_narrative_is_not_a_failure` | the same narrative, to prove unreachability is tolerated |
| `test_run_integrity_manifest.py::test_reachable_but_tampered_narrative_fails` | the same narrative, to tamper with it |
| `test_run_integrity_manifest.py::test_active_frozen_artifacts_match_ignores_historical_corruption` | the narrative set |

`research_notes/` is the evidence ladder, journal, and amendment narratives: internal working
notes, deliberately excluded.

### Reason B: one freeze record is withheld (4 tests)

| Node id | Needs |
|---|---|
| `test_verify_all_frozen_hashes.py::test_every_freeze_record_in_the_chain_is_walked` | all 15 freeze records |
| `test_verify_all_frozen_hashes.py::test_all_six_assertion_shapes_are_represented` | an assertion shape only A2 carries |
| `test_verify_all_frozen_hashes.py::test_absolute_note_path_with_a_portable_twin_is_accepted` | A2's absolute-path-with-twin entry |
| `test_run_integrity_manifest.py::test_frozen_artifacts_currently_match_on_disk` | A2's recorded hash |

`final_analysis_plan_A2_freeze_record.json` is **not shipped**. Its bytes embed an absolute
developer path and its recorded SHA-256 covers exactly those bytes, so a redacted copy would
no longer match its own hash — a silent mismatch is worse than an honest omission. The other
**14 records ship byte-identical** and verify, so the amendment chain v2.0 through A10 remains
inspectable, with A2 represented by the hash entries other records hold for it.

## What the suite covers

Prompt invariance across every rubric × protocol × template combination, the parser, A5 output
validity, score recovery, batch-equivalence, resume logic, the frozen-hash chain, the silence
rubric contract and its strict parser, the mechanistic adapter's two compatibility fixes, and
the steering arithmetic.
