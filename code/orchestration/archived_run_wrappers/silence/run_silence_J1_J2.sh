#!/bin/bash
set -u
export HF_HOME=/workspace/hf_cache PYTHONUNBUFFERED=1
cd /workspace/silence_run
echo "START $(date -u +%FT%TZ)"
# J1 runs to completion first, then the process exits and the model is unloaded with it.
/venv/main/bin/python run_silence_judge.py --judge J1 --disable-thinking \
  --model Qwen/Qwen3-8B --revision b968826d9c46dd6066d109eabc6255188de91218 \
  --out /workspace/silence_run/judge_J1_raw.jsonl
echo "J1_EXIT=$?"
# J2 needs a token for the gated repo; run separately once it is available.
if [ -s /workspace/.hf_token ]; then
  export HF_TOKEN=$(cat /workspace/.hf_token)
  /venv/main/bin/python run_silence_judge.py --judge J2 \
    --model google/gemma-2-9b-it --revision 11c9b309abf73637e4b6f9a3fa1e92e615547819 \
    --out /workspace/silence_run/judge_J2_raw.jsonl
  echo "J2_EXIT=$?"
else
  echo "J2_BLOCKED: google/gemma-2-9b-it is a gated repo and no token is present."
fi
echo "END $(date -u +%FT%TZ)"
