# Spec: Genesis Markdown/20-Agents/Charting/Agent — Chart Markup.md
"""Candidates -> a Markup Spec. The selection step, with and without a model.

Agent — Chart Markup's system prompt draws the line this module implements:
*"Levels are computed by tools, not estimated by you. Never state a price you
did not receive from a tool call."* The model's job is **selection and
explanation**; the numbers are already decided by :mod:`levels`.

So there are two paths to a spec and they share everything except who chooses:

:func:`compose_default`
    Deterministic. Takes the strongest candidates, merges, caps, writes the
    machine ``why``. No model, no network, no cost. This is what runs when the
    LLM is unavailable, what the 3am loop uses, and what every test asserts
    against -- and it is a *complete* answer, not a stub. An agent whose
    fallback is "no chart" is an agent that stops working the moment a provider
    has a bad afternoon.

:func:`compose_selected`
    The model picked ids and rewrote the reasons. Every price still comes from
    the candidate it names, because the model returns **ids, never numbers** --
    which is the structural version of the prompt rule, and the reason a
    hallucinated price cannot reach a spec even if the model emits one.

The second is better prose. The first is never wrong. Both produce the same
object, and :func:`genesis.charting.spec.unsourced_prices` audits either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence

from genesis.charting.bars import Bars
from genesis.charting.levels import (
    FibCandidate,
    LevelCandidate,
    LevelComputation,
    LineCandidate,
    ZoneCandidate,
)
from genesis.charting.spec import (
    BarsRef,
    Fib,
    Level,
    Line,
    MarkupSpec,
    Structure,
    Zone,
)
from genesis.charting.structure import StructureRead

__all__ = [
    "Candidate",
    "candidate_table",
    "candidates",
    "compose_default",
    "compose_selected",
    "structure_of",
]


@dataclass(frozen=True)
class Candidate:
    """One offerable annotation, addressed by an id the model can return.

    The id is the whole mechanism. A model that answers ``["c3", "c7"]`` cannot
    invent a price; a model that answers ``[{"price": 122.10}]`` can, and will,
    eventually, on a chart where 122.10 is nearly right.
    """

    id: str
    kind: str
    label: str
    why: str
    strength: float
    source: str
    payload: Any
    #: Guaranteed a place on the chart regardless of what the model picks.
    always: bool = False

    def line(self) -> str:
        """One row of the table the model reads. Terse: this goes in a prompt."""
        item = self.payload
        if isinstance(item, LevelCandidate):
            where = f"{item.price:,.4g} ({item.distance_atr:+.1f} ATR, {item.touches} touches)"
        elif isinstance(item, ZoneCandidate):
            where = f"{item.low:,.4g}–{item.high:,.4g}"
        elif isinstance(item, LineCandidate):
            where = f"{item.points[0][1]:,.4g} → {item.points[-1][1]:,.4g}, {item.touches} touches"
        else:
            where = "swing anchors"
        keep = " [always drawn]" if self.always else ""
        return (
            f"{self.id}\t{self.kind}\t{self.label}\t{where}\t"
            f"strength {self.strength:.2f}\t{self.why}{keep}"
        )


def candidates(
    computation: LevelComputation, *, max_levels: int = 14
) -> list[Candidate]:
    """Everything the model may choose from, strongest first.

    Capped well above the annotation cap: the model needs enough to exercise
    judgement (which of these three near-identical resistances is the one?) and
    few enough that the table is not itself a context problem. Fourteen rows is
    a screenful.
    """
    out: list[Candidate] = []
    ranked = sorted(
        computation.levels,
        key=lambda c: (not c.always, -c.strength, abs(c.distance_atr)),
    )[:max_levels]
    for i, level in enumerate(ranked, start=1):
        out.append(
            Candidate(
                id=f"L{i}", kind="level", label=level.label, why=level.why,
                strength=level.strength, source=level.source, payload=level,
                always=level.always,
            )
        )
    for i, zone in enumerate(computation.zones, start=1):
        out.append(
            Candidate(
                id=f"Z{i}", kind="zone", label=zone.label, why=zone.why,
                strength=zone.strength, source=zone.source, payload=zone,
            )
        )
    for i, line in enumerate(computation.lines, start=1):
        out.append(
            Candidate(
                id=f"T{i}", kind="line", label=line.label, why=line.why,
                strength=line.strength, source="trendline", payload=line,
            )
        )
    for i, fib in enumerate(computation.fibs, start=1):
        out.append(
            Candidate(
                id=f"F{i}", kind="fib", label="fib retracement", why=fib.why,
                strength=0.4, source="fib", payload=fib,
            )
        )
    return out


def candidate_table(items: Sequence[Candidate]) -> str:
    """The candidate list as the prompt renders it."""
    header = "id\tkind\tlabel\twhere\tstrength\twhy"
    return "\n".join([header, *(c.line() for c in items)])


def structure_of(read: StructureRead, regime: str | None = None) -> Structure:
    import math

    return Structure(
        trend=read.trend,  # type: ignore[arg-type]
        swing=read.swing,  # type: ignore[arg-type]
        regime=regime,
        volatility_pct_rank=(
            round(read.volatility_pct_rank, 3)
            if math.isfinite(read.volatility_pct_rank)
            else None
        ),
        atr14=round(read.atr, 4),
        trend_strength=round(read.trend_strength, 3),
        range_high=round(read.range_high, 4),
        range_low=round(read.range_low, 4),
        contraction=round(read.contraction, 3),
    )


# --------------------------------------------------------------------------
# The two composition paths
# --------------------------------------------------------------------------


def compose_default(
    bars: Bars,
    computation: LevelComputation,
    read: StructureRead,
    *,
    max_annotations: int = 8,
    created_by: str = "chart-markup",
    trace_id: str | None = None,
    parent: str | None = None,
    regime: str | None = None,
) -> MarkupSpec:
    """The model-free spec. Complete, honest, and slightly duller prose."""
    items = candidates(computation)
    chosen = _default_selection(items, max_annotations)
    return _assemble(
        bars, computation, read, chosen, {},
        max_annotations=max_annotations, created_by=created_by,
        trace_id=trace_id, parent=parent, regime=regime,
    )


def compose_selected(
    bars: Bars,
    computation: LevelComputation,
    read: StructureRead,
    *,
    selected: Iterable[str],
    reasons: dict[str, str] | None = None,
    max_annotations: int = 8,
    created_by: str = "chart-markup",
    trace_id: str | None = None,
    parent: str | None = None,
    regime: str | None = None,
) -> MarkupSpec:
    """A spec from the model's chosen ids and rewritten reasons.

    Unknown ids are dropped rather than raising: a model that names ``L9`` on a
    chart with eight levels has made a recoverable mistake, and the useful
    behaviour is a chart with seven levels, not a failed task. ``always``
    candidates are re-added whatever the model said, because *"always include
    prior-period high and low"* is a rule about the chart, not a suggestion to
    the model.
    """
    items = candidates(computation)
    by_id = {c.id: c for c in items}
    picked = [by_id[i] for i in dict.fromkeys(selected) if i in by_id]
    for candidate in items:
        if candidate.always and candidate not in picked:
            picked.append(candidate)
    if not picked:
        picked = _default_selection(items, max_annotations)
    return _assemble(
        bars, computation, read, picked, reasons or {},
        max_annotations=max_annotations, created_by=created_by,
        trace_id=trace_id, parent=parent, regime=regime,
    )


def _default_selection(items: Sequence[Candidate], cap: int) -> list[Candidate]:
    """Always-levels first, then by strength, then one zone and one line.

    Reserving a slot each for a zone and a trendline is an editorial choice, not
    an accident of sorting: eight horizontal lines describe where price is, and
    one zone plus one line describes what shape it is in. A chart of only
    horizontals reads as a list.
    """
    levels = [c for c in items if c.kind == "level"]
    ranked = sorted(levels, key=lambda c: (not c.always, -c.strength))
    zones = sorted((c for c in items if c.kind == "zone"), key=lambda c: -c.strength)
    lines = sorted((c for c in items if c.kind == "line"), key=lambda c: -c.strength)

    reserved = min(1, len(zones)) + min(1, len(lines))
    chosen = ranked[: max(cap - reserved, 1)]
    chosen.extend(zones[:1])
    chosen.extend(lines[:1])
    return chosen[:cap]


def _assemble(
    bars: Bars,
    computation: LevelComputation,
    read: StructureRead,
    chosen: Sequence[Candidate],
    reasons: dict[str, str],
    *,
    max_annotations: int,
    created_by: str,
    trace_id: str | None,
    parent: str | None,
    regime: str | None,
) -> MarkupSpec:
    annotations: list[Any] = []
    for candidate in chosen:
        why = (reasons.get(candidate.id) or candidate.why).strip() or candidate.why
        item = candidate.payload
        if isinstance(item, LevelCandidate):
            annotations.append(
                Level(
                    price=item.price, label=item.label, type=item.type,
                    strength=min(max(item.strength, 0.0), 1.0),
                    touches=item.touches, confluence=item.confluence,
                    why=why, source=item.source,
                )
            )
        elif isinstance(item, ZoneCandidate):
            annotations.append(
                Zone(
                    **{"from": item.low, "to": item.high},
                    label=item.label, subtype=item.subtype, why=why, source=item.source,
                )
            )
        elif isinstance(item, LineCandidate):
            annotations.append(
                Line(
                    points=tuple((t.isoformat(), p) for t, p in item.points),
                    label=item.label, touches=item.touches, why=why, source="trendline",
                )
            )
        elif isinstance(item, FibCandidate):
            annotations.append(
                Fib(
                    anchor_from=(item.anchor_from[0].isoformat(), item.anchor_from[1]),
                    anchor_to=(item.anchor_to[0].isoformat(), item.anchor_to[1]),
                    retracements=item.retracements, label="fib", why=why, source="fib",
                )
            )

    return MarkupSpec.build(
        symbol=bars.symbol,
        timeframe=bars.timeframe,
        as_of=bars.last_time,
        bars_ref=BarsRef(
            source=bars.source,
            **{
                "from": bars.first_time.date().isoformat(),
                "to": bars.last_time.date().isoformat(),
            },
            adjusted=bars.adjusted, bars=len(bars), tier=bars.tier,
        ),
        annotations=annotations,
        structure=structure_of(read, regime),
        created_by=created_by,
        trace_id=trace_id,
        parent=parent,
        degraded=computation.degraded,
        max_annotations=max_annotations,
    )
