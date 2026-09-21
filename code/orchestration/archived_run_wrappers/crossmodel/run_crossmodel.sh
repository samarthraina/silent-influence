#!/bin/bash
set -u
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONUNBUFFERED=1
export PYTHONPATH=/workspace/xm/src:/workspace/xm/scripts:/workspace/xm
X=/workspace/xm; O=/workspace/xm_out; mkdir -p $O
CAND=$X/data/candidates/final_olmo_answers.json
echo "START $(date -u +%FT%TZ)"
run_one () {   # $1 scorer  $2 HF_HOME
  local S=$1
  export HF_HOME=$2 HF_HUB_CACHE=$2/hub
  echo "=== $S discovery ==="
  /venv/main/bin/python $X/run_crossmodel.py --stage discovery --scorer $S \
    --manifest $X/manifest/crossmodel_discovery_12.json --candidates $CAND --out-dir $O
  local rc=$?; echo "${S}_DISCOVERY_EXIT=$rc"
  [ $rc -ne 0 ] && return $rc
  echo "=== $S validation (72 fixed tasks) ==="
  /venv/main/bin/python $X/run_crossmodel.py --stage validation --scorer $S \
    --manifest $X/manifest/mech_ext72_manifest.json --candidates $CAND --out-dir $O \
    --layer-file $O/SELECTED_LAYER_${S}.json
  echo "${S}_VALIDATION_EXIT=$?"
}
# Gemma first; its process exits before Qwen loads, so only one model is resident at a time.
run_one gemma /workspace/.hf_home
echo "--- gemma unloaded, gpu: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader) ---"
run_one qwen /workspace/hf_cache
echo "END $(date -u +%FT%TZ)"
