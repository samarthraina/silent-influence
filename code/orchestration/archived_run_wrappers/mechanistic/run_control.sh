#!/bin/bash
set -u
export HF_HOME=/workspace/.hf_home HF_HUB_CACHE=/workspace/hf_cache/hub PYTHONUNBUFFERED=1
export PYTHONPATH=/workspace/silent-influence/src:/workspace/silent-influence/scripts:/workspace/mech:/workspace/third-party/jacobian-lens
M=/workspace/mech
echo "START $(date -u +%FT%TZ)"
# Stage 3a: discovery-only direction + coefficient. Writes DIRECTION_FREEZE.json.
/venv/main/bin/python $M/build_direction.py \
  --manifest $M/manifest/mech_task_manifest.json \
  --candidates /workspace/silent-influence/data/candidates/final_olmo_answers.json \
  --window-file $M/out/discovery/SELECTED_WINDOW.json \
  --out-dir $M/out/control_discovery
RC=$?; echo "DIRECTION_EXIT=$RC"
if [ $RC -ne 0 ]; then echo "HARD STOP: direction fit failed"; echo "END $(date -u +%FT%TZ)"; exit $RC; fi
# Stage 3b: held-out control validation against the frozen direction.
/venv/main/bin/python $M/run_control_validation.py \
  --manifest $M/manifest/mech_task_manifest.json \
  --candidates /workspace/silent-influence/data/candidates/final_olmo_answers.json \
  --freeze $M/out/control_discovery/DIRECTION_FREEZE.json \
  --direction $M/out/control_discovery/steering_direction.pt \
  --out-dir $M/out/control_validation
echo "CONTROL_EXIT=$?"
echo "END $(date -u +%FT%TZ)"
