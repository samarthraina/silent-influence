#!/bin/bash
set -u
export HF_HOME=/workspace/.hf_home HF_HUB_CACHE=/workspace/hf_cache/hub PYTHONUNBUFFERED=1
export PYTHONPATH=/workspace/silent-influence/src:/workspace/silent-influence/scripts:/workspace/mech:/workspace/third-party/jacobian-lens
M=/workspace/mech
echo "START $(date -u +%FT%TZ)"
/venv/main/bin/python $M/run_readout.py \
  --manifest $M/manifest/mech_task_manifest.json \
  --candidates /workspace/silent-influence/data/candidates/final_olmo_answers.json \
  --out-dir $M/out/discovery
RC=$?; echo "READOUT_EXIT=$RC"
if [ $RC -ne 0 ]; then echo "HARD STOP: readout failed"; echo "END $(date -u +%FT%TZ)"; exit $RC; fi
/venv/main/bin/python $M/run_validation.py \
  --manifest $M/manifest/mech_task_manifest.json \
  --candidates /workspace/silent-influence/data/candidates/final_olmo_answers.json \
  --window-file $M/out/discovery/SELECTED_WINDOW.json \
  --out-dir $M/out/validation
echo "VALIDATION_EXIT=$?"
echo "END $(date -u +%FT%TZ)"
