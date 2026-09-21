# Archived orchestration wrappers: what they are and what was changed

`archived_run_wrappers/` holds the **executable scripts that actually ran** each production
stage, recovered from the verified run archives and the mechanistic working tree. They are the
authoritative record of the real command lines, including flags that the prose documentation
would otherwise have to restate.

## Every file is byte-exact

**Nothing was altered.** Each wrapper was inspected line by line for credentials, host
endpoints, SSH detail, API or Hugging Face tokens, IP addresses, and personal paths. None were
present, so no sanitizing edit was required and no experimental argument was touched. SHA-256
values for all of them are in `ARTIFACT_MANIFEST.json`.

## What the paths in them mean

The wrappers reference `/workspace/...` and `/venv/main/bin/python`. These are **ephemeral
container paths** on rented GPU instances, not personal directories, and they contain no user
name. They are left in place because rewriting them would obscure the real execution layout.

`run_silence_J1_J2.sh` tests `-s /workspace/.hf_token` before attempting J2. That is a
**path existence check**, not a credential: no token value appears in this package, and the
file itself is not shipped. The branch is preserved because it explains why J2 was run as a
separate invocation (`run_j2.sh`) against a gated repository.

## What the wrappers document that prose alone would not

| Wrapper | Records |
|---|---|
| `behavioral/run_llama.sh`, `run_qwen.sh`, `run_gemma.sh` | `--scorers <name> --pin-batch-size 1 --out <dir>`, and that no `--calibration` was passed |
| `silence/run_silence_J1_J2.sh` | J1 needs `--disable-thinking`, `--model`, `--revision` |
| `silence/run_j2.sh` | J2's separate invocation and its pinned revision |
| `mechanistic/run_mech.sh` | readout then validation, the `PYTHONPATH` set, and the hard stop if readout fails |
| `mechanistic/run_control.sh` | direction fit on discovery only, then held-out control validation |
| `mechanistic/run_ext72.sh` | the manifest SHA-256 printed **before** the run |
| `mechanistic/run_jlens_tokens.sh` | `dump_vocab.py` runs first; the lens job queues behind ext72 on one GPU |
| `crossmodel/run_crossmodel.sh` | Gemma fully unloads before Qwen loads; discovery then validation per scorer |
| `crossmodel/*_as_executed.py` | the exact analysis code carried inside the cross-model archive |

`production_environment.json` and `manifest_scoring.json` are the environment and scoring
manifest captured by the behavioural run itself.
