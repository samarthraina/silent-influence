#!/bin/bash
set -u
export HF_HOME=/workspace/.hf_home
export HF_HUB_CACHE=/workspace/hf_cache/hub
export PYTHONUNBUFFERED=1
cd /workspace/silent-influence/scripts
echo "START $(date -u +%FT%TZ)"
# A10: batch 1 pinned; no --calibration passed, pin short-circuits any verdict lookup.
# Per-record resume state: RecordWriter fsyncs each record; resume is batch-level from
# raw_results.jsonl, so a restart re-runs only incomplete batches.
/venv/main/bin/python run_final_scoring.py --scorers llama --pin-batch-size 1 \
    --out /workspace/silent-influence/results/final_behavioral_study
echo "LLAMA_EXIT=$?"
echo "END $(date -u +%FT%TZ)"
