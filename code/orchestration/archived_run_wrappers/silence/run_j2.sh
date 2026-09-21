#!/bin/bash
set -u
# J2 inherits the browser-login credential store directly; no token file, no token copy.
export HF_HOME=/workspace/.hf_home
export PYTHONUNBUFFERED=1
cd /workspace/silence_run
echo "START_J2 $(date -u +%FT%TZ)"
/venv/main/bin/python run_silence_judge.py --judge J2 \
  --model google/gemma-2-9b-it --revision 11c9b309abf73637e4b6f9a3fa1e92e615547819 \
  --out /workspace/silence_run/judge_J2_raw.jsonl
echo "J2_EXIT=$?"
echo "END_J2 $(date -u +%FT%TZ)"
