# Spec: Genesis Markdown/20-Agents/Charting/Charting Family.md
"""Did the level hold? The question no charting platform can answer for you.

Charting Family.md calls this the family's distinctive edge, and it is worth
quoting because it is the reason the Markup Spec is an object at all:

> After a few hundred marked levels, Agent — Insight Miner can tell you that
> your anchored-VWAP levels hold 70% of the time and your hand-drawn trendlines
> hold 40%. That is a real, personal edge, and it exists only because the markup
> is structured rather than drawn.

Turning that into arithmetic needs one definition to be right, and it is the
same distinction Agent — Level Watcher is built around:

**A wick through a level is not a break. A close beyond it is.**

Conflate them and every level "breaks" on its first test, the hold rates all
collapse toward zero, and the statistic becomes noise. So :func:`evaluate`
classifies on closes, and records the wick separately as a *test* -- which is
the interesting case, because a level that is wicked and reclaimed is a level
that worked.

Four outcomes, and ``untested`` is not a failure to classify -- it is the honest
answer for a level price never reached, and excluding it from hold rates is what
stops "levels far from price" from inflating a strategy's apparent accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

import numpy as np

from genesis.charting import indicators as ind
from genesis.charting.bars import Bars
from genesis.charting.spec import Level, MarkupSpec

__all__ = ["LevelOutcome", "SpecOutcome", "evaluate"]

Outcome = Literal["held", "broke", "reclaimed", "untested"]

#: How close price must come to count as a test, in ATR. Tolerance in ATR and
#: not cents, because 10c means different things on a $5 and a $500 stock --
#: Agent — Level Watcher states this as a design constraint and it applies
#: identically to scoring after the fact.
TEST_ATR = 0.15


@dataclass(frozen=True)
class LevelOutcome:
    """What happened to one level after the spec was written."""

    label: str
    price: float
    type: str
    source: str
    outcome: Outcome
    tests: int
    #: Closes beyond the level, on the level's own timeframe.
    breaks: int
    #: Furthest price moved away from the level after touching, in ATR. The
    #: magnitude of the reaction -- a level that produced a 3 ATR bounce is a
    #: different object from one that produced a 0.2 ATR pause, and both
    #: register as "held".
    max_reaction_atr: float
    first_test: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "price": round(self.price, 4),
            "type": self.type,
            "source": self.source,
            "outcome": self.outcome,
            "tests": self.tests,
            "breaks": self.breaks,
            "max_reaction_atr": round(self.max_reaction_atr, 2),
            "first_test": self.first_test,
        }


@dataclass(frozen=True)
class SpecOutcome:
    """The whole spec, scored against what price did next."""

    spec_id: str
    symbol: str
    timeframe: str
    as_of: datetime
    evaluated_to: datetime
    bars_since: int
    levels: tuple[LevelOutcome, ...]

    @property
    def hold_rate(self) -> float | None:
        """Held / tested. ``None`` when nothing was tested.

        ``None`` rather than 0.0, and the distinction is the whole point: a spec
        whose levels price never reached has no hold rate, and reporting one as
        zero would drag every aggregate down with charts that were never
        examined.
        """
        tested = [level for level in self.levels if level.outcome != "untested"]
        if not tested:
            return None
        held = sum(1 for level in tested if level.outcome in ("held", "reclaimed"))
        return held / len(tested)

    def to_dict(self) -> dict[str, object]:
        return {
            "spec_id": self.spec_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "as_of": self.as_of.isoformat(),
            "evaluated_to": self.evaluated_to.isoformat(),
            "bars_since": self.bars_since,
            "hold_rate": (
                round(self.hold_rate, 3) if self.hold_rate is not None else None
            ),
            "levels": [level.to_dict() for level in self.levels],
        }

    def summary(self) -> str:
        if not self.bars_since:
            return f"No bars since {self.as_of.date().isoformat()} — nothing to score yet."
        rate = self.hold_rate
        tested = [level for level in self.levels if level.outcome != "untested"]
        if rate is None:
            return (
                f"{self.bars_since} bars since the mark; price never reached any "
                f"of the {len(self.levels)} levels."
            )
        broke = [level for level in tested if level.outcome == "broke"]
        line = (
            f"{len(tested)} of {len(self.levels)} levels tested over "
            f"{self.bars_since} bars, {rate:.0%} held."
        )
        if broke:
            line += " Broke: " + ", ".join(f"{b.label} {b.price:,.2f}" for b in broke) + "."
        return line


def evaluate(spec: MarkupSpec, bars: Bars) -> SpecOutcome:
    """Score a spec's levels against the bars that came after it.

    ``bars`` may span the whole history; only the part after ``spec.as_of`` is
    used. Passing the full frame rather than a pre-sliced one is deliberate --
    the ATR the tolerance is measured in should come from the *whole* window, not
    from the handful of bars since the mark, which on a quiet week would shrink
    the tolerance until nothing counted as a test.
    """
    atr = ind.last_atr(bars) or (bars.last * 0.01)
    start = _first_index_after(bars, spec.as_of)
    after = bars.tail(len(bars) - start) if start < len(bars) else None

    outcomes: list[LevelOutcome] = []
    for level in spec.levels():
        outcomes.append(_score(level, after, atr))

    return SpecOutcome(
        spec_id=spec.id,
        symbol=spec.symbol,
        timeframe=spec.timeframe,
        as_of=spec.as_of,
        evaluated_to=bars.last_time,
        bars_since=len(after) if after is not None else 0,
        levels=tuple(outcomes),
    )


def _score(level: Level, after: Bars | None, atr: float) -> LevelOutcome:
    if after is None or len(after) == 0:
        return LevelOutcome(
            label=level.label, price=level.price, type=level.type,
            source=level.source, outcome="untested", tests=0, breaks=0,
            max_reaction_atr=0.0,
        )

    band = atr * TEST_ATR
    touched = np.where(
        (after.low <= level.price + band) & (after.high >= level.price - band)
    )[0]
    if len(touched) == 0:
        return LevelOutcome(
            label=level.label, price=level.price, type=level.type,
            source=level.source, outcome="untested", tests=0, breaks=0,
            max_reaction_atr=0.0,
        )

    # Direction of approach decides what "beyond" means. A resistance breaks on
    # a close above; a support breaks on a close below. For a pivot or a moving
    # average, the side price came from is the side that defines the break --
    # taken from the first test rather than assumed, because a moving average
    # is approached from both sides over a long enough window.
    first = int(touched[0])
    from_below = bool(after.close[max(first - 1, 0)] <= level.price)
    if level.type == "resistance":
        from_below = True
    elif level.type == "support":
        from_below = False

    beyond = (
        after.close[first:] > level.price + band
        if from_below
        else after.close[first:] < level.price - band
    )
    breaks = int(beyond.sum())

    reaction = float(np.abs(after.close[first:] - level.price).max() / atr) if atr else 0.0

    if breaks == 0:
        outcome: Outcome = "held"
    else:
        # A reclaim: it closed beyond, then closed back on the original side and
        # stayed there. Distinguished from a break because it is the opposite
        # information -- a level that was lost and taken back is a level that is
        # working, and lumping the two together is what makes trendline
        # statistics meaningless.
        back = (
            after.close[-1] <= level.price + band
            if from_below
            else after.close[-1] >= level.price - band
        )
        outcome = "reclaimed" if back else "broke"

    return LevelOutcome(
        label=level.label, price=level.price, type=level.type,
        source=level.source, outcome=outcome, tests=len(touched), breaks=breaks,
        max_reaction_atr=reaction,
        first_test=after.times[first].date().isoformat(),
    )


def _first_index_after(bars: Bars, when: datetime) -> int:
    for i, stamp in enumerate(bars.times):
        if stamp > when:
            return i
    return len(bars)
