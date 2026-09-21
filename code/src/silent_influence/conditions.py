"""Prior-context conditions.

Conditions are data, not templates. `no_history` is a first-class baseline and is
deliberately NOT the same object as a mid-valued score condition: it answers whether a
history is present at all, which is a different question from what the history says.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

NO_HISTORY = "no_history"
SCORE_MIN = 1
SCORE_MAX = 10

# Post-hoc exploratory boundary extension, added after the 1-10 sweep was frozen.
# Deliberately NOT a member of FULL_SWEEP: folding it into the confirmatory sweep would
# retroactively redefine a frozen result. It is also NOT no_history — score_0 carries the
# same history sentence with the numeral 0, whereas no_history has no sentence at all, so
# the two answer different questions and must never share an axis.
SCORE_EXPLORATORY = 0


@dataclass(frozen=True)
class PriorContext:
    name: str
    score: Optional[int]  # None renders no history block at all

    @property
    def has_history(self) -> bool:
        return self.score is not None


def score_condition(value: int) -> PriorContext:
    if value != SCORE_EXPLORATORY and not (SCORE_MIN <= value <= SCORE_MAX):
        raise ValueError(f"prior score {value} outside {SCORE_MIN}-{SCORE_MAX} "
                         f"(and not the exploratory {SCORE_EXPLORATORY})")
    return PriorContext(f"score_{value}", value)


NO_HISTORY_CONDITION = PriorContext(NO_HISTORY, None)

# Full 1-10 sweep plus the no-history baseline. Phase 1A uses all of these; the final
# low/neutral/high triple is chosen afterwards, not here.
FULL_SWEEP: List[PriorContext] = [NO_HISTORY_CONDITION] + [
    score_condition(v) for v in range(SCORE_MIN, SCORE_MAX + 1)
]

SCORE_0_CONDITION = score_condition(SCORE_EXPLORATORY)

# Resolvable by name so a config can request it, without being part of FULL_SWEEP.
_BY_NAME = {c.name: c for c in [*FULL_SWEEP, SCORE_0_CONDITION]}


def resolve(name: str) -> PriorContext:
    if name not in _BY_NAME:
        raise KeyError(f"unknown prior-context condition {name!r}; "
                       f"known: {sorted(_BY_NAME)}")
    return _BY_NAME[name]


def resolve_many(names: List[str]) -> List[PriorContext]:
    return [resolve(n) for n in names]
