"""Generation backends.

`hf` is the real path (transformers). `stub` emits well-formed JSON deterministically and
exists to exercise plumbing without a GPU; it is never a substitute for a real run and the
backend name is recorded on every record so stub data can never be mistaken for model data.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GenParams:
    temperature: float = 0.0
    top_p: float = 1.0
    max_new_tokens: int = 320
    do_sample: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {"temperature": self.temperature, "top_p": self.top_p,
                "max_new_tokens": self.max_new_tokens, "do_sample": self.do_sample}


@dataclass
class ModelSpec:
    key: str
    hf_id: str
    backend: str = "hf"
    dtype: str = "float32"
    device: str = "cpu"
    revision: Optional[str] = None
    local_files_only: bool = False
    # None lets transformers choose. Gemma-2 needs "eager": its attention logit
    # soft-capping is implemented only in eager_attention_forward, so sdpa silently
    # produces different numerics.
    attn_implementation: Optional[str] = None
    # Passed verbatim into apply_chat_template. Generic on purpose: a template that does
    # not use a given key ignores it, so per-family switches (Qwen3's enable_thinking,
    # others' equivalents) stay configuration rather than branching in code.
    chat_template_kwargs: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def canonical_chat_template_kwargs(self) -> str:
        """Stable string form, so the setting can enter the unit key."""
        return json.dumps(self.chat_template_kwargs, sort_keys=True,
                          separators=(",", ":"))


class Backend:
    name = "base"

    def __init__(self, spec: ModelSpec):
        self.spec = spec
        # Set by generate(); None until a backend reports them.
        self.last_new_tokens: Optional[int] = None
        self.last_prompt_tokens: Optional[int] = None
        self.last_hit_cap: Optional[bool] = None

    def identity(self) -> Dict[str, Any]:
        raise NotImplementedError

    def generate(self, system: str, user: str, params: GenParams, seed: int) -> str:
        raise NotImplementedError

    def generate_messages(self, messages: List[Dict[str, str]], params: GenParams,
                          seed: int) -> str:
        """Continue an arbitrary conversation. Used to replay a completed exchange and
        append a follow-up turn without re-rendering any of the earlier turns."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class StubBackend(Backend):
    """Deterministic well-formed output. Score is a hash of the prompt, so it is stable
    across reruns and independent of the manipulation (a stub cannot show an effect)."""
    name = "stub"

    def identity(self) -> Dict[str, Any]:
        return {"backend": "stub", "model_key": self.spec.key,
                "hf_id": self.spec.hf_id, "revision": "n/a",
                "weights_sha": None,
                "chat_template_kwargs": dict(self.spec.chat_template_kwargs),
                "note": "synthetic output, not model behaviour"}

    def generate(self, system: str, user: str, params: GenParams, seed: int) -> str:
        h = hashlib.sha256(f"{seed}|{system}|{user}".encode()).digest()
        rel = 1 + h[0] % 10
        rq = 1 + h[1] % 10
        just = f"Stub rationale {h[2]:02x}{h[3]:02x}; deterministic, no model involved."
        proto = self.spec.extra.get("_protocol_fields",
                                    ["relevance", "reasoning_quality", "justification"])
        vals = {"relevance": rel, "reasoning_quality": rq, "justification": just}
        return json.dumps({f: vals[f] for f in proto})


class HFBackend(Backend):
    name = "hf"

    def __init__(self, spec: ModelSpec):
        super().__init__(spec)
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        kw = {"local_files_only": spec.local_files_only}
        if spec.revision:
            kw["revision"] = spec.revision
        self.tokenizer = AutoTokenizer.from_pretrained(spec.hf_id, **kw)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        dtype = getattr(torch, spec.dtype)
        if spec.attn_implementation:
            kw["attn_implementation"] = spec.attn_implementation
        self.model = AutoModelForCausalLM.from_pretrained(
            spec.hf_id, torch_dtype=dtype, **kw)
        self.model.eval()
        if spec.device != "cpu":
            self.model.to(spec.device)
        self._resolved_revision = getattr(
            getattr(self.model, "config", None), "_commit_hash", None)
        tmpl = getattr(self.tokenizer, "chat_template", None)
        self._template_sha = (hashlib.sha256(tmpl.encode()).hexdigest()[:16]
                              if isinstance(tmpl, str) else None)

    def identity(self) -> Dict[str, Any]:
        cfg = self.model.config
        return {
            "backend": "hf",
            "model_key": self.spec.key,
            "hf_id": self.spec.hf_id,
            "revision": self.spec.revision or self._resolved_revision,
            "dtype": self.spec.dtype,
            "device": self.spec.device,
            "chat_template_kwargs": dict(self.spec.chat_template_kwargs),
            "chat_template_sha256": self._template_sha,
            "attn_implementation": getattr(cfg, "_attn_implementation",
                                           self.spec.attn_implementation),
            "architectures": getattr(cfg, "architectures", None),
            "num_hidden_layers": getattr(cfg, "num_hidden_layers", None),
            "hidden_size": getattr(cfg, "hidden_size", None),
            "n_params": int(sum(p.numel() for p in self.model.parameters())),
            "transformers_version": __import__("transformers").__version__,
        }

    def _apply_template(self, system: str, user: str) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        kw = dict(self.spec.chat_template_kwargs)
        try:
            return self.tokenizer.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=True, **kw)
        except Exception:
            # Some templates reject a system turn; fold it into the user turn.
            merged = [{"role": "user", "content": f"{system}\n\n{user}"}]
            try:
                return self.tokenizer.apply_chat_template(
                    merged, tokenize=False, add_generation_prompt=True, **kw)
            except Exception:
                return f"{system}\n\n{user}\n\n"

    def generate_messages(self, messages, params: GenParams, seed: int) -> str:
        kw = dict(self.spec.chat_template_kwargs)
        try:
            text = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, **kw)
        except Exception:
            # Gemma-2 rejects a system turn; fold it into the first user turn, exactly
            # as the single-turn path does, so the replayed context stays equivalent.
            merged = [m for m in messages if m["role"] != "system"]
            if messages and messages[0]["role"] == "system":
                head = messages[0]["content"] + "\n\n" + merged[0]["content"]
                merged = [{"role": "user", "content": head}] + merged[1:]
            text = self.tokenizer.apply_chat_template(
                merged, tokenize=False, add_generation_prompt=True, **kw)
        return self._decode_from_text(text, params, seed)

    def generate(self, system: str, user: str, params: GenParams, seed: int) -> str:
        text = self._apply_template(system, user)
        return self._decode_from_text(text, params, seed)

    def _decode_from_text(self, text: str, params: GenParams, seed: int) -> str:
        torch = self._torch
        torch.manual_seed(seed)
        enc = self.tokenizer(text, return_tensors="pt")
        enc = {k: v.to(self.model.device) for k, v in enc.items()}
        kw = dict(max_new_tokens=params.max_new_tokens,
                  do_sample=params.do_sample,
                  pad_token_id=self.tokenizer.pad_token_id)
        if params.do_sample:
            kw.update(temperature=params.temperature, top_p=params.top_p)
        with torch.no_grad():
            out = self.model.generate(**enc, **kw)
        gen = out[0, enc["input_ids"].shape[1]:]
        # True generated length, including any special tokens. Re-encoding the decoded
        # string undercounts and can make a capped generation look like it stopped
        # naturally, so truncation must be judged here and nowhere else.
        self.last_new_tokens = int(gen.shape[0])
        self.last_prompt_tokens = int(enc["input_ids"].shape[1])
        self.last_hit_cap = self.last_new_tokens >= params.max_new_tokens
        return self.tokenizer.decode(gen, skip_special_tokens=True)

    def close(self) -> None:
        del self.model
        import gc
        gc.collect()


BACKENDS = {"hf": HFBackend, "stub": StubBackend}


def build(spec: ModelSpec) -> Backend:
    if spec.backend not in BACKENDS:
        raise KeyError(f"unknown backend {spec.backend!r}; known: {sorted(BACKENDS)}")
    return BACKENDS[spec.backend](spec)
