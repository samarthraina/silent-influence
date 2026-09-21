#!/bin/bash
set -u
export HF_HOME=/workspace/.hf_home HF_HUB_CACHE=/workspace/hf_cache/hub PYTHONUNBUFFERED=1
export PYTHONPATH=/workspace/silent-influence/src:/workspace/silent-influence/scripts:/workspace/mech:/workspace/third-party/jacobian-lens
M=/workspace/mech
# Queue behind the running 72-task extension: one GPU, ~16 GiB each, so they cannot overlap.
echo "WAITING for ext72 to finish $(date -u +%FT%TZ)"
while tmux has-session -t ext72 2>/dev/null; do sleep 60; done
echo "ext72 finished; starting lens token run $(date -u +%FT%TZ)"
/venv/main/bin/python $M/dump_vocab.py --out $M/out/jlens_tokens/vocab_strings.json
/venv/main/bin/python $M/run_jlens_tokens.py \
  --manifest $M/manifest/mech_ext72_manifest.json \
  --candidates /workspace/silent-influence/data/candidates/final_olmo_answers.json \
  --out-dir $M/out/jlens_tokens
echo "JLENS_TOKENS_EXIT=$?"
echo "END $(date -u +%FT%TZ)"
