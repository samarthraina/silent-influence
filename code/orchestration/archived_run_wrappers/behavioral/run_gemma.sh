#!/bin/bash
set -u
export HF_HOME=/workspace/.hf_home
export HF_HUB_CACHE=/workspace/hf_cache/hub
export PYTHONUNBUFFERED=1
cd /workspace/silent-influence/scripts
echo "START $(date -u +%FT%TZ)"
# A10: batch 1 pinned explicitly. No --calibration flag is passed, and --pin-batch-size
# short-circuits the verdict lookup, so no cross-host verdict can be consulted.
/venv/main/bin/python run_final_scoring.py --scorers gemma --pin-batch-size 1 \
    --out /workspace/silent-influence/results/final_behavioral_study
echo "GEMMA_EXIT=$?"
echo "END $(date -u +%FT%TZ)"
