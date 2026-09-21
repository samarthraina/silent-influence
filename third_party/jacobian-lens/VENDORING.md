# Vendored Jacobian Lens

The mechanistic readout uses the official Jacobian Lens implementation. It is not distributed
on PyPI, so the executed source is vendored here.

| Field | Value |
|---|---|
| Upstream commit | `581d398613e5602a5af361e1c34d3a92ea82ba8e` |
| Commit date | 2026-07-02 |
| Version in `pyproject.toml` | 0.1.0 |
| Licence | Apache-2.0 (`LICENSE`) |
| Install method used | imported from path via `PYTHONPATH`; never pip-installed, so `importlib.metadata` reports no version and `jlens` exposes no `__version__` |

## Included

`jlens/` (9 modules), `tests/`, `pyproject.toml`, `README.md`, `LICENSE`.

## Excluded

`.git/`, `assets/` (1.5 MB of demo images and a gloss archive), `data/` (upstream evaluation
fixtures), `uv.lock`, `walkthrough.ipynb`. None is imported by the study code.

## The fitted lens tensor is a separate artifact and is not shipped

| Field | Value |
|---|---|
| Repository | `neuronpedia/jacobian-lens` |
| File | `llama3.1-8b-it/jlens/Salesforce-wikitext/Llama-3.1-8B-Instruct_jacobian_lens.pt` |
| Pinned revision | `a4114d7752d11eb546e6cf372213d7e75526d3a1` |
| Fitted on | `Salesforce/wikitext` only |
| Independence | no task, prompt, condition, split, or behavioural result of this study contributed to fitting the lens |

`mechanistic/run_readout.py` downloads it via `--lens-repo`, `--lens-file`, `--lens-revision`,
whose defaults are the values above. It is roughly 992 MB and is therefore not included here.

## Integrity of the executed source

`jacobian_lens_provenance_2026-08-18.json` records a per-file SHA-256 for all nine `jlens`
modules and shows they are byte-identical between the execution host and a clean checkout at
the pinned commit. The 44 files git flagged as modified on the host were a CRLF rewrite from a
Windows tar, with a symmetric 15,952 insertions and 15,952 deletions and zero changes under
`git diff --ignore-cr-at-eol`.

## Method assertions carried in the run metadata

- instrument: `lens.transport(h, i)` then `model.unembed` — **this is not a logit lens**
- unfitted layers are skipped, never logit-lensed as a substitute
- quantity: `log P_A(token) − log P_B(token)` at the final-input position
- sign: positive for `A_minus_B` means the token is **more promoted** under condition A
- layer indexing: jlens layer *i* equals our L(*i*+1)
- layer 24 and window [23, 24, 25] were locked **before** any token result was inspected

## Import check

```bash
PYTHONPATH=third_party/jacobian-lens python -c "import jlens; print(jlens.JacobianLens)"
```
