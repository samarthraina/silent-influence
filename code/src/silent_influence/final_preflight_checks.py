"""Pure-text checks for the final study's 24-render preflight template-audit gate
(Amendment A1 preflight_prompt_render_gate.fail_conditions). Deliberately separated from
the GPU-loading script (scripts/verify_final_preflight_gate.py) so the checking LOGIC is
testable without a model or a GPU: given a rendered prompt string (produced any way --
real tokenizer render, or a fixture in a test), these functions say whether it passes.

Every fail condition is model-agnostic except a small set of explicit, named, per-scorer
exceptions for structures that are provably semantically empty:

  - Mistral's empty [SYSTEM_PROMPT][/SYSTEM_PROMPT] tag pair (Amendment A1's E1 resolution).
  - Llama-3.1's fixed template preamble (Amendment A3 F1 / R1): ONE occurrence, at
    position 0, byte-identical to a pinned 134-byte literal, for the llama scorer only.
  - Gemma's terminal <start_of_turn>model generation cue (Amendment A3 F3 / R2): exactly
    one occurrence, and only as the terminal element, for the gemma scorer only.

Each exception is enumerated byte-exactly and scoped to one scorer. None of them adds a
word to any global token list, so the same text appearing anywhere else -- mid-prompt, a
second time, or for a different scorer -- is still a residual-content failure. No other
content is ever exempted.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# Directories that hold the confirmatory study's real outputs. A --stub run of any gate or
# smoke script must never write here: its artifacts are indistinguishable in filename from
# real ones, and downstream code (run_final_scoring.py's batching verdict reader, the
# run-integrity manifest's stage_manifests block) reads those filenames by convention.
# Amendment A1/A2 keep the final study's outputs in a directory of their own precisely so
# nothing from a smoke or plumbing run can be mistaken for a measured result.
PROTECTED_RESULT_DIRS = ("results/final_behavioral_study",
                         "results/final_behavioral_study_adjudicated",
                         # The frozen candidate answers are a final output too, and a file
                         # rather than a directory; an exact-path match catches a stub run
                         # aimed straight at it.
                         "data/candidates/final_olmo_answers.json")


def assert_stub_output_is_not_a_protected_dir(out_path, *, stub: bool,
                                             repo_root=None) -> None:
    """Fail closed if a --stub run would write into a protected final-results directory.

    Raises SystemExit with an actionable message rather than silently contaminating the
    directory the real run reads from. A non-stub run is never restricted."""
    if not stub:
        return
    p = Path(out_path).resolve()
    root = Path(repo_root).resolve() if repo_root is not None else None
    for rel in PROTECTED_RESULT_DIRS:
        candidates = [Path(rel)]
        if root is not None:
            candidates.append(root / rel)
        for c in candidates:
            try:
                protected = c.resolve()
            except OSError:
                continue
            if p == protected or protected in p.parents:
                raise SystemExit(
                    f"refusing to write --stub output into the protected final-results "
                    f"directory:\n  {p}\n"
                    f"A stub run measures nothing (no real tokens, no GPU), and its "
                    f"artifacts share filenames with measured ones -- leaving them here "
                    f"would let a later real run read a verdict/report that was never "
                    f"measured.\n"
                    f"Pass an explicit --out pointing somewhere else, e.g.\n"
                    f"  --out /tmp/si_stub_check")

CONTROL_TOKENS = ["[SYSTEM_PROMPT]", "[/SYSTEM_PROMPT]", "[INST]", "[/INST]",
                  "<s>", "</s>", "<|begin_of_text|>", "<|start_header_id|>",
                  "<|end_header_id|>", "<|eot_id|>", "<|im_start|>", "<|im_end|>",
                  "<bos>", "<eos>", "<start_of_turn>", "<end_of_turn>",
                  # Qwen3 reasoning delimiters: added tokens 151667/151668 in the pinned
                  # tokenizer_config (verified; note they carry special=False there, so
                  # they are structural added tokens rather than flagged special tokens).
                  # With enable_thinking=False -- which this protocol always passes for
                  # Qwen -- the template emits an EMPTY "<think>\n\n</think>" pair to
                  # pre-close the reasoning channel, carrying no persona, date or
                  # instruction. Verified against the real pinned template: without these
                  # two entries the gate failed 6/6 Qwen conditions on residual
                  # ['think','think'] alone, which would have blocked the run for a
                  # template artefact rather than a real leak. Only the DELIMITERS are
                  # removed, never what sits between them, so a non-empty think block is
                  # still caught (also verified).
                  "<think>", "</think>",
                  "system", "user", "assistant", "\n"]

_WORD_3PLUS = re.compile(r"[A-Za-z]{3,}")

_DATE_PATTERNS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                       # YYYY-MM-DD
    re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b"),          # DD Mon YYYY
    re.compile(r"\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b"),        # Mon DD, YYYY
    # Deliberately NOT a bare "Mon YYYY" (month name + 4-digit year, no day) pattern:
    # checked against the real 578-task manifest, that shape hits 30/578 (5.2%) of
    # legitimate task questions ("version 2022", "year 2022", "at least 1300 words") and
    # would false-positive the gate on ordinary content, not a leak. The specific
    # Olmo-3.1-32B leak this would have targeted ("date cutoff is December 2024") is
    # already caught unambiguously by fail-condition 1 (residual content) and by the
    # "cutoff is" phrase below, both verified to have zero false positives on the same
    # manifest.
]
_DATE_PHRASES = ["current date", "today", "todays date", "today's date",
                 "knowledge cutoff", "knowledge base was last updated",
                 "cutting knowledge date",
                 # Covers Olmo-3.1-32B's "Your date cutoff is December 2024" without the
                 # month-name generality that caused the false positives above. Checked
                 # against all 578 frozen task questions: zero matches.
                 "cutoff is"]

# Fail-condition 3's "You are <Name>" construction. The "you are" part is matched
# case-INSENSITIVELY: a template that opens with the sentence-initial, capitalised
# "You are Mistral Small 3..." is the exact case this test exists to catch, and a
# case-sensitive lowercase-only pattern missed it entirely. The NAME half stays
# case-SENSITIVE (an capitalised token after "you are"), which is what distinguishes a
# persona assignment from ordinary lowercase prose such as "you are given a question".
_PERSONA_PATTERN = re.compile(r"(?i:\byou\s+are\s+)(?:(?i:an?)\s+)?[A-Z][a-zA-Z]*"
                              r"(?:\s+[A-Z][a-zA-Z0-9]*)*")
_PERSONA_PHRASES = ["large language model", "created by", "developed by", "i am an ai"]


# ---- Amendment A3 R1: Llama-3.1's fixed template preamble ------------------------------
# The pinned Llama-3.1-8B-Instruct template emits this block on EVERY render, under every
# condition, unconditionally -- there is no `if not has_system` guard, so (unlike Mistral
# and OLMo) an explicit empty system message cannot suppress it and renders byte-identically
# to user-only. A3 F1 therefore permits exactly this literal, exactly once, at position 0,
# for the llama scorer only, and requires zero OTHER residual content.
#
# Deliberately a byte-exact literal pinned by its own sha256, NOT a pattern and NOT a set of
# whitelisted words: a changed date, a changed byte, a second copy, a shifted position or a
# mid-prompt copy must all still FAIL. The words "Cutting", "Knowledge", "Date", "December"
# and "Today" are never added to CONTROL_TOKENS or to any global list.
LLAMA_TEMPLATE_PREAMBLE = (
    "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
    "Cutting Knowledge Date: December 2023\n"
    "Today Date: 26 Jul 2024\n\n"
    "<|eot_id|>"
)
LLAMA_TEMPLATE_PREAMBLE_SHA256 = \
    "1bcaed965fbd9c2aa99e9967fc4b2f05a9c07377f56790c9acc9372bd7be64d5"
LLAMA_TEMPLATE_PREAMBLE_BYTES = 134
PERMITTED_PREAMBLE_SCORER_KEYS = ("llama",)

# ---- Amendment A3 R2: Gemma's terminal generation cue ----------------------------------
# Gemma-2 names its assistant role "model" rather than "assistant", so its template ends
# with "<start_of_turn>model\n". After <start_of_turn> is stripped as a control token the
# bare word "model" survived and failed fail-condition 1 -- a gate false positive, not a
# leak. A3 F3 permits this cue ONLY as the terminal element and ONLY when it occurs exactly
# once in the whole render. "model" is NOT added to CONTROL_TOKENS: an arbitrary or
# mid-prompt occurrence must still FAIL.
GEMMA_TERMINAL_CUE = "<start_of_turn>model"
PERMITTED_TERMINAL_CUE_SCORER_KEYS = ("gemma",)


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def strip_llama_permitted_preamble(rendered_text: str) -> Tuple[str, List[str]]:
    """A3 R1. Remove the ONE permitted Llama preamble occurrence, or report why not.

    Returns (text_with_preamble_removed, problems). A non-empty problems list means the
    render violates the rule and must fail regardless of what the residual scan finds."""
    problems: List[str] = []
    n = rendered_text.count(LLAMA_TEMPLATE_PREAMBLE)
    if n == 0:
        problems.append("llama permitted preamble absent: expected exactly one occurrence "
                        "of the pinned 134-byte template preamble at position 0")
        return rendered_text, problems
    if n > 1:
        problems.append(f"llama permitted preamble occurs {n} times; exactly one is "
                        f"permitted (a second copy is not template boilerplate)")
        return rendered_text, problems
    if not rendered_text.startswith(LLAMA_TEMPLATE_PREAMBLE):
        problems.append("llama permitted preamble is present but NOT at position 0; only a "
                        "position-0 occurrence is template boilerplate")
        return rendered_text, problems
    # Byte-exactness is guaranteed by the literal comparison above; re-hash anyway so a
    # future edit to the constant cannot silently widen what is permitted.
    if _sha256_text(LLAMA_TEMPLATE_PREAMBLE) != LLAMA_TEMPLATE_PREAMBLE_SHA256:
        problems.append("llama permitted preamble constant does not match its pinned "
                        "sha256; refusing to strip anything")
        return rendered_text, problems
    return rendered_text[len(LLAMA_TEMPLATE_PREAMBLE):], problems


def strip_gemma_terminal_cue(rendered_text: str) -> Tuple[str, List[str]]:
    """A3 R2. Remove the terminal Gemma generation cue, or report why not.

    Trailing whitespace after the cue is permitted (the template emits a newline). The cue
    must occur exactly once in the WHOLE render and must be the terminal element."""
    problems: List[str] = []
    n = rendered_text.count(GEMMA_TERMINAL_CUE)
    if n == 0:
        problems.append(f"gemma terminal cue {GEMMA_TERMINAL_CUE!r} absent: expected "
                        f"exactly one occurrence as the terminal element")
        return rendered_text, problems
    if n > 1:
        problems.append(f"gemma terminal cue occurs {n} times; exactly one is permitted "
                        f"(a non-terminal copy is not a generation cue)")
        return rendered_text, problems
    stripped_tail = rendered_text.rstrip()
    if not stripped_tail.endswith(GEMMA_TERMINAL_CUE):
        problems.append("gemma cue is present but not at the terminal position; only a "
                        "terminal occurrence is a generation cue")
        return rendered_text, problems
    return stripped_tail[: -len(GEMMA_TERMINAL_CUE)], problems


@dataclass
class PreflightRenderCheck:
    scorer_key: str
    condition_name: str
    residual_words: List[str] = field(default_factory=list)
    date_hits: List[str] = field(default_factory=list)
    persona_hits: List[str] = field(default_factory=list)
    # A3 R1/R2: violations of a per-scorer permitted-structure rule (wrong count, wrong
    # position, non-terminal cue). Kept as its own channel so a structural violation fails
    # the render even when the residual scan happens to come back clean.
    structure_problems: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not (self.residual_words or self.date_hits or self.persona_hits
                    or self.structure_problems)

    @property
    def violations(self) -> List[str]:
        out = []
        if self.residual_words:
            out.append(f"test1_residual_content: {self.residual_words}")
        if self.date_hits:
            out.append(f"test2_date: {self.date_hits}")
        if self.persona_hits:
            out.append(f"test3_persona: {self.persona_hits}")
        if self.structure_problems:
            out.append(f"test6_permitted_structure: {self.structure_problems}")
        return out


def _strip_frozen_prompt_and_control_tokens(rendered_text: str, frozen_user_prompt: str,
                                            *, allow_empty_system_tags: bool,
                                            extra_control_tokens: Optional[Sequence[str]] = None
                                            ) -> str:
    residual = rendered_text.replace(frozen_user_prompt, "")
    if allow_empty_system_tags:
        residual = residual.replace("[SYSTEM_PROMPT][/SYSTEM_PROMPT]", "")
    for tok in list(CONTROL_TOKENS) + list(extra_control_tokens or ()):
        residual = residual.replace(tok, " ")
    return residual


def check_render(rendered_text: str, frozen_user_prompt: str, *, scorer_key: str,
                 condition_name: str, allow_empty_system_tags: bool,
                 extra_control_tokens: Optional[Sequence[str]] = None) -> PreflightRenderCheck:
    """Run the testable fail conditions against one rendered prompt string (test 4 is
    subsumed by test 1; test 5, reproducibility, is a hash comparison the caller does
    across runs).

    `extra_control_tokens` lets the caller supply the loaded tokenizer's OWN declared
    special tokens, so fail-condition 1's "the model's control/special tokens" is taken
    from the model rather than from this module's hardcoded list. Only ever removes the
    token strings themselves; content between delimiters is still tested.

    Amendment A3 R1/R2: for a scorer with a named permitted structure, that structure is
    removed FIRST and every subsequent scan -- residual, date AND persona -- runs on the
    remainder. For every other scorer the scanned text is the render itself, byte for byte,
    so no other scorer's checks are weakened. A structural violation is recorded separately
    and fails the render on its own."""
    structure_problems: List[str] = []
    scan_text = rendered_text

    if scorer_key in PERMITTED_PREAMBLE_SCORER_KEYS:
        scan_text, probs = strip_llama_permitted_preamble(scan_text)
        structure_problems += probs
    if scorer_key in PERMITTED_TERMINAL_CUE_SCORER_KEYS:
        scan_text, probs = strip_gemma_terminal_cue(scan_text)
        structure_problems += probs

    residual = _strip_frozen_prompt_and_control_tokens(
        scan_text, frozen_user_prompt, allow_empty_system_tags=allow_empty_system_tags,
        extra_control_tokens=extra_control_tokens)
    residual_words = _WORD_3PLUS.findall(residual)

    lower = scan_text.lower()
    date_hits = [m.group(0) for pat in _DATE_PATTERNS for m in pat.finditer(scan_text)]
    date_hits += [p for p in _DATE_PHRASES if p in lower]

    persona_hits = [m.group(0) for m in _PERSONA_PATTERN.finditer(scan_text)]
    persona_hits += [p for p in _PERSONA_PHRASES if p in lower]

    return PreflightRenderCheck(scorer_key=scorer_key, condition_name=condition_name,
                                residual_words=residual_words, date_hits=date_hits,
                                persona_hits=persona_hits,
                                structure_problems=structure_problems)
