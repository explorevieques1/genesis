# Spec: Genesis Markdown/20-Agents/Journal/Journal Family.md
"""Where the rest of the system deposits things worth learning from.

The Journal Family's learning loop is drawn from trades, and trades need Phase 7.
But the loop does not have to wait, and this module is why: the charting family
is already producing scoreable outcomes, and every one of them is evidence a
lesson might later rest on.

> After a few hundred marked levels, Agent — Insight Miner can tell you that your
> anchored-VWAP levels hold 70% of the time and your hand-drawn trendlines hold
> 40%. That is a real, personal edge, and it exists only because the markup is
> structured rather than drawn.

That finding needs one thing to be true: **somebody has to write each outcome
down at the time.** Not reconstruct it later -- a level's outcome depends on the
spec that was active when price reached it, and once the spec has been re-marked
the original question is unanswerable. So the recording happens at the moment of
scoring, here, and it costs one row.

Deliberately thin, and deliberately not an agent. Agent Contract rule 1 forbids
agents calling each other; these are functions the *journal store* exposes to
whatever produced the fact, so nothing here creates a dependency between two
agents.
"""

from __future__ import annotations

from typing import Any, Iterable

from genesis.errors import FatalError
from genesis.journal.schema import Observation
from genesis.journal.store import JournalStore

__all__ = [
    "MARK_KINDS",
    "MAX_NOTE_CHARS",
    "record_idea_outcome",
    "record_level_fire",
    "marks",
    "record_mark",
    "record_spec_outcome",
]

#: What a marked range of candles can be about. Closed, because the Insight
#: Miner aggregates on it: a free-text kind is a bucket of one.
MARK_KINDS = ("entry", "exit", "idea")

#: A note, not an essay. The write-up belongs in the Notebook, which a mark
#: can link to.
MAX_NOTE_CHARS = 2000


def record_spec_outcome(store: JournalStore, outcome: Any) -> int:
    """A scored Markup Spec's levels, one observation each.

    ``outcome`` is a :class:`~genesis.charting.outcomes.SpecOutcome`. Untested
    levels are recorded too, and that matters: excluding them would quietly
    inflate every hold rate, because a level type that is often drawn far from
    price would only ever be counted on the occasions it was reached.

    ``source`` carries the *derivation* -- ``anchored-vwap``, ``sr-cluster``,
    ``trendline`` -- because the question worth answering is not "do my levels
    hold" but "which kind of level holds".
    """
    written = 0
    for level in getattr(outcome, "levels", ()):
        store.record(
            Observation(
                kind="level.outcome",
                subject=f"level:{outcome.symbol}:{level.price:.2f}",
                outcome=level.outcome,
                value=level.max_reaction_atr,
                unit="ATR",
                source=level.source or "unknown",
                detail={
                    "spec": outcome.spec_id,
                    "timeframe": outcome.timeframe,
                    "label": level.label,
                    "type": level.type,
                    "tests": level.tests,
                    "breaks": level.breaks,
                    "bars_since": outcome.bars_since,
                },
            )
        )
        written += 1
    return written


def record_level_fire(store: JournalStore, fire: Any) -> Observation:
    """One live level event, as it happens.

    Separate from :func:`record_spec_outcome` because they answer different
    questions: a fire is *"price reached this"*, an outcome is *"and then this
    happened"*. Conflating them would make a level that was touched forty times
    look like forty levels.
    """
    watch = fire.watch
    return store.record(
        Observation(
            kind=f"level.{fire.watch_type}",
            subject=f"level:{fire.symbol}:{watch.price:.2f}",
            outcome=fire.watch_type,
            value=fire.price,
            unit="price",
            source=watch.level_type or watch.kind,
            detail={
                "spec": watch.spec_id,
                "label": watch.label,
                "timeframe": watch.timeframe,
                "priority": fire.priority,
                "spoken": fire.spoken,
                **{k: v for k, v in fire.context.items() if k != "why"},
            },
        )
    )


def record_idea_outcome(
    store: JournalStore,
    idea_id: str,
    *,
    taken: bool,
    realised_r: float | None,
    confidence: float | None = None,
    symbol: str = "",
) -> Observation:
    """An idea, and whether it was acted on — including when it was not.

    The skipped ones are the point. *"You skipped 4 of your 6 highest-confidence
    ideas last month; they averaged +0.9R"* is only computable because a skipped
    idea leaves a record, and a skipped idea leaves no trade — so the journal
    alone can never answer it.
    """
    return store.record(
        Observation(
            kind="idea.outcome",
            subject=idea_id,
            outcome="taken" if taken else "skipped",
            value=realised_r,
            unit="R",
            source="idea-synthesizer",
            detail={"confidence": confidence, "symbol": symbol},
        )
    )


def record_mark(
    store: JournalStore,
    *,
    kind: str,
    symbol: str,
    timeframe: str,
    start: int,
    end: int,
    note: str = "",
    series: str = "",
    drawing_id: str = "",
    entry_id: str = "",
    trace_id: str | None = None,
) -> Observation:
    """A range of candles the trader marked, and what they said about it.

    The one thing in the journal a **person** authors. Everything else here is
    deposited by whatever scored an outcome; this is the trader saying *"this
    is where I got in, and this is what I was thinking"* over bars they
    selected on a chart.

    Two records, by context, and that split is the design:

    * Always an :class:`Observation` (``mark.entry`` / ``mark.exit`` /
      ``mark.idea``). Observations are not trade-shaped, so an idea that was
      never taken still leaves evidence the [[Agent — Insight Miner]] can
      aggregate — which is the half a fill-driven journal can never see.
    * When ``entry_id`` names a real trade, the mark is also appended to that
      entry's **human half** (``notes``, ``tags``), which is the only mutation
      [[Trade Journal Schema]] permits. The machine half is frozen by a
      trigger and is not touched: a hand-drawn range must never be able to
      reach the arithmetic the Performance Analyst reasons over.

    ``start`` and ``end`` are epoch seconds, the chart's own time axis, so a
    mark reopens exactly the bars it was drawn over.
    """
    if kind not in MARK_KINDS:
        raise ValueError(f"mark kind {kind!r} is not one of {', '.join(MARK_KINDS)}")
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("a mark needs the symbol it was drawn on")
    start, end = int(start), int(end)
    if end <= start:
        raise ValueError(f"a mark's window ends before it starts ({start} → {end})")
    note = note.strip()[:MAX_NOTE_CHARS]

    observation = store.record(
        Observation(
            kind=f"mark.{kind}",
            # The thing the fact is about, so marks aggregate per instrument
            # rather than per drawing.
            subject=symbol,
            outcome=kind,
            source="operator",
            trace_id=trace_id,
            detail={
                "symbol": symbol, "timeframe": timeframe,
                "start": start, "end": end,
                "series": series or f"{symbol}|{timeframe}",
                "drawing_id": drawing_id, "note": note, "entry_id": entry_id,
            },
        )
    )
    if entry_id:
        entry = store.entry(entry_id)
        if entry is None:
            raise FatalError(f"no journal entry {entry_id!r} to attach this mark to")
        stamped = f"[{observation.id}] {kind}: {note}".strip()
        store.patch_human(
            entry_id,
            notes="\n".join(x for x in (entry.notes, stamped) if x),
            tags=tuple(dict.fromkeys((*entry.tags, f"mark:{observation.id}"))),
        )
    return observation


def marks(store: JournalStore, *, symbol: str = "", limit: int = 200) -> list[Observation]:
    """Marked ranges, newest first. ``kind="mark"`` prefix-matches all three."""
    found = store.observations(kind="mark", subject=symbol.strip().upper() or None, limit=limit)
    return sorted(found, key=lambda o: o.at, reverse=True)
