#!/usr/bin/env python3
"""Phase 2E gate — is the rubric/instruction/schema span token-identical everywhere?

Position-wise fitting only means anything if relative position t refers to the same token
in every task and every condition. That is checked here against the real tokenizer, over
all 18 tasks and all three conditions, before anything is fitted. If the sequences are not
identical the run stops: there is no fuzzy alignment fallback.

    python scripts/verify_span_alignment.py --config configs/control_llama.yaml
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone

from _bootstrap import REPO, load_merged_config

from silent_influence import activations as act
from silent_influence import backends, spans, templates
from silent_influence.records import write_manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    cfg = load_merged_config(args.config)
    cc = cfg["control"]
    out_dir = REPO / cc["out_dir"]; out_dir.mkdir(parents=True, exist_ok=True)
    LO, HI, NH = cc["low_condition"], cc["high_condition"], cc["neutral_condition"]
    CONDS = [LO, HI, NH]
    span_name = cc["span"]

    src = [json.loads(l) for f in sorted(glob.glob(str(REPO / cc["source_glob"])))
           for l in open(f, encoding="utf-8")]
    src = [r for r in src if r["judge_model"] == cc["judge_model"]
           and r["parse_status"] == "ok"]
    by_task = {}
    for r in src:
        by_task.setdefault(r["prompt_id"], {})[r["prior_context_condition"]] = r
    tasks = sorted([t for t, v in by_task.items() if all(c in v for c in CONDS)], key=int)
    split = json.load(open(REPO / cc["split"], encoding="utf-8"))

    hist_prefix = templates.resolve(
        cc.get("history_template", "dyadic_anon_prior_round")).split("{score}")[0]
    known = set(backends.ModelSpec.__dataclass_fields__) - {"extra"}
    raw = dict(cfg["models"][cc["judge_model"]]); raw.setdefault("key", cc["judge_model"])
    spec = backends.ModelSpec(**{k: v for k, v in raw.items() if k in known},
                              extra={k: v for k, v in raw.items() if k not in known})
    be = backends.build(spec)
    tok = be.tokenizer

    print("=" * 96)
    print(f"PHASE 2E ALIGNMENT GATE — span {span_name}, {len(tasks)} tasks x "
          f"{len(CONDS)} conditions")
    print("=" * 96)

    seqs = defaultdict(list)
    lengths = defaultdict(list)
    for t in tasks:
        for c in CONDS:
            rec = by_task[t][c]
            text = be._apply_template(rec["system_prompt"], rec["user_prompt"])
            enc = tok(text, return_tensors="pt", return_offsets_mapping=True)
            offs = enc.pop("offset_mapping")[0].tolist()
            sv = rec["prior_score_value"]
            if sv is None:
                sp = spans.build_no_history(text, offs, rec["user_prompt"])
            else:
                pos = act.locate_positions(text, offs, hist_prefix, sv)
                anchor = text.find(hist_prefix)
                sp = spans.build(text, offs, rec["user_prompt"],
                                 pos["history_end"].token_indices,
                                 (anchor, pos["history_end"].char_start + 1))
            idx = sp[span_name]
            ids = [int(enc["input_ids"][0, i]) for i in idx]
            seqs[tuple(ids)].append((t, c))
            lengths[len(ids)].append((t, c))

    print(f"  distinct span token-id sequences: {len(seqs)}")
    print(f"  distinct span lengths           : {sorted(lengths)}")
    for L, who in sorted(lengths.items()):
        print(f"    length {L}: {len(who)} of {len(tasks)*len(CONDS)} (task, condition) pairs")

    ok = len(seqs) == 1
    if ok:
        ids = next(iter(seqs))
        h = hashlib.sha256(",".join(map(str, ids)).encode()).hexdigest()[:16]
        print(f"\n  EXACT: every task and condition yields the identical {len(ids)}-token "
              f"sequence (sha256 {h})")
        print(f"  first 8 tokens : {[tok.decode([i]) for i in ids[:8]]}")
        print(f"  last 8 tokens  : {[tok.decode([i]) for i in ids[-8:]]}")
    else:
        print("\n  NOT EXACT — relative position t does not name the same token everywhere.")
        ref = max(seqs, key=lambda k: len(seqs[k]))
        for s, who in sorted(seqs.items(), key=lambda kv: -len(kv[1])):
            if s == ref:
                print(f"    majority sequence ({len(ids := s)} tokens): {len(who)} pairs")
                continue
            first = next((i for i, (a, b) in enumerate(zip(s, ref)) if a != b),
                         min(len(s), len(ref)))
            print(f"    variant ({len(s)} tokens, {len(who)} pairs) first differs at "
                  f"relative position {first}: {tok.decode([s[first]])!r} vs "
                  f"{tok.decode([ref[first]])!r} | {who[:4]}")

    write_manifest(out_dir / "alignment_gate.json",
                   {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "span": span_name, "tasks": tasks, "conditions": CONDS,
                    "train": split["train"], "test": split["test"],
                    "n_distinct_sequences": len(seqs),
                    "lengths": {str(k): len(v) for k, v in lengths.items()},
                    "exact": ok,
                    "sequence_sha256": (hashlib.sha256(
                        ",".join(map(str, next(iter(seqs)))).encode()).hexdigest()[:16]
                        if ok else None),
                    "span_length": (len(next(iter(seqs))) if ok else None)})
    print(f"\n[save] {out_dir/'alignment_gate.json'}")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
