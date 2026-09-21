#!/bin/bash
set -u
export HF_HOME=/workspace/.hf_home HF_HUB_CACHE=/workspace/hf_cache/hub PYTHONUNBUFFERED=1
export PYTHONPATH=/workspace/silent-influence/src:/workspace/silent-influence/scripts:/workspace/mech:/workspace/third-party/jacobian-lens
M=/workspace/mech
echo "START $(date -u +%FT%TZ)"
echo "manifest sha256: $(sha256sum $M/manifest/mech_ext72_manifest.json | cut -d' ' -f1)"
/venv/main/bin/python $M/run_ext72.py \
  --manifest $M/manifest/mech_ext72_manifest.json \
  --candidates /workspace/silent-influence/data/candidates/final_olmo_answers.json \
  --freeze $M/out/control_discovery/DIRECTION_FREEZE.json \
  --direction $M/out/control_discovery/steering_direction.pt \
  --out-dir $M/out/ext72
echo "EXT72_EXIT=$?"
echo "END $(date -u +%FT%TZ)"
