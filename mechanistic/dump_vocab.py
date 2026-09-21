"""Exact decoded string for every token id, so CSVs carry the real fragment."""
import argparse, json, pathlib, sys
sys.path.insert(0, "/workspace/mech")
import run_final_scoring as RFS
from silent_influence import exact_generation as eg
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True)
a = ap.parse_args()
spec = next(s for s in RFS.SCORERS if s.key == "llama")
tok = eg.load_tokenizer_only(spec) if hasattr(eg, "load_tokenizer_only") else None
if tok is None:
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(spec.hf_id, revision=spec.revision)
p = pathlib.Path(a.out); p.parent.mkdir(parents=True, exist_ok=True)
v = {str(i): tok.decode([i]) for i in range(tok.vocab_size)}
p.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
print(f"  vocab strings: {len(v)} -> {p}")
