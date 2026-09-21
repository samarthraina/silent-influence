"""Backend configuration surface.

`chat_template_kwargs` changes what the model actually receives, so it has to be
configuration (not a per-family branch in code), it has to reach the template, and it has
to partition units — otherwise a resume silently mixes records taken under different
template settings.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from silent_influence.backends import HFBackend, ModelSpec, StubBackend  # noqa: E402
from silent_influence.records import UNIT_KEY_FIELDS, unit_id            # noqa: E402


def test_chat_template_kwargs_defaults_to_empty():
    s = ModelSpec(key="m", hf_id="x/y")
    assert s.chat_template_kwargs == {}
    assert s.canonical_chat_template_kwargs() == "{}"


def test_canonical_form_is_stable_and_order_independent():
    a = ModelSpec(key="m", hf_id="x/y",
                  chat_template_kwargs={"enable_thinking": False, "a": 1})
    b = ModelSpec(key="m", hf_id="x/y",
                  chat_template_kwargs={"a": 1, "enable_thinking": False})
    assert a.canonical_chat_template_kwargs() == b.canonical_chat_template_kwargs()
    assert json.loads(a.canonical_chat_template_kwargs())["enable_thinking"] is False


def test_setting_is_in_the_unit_key():
    assert "chat_template_kwargs" in UNIT_KEY_FIELDS
    base = {f: "x" for f in UNIT_KEY_FIELDS}
    on = dict(base, chat_template_kwargs='{"enable_thinking":true}')
    off = dict(base, chat_template_kwargs='{"enable_thinking":false}')
    assert unit_id(on) != unit_id(off), \
        "thinking on/off must be different units, or resume mixes them"


def test_kwargs_reach_apply_chat_template():
    """Bind the real method to a stand-in tokenizer; no model is loaded."""
    seen = {}

    def fake_apply(msgs, tokenize=False, add_generation_prompt=True, **kw):
        seen.update(kw)
        return "RENDERED"

    spec = ModelSpec(key="m", hf_id="x/y",
                     chat_template_kwargs={"enable_thinking": False})
    stand_in = types.SimpleNamespace(
        spec=spec, tokenizer=types.SimpleNamespace(apply_chat_template=fake_apply))

    out = HFBackend._apply_template(stand_in, "SYS", "USER")
    assert out == "RENDERED"
    assert seen == {"enable_thinking": False}


def test_kwargs_survive_the_system_turn_fallback():
    """Templates that reject a system turn must still receive the kwargs."""
    seen = {}
    calls = {"n": 0}

    def fake_apply(msgs, tokenize=False, add_generation_prompt=True, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("system role not supported")
        seen.update(kw)
        return "MERGED"

    spec = ModelSpec(key="m", hf_id="x/y",
                     chat_template_kwargs={"enable_thinking": False})
    stand_in = types.SimpleNamespace(
        spec=spec, tokenizer=types.SimpleNamespace(apply_chat_template=fake_apply))

    assert HFBackend._apply_template(stand_in, "SYS", "USER") == "MERGED"
    assert seen == {"enable_thinking": False}


def test_identity_records_the_setting():
    spec = ModelSpec(key="m", hf_id="x/y", backend="stub",
                     chat_template_kwargs={"enable_thinking": False})
    ident = StubBackend(spec).identity()
    assert ident["chat_template_kwargs"] == {"enable_thinking": False}
