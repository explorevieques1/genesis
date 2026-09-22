# Spec: Genesis Markdown/20-Agents/Research/Agent — News And Catalyst.md · 70-Schemas/Idea Schema.md
"""The brief's trade ideas, promoted into the one idea store.

A news brief already ends with `trade_ideas`: a bias, the symbols, why, and
what would prove it wrong. Until this module they lived inside the brief's JSON
and died there -- readable in a note, invisible to everything that ranks, sizes
or measures an idea. This turns them into `Idea` records, which is the only
shape the rest of Genesis understands.

**One store, not a second one.** Session Plan's rule is "one store, one shape,
and a plan ranks both" -- the trader's ideas and the synthesizer's sit in the
same place and compete on merit. A news idea is a third author, not a third
store. It is ranked by the same plan, sized by the same gate's dry run, and
measured by the same journal.

**The invalidation survives, or the idea does not exist.** Idea Schema: an idea
without a stated invalidation is a hope, and a hope that reaches the dashboard
looking like an idea is the expensive failure. The brief's own `invalidation`
becomes the record's, untouched -- and an idea that arrives without one is
dropped here rather than patched with a guess.

**`watch` is not an idea.** A third of what a brief produces is "something is
happening here", with no side. `Idea` requires a direction and would reject it,
and inventing one to make it fit is how a watch item becomes a position. They
are kept as watch items: same origin, same evidence, no direction, and nothing
in the system will size one.

**Untrusted all the way down.** This text came from a model reading articles
written by strangers. It is stored, shown and cited; it never becomes an
instruction, and nothing here can place an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from genesis.research.schema import Idea, ResearchNote
from genesis.research.store import ResearchStore, new_note_id

__all__ = ["NEWS_AUTHOR", "Promoted", "promote_brief"]

#: The author on every idea that came from a brief. The plan, the `TI` module
#: and the weekly review all group by it, so "how are the news ideas doing"
#: is a question with an answer.
NEWS_AUTHOR = "news-catalyst"


@dataclass
class Promoted:
    """What one brief produced. Dropped ideas are counted, never hidden."""

    ideas: list[str]
    watching: list[str]
    dropped: list[str]
    #: Ideas the brief did not write, found in its text. Counted apart from
    #: `ideas` because they rest on a weaker signal and the operator should be
    #: able to see the difference at a glance.
    extracted: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ideas": self.ideas, "watching": self.watching,
                "extracted": self.extracted, "dropped": self.dropped}


def _symbol(idea: dict[str, Any]) -> str:
    """The first symbol, upper-cased. A news idea names its own instruments.

    No model is asked what "energy" resolves to -- Operating Model §4, nobody
    knows the ticker. If the brief did not name a symbol there is nothing to
    trade and the idea is dropped.
    """
    for raw in idea.get("symbols") or []:
        text = str(raw).strip().upper()
        if text:
            return text
    return ""


def _thesis(idea: dict[str, Any]) -> str:
    headline = str(idea.get("idea") or "").strip()
    rationale = str(idea.get("rationale") or "").strip()
    if headline and rationale and rationale not in headline:
        return f"{headline}\n\n{rationale}"
    return headline or rationale


def promote_brief(
    store: ResearchStore,
    brief: dict[str, Any],
    *,
    trace_id: str | None = None,
    horizon_days: int = 5,
    setup_for: Callable[[str, str], Any] | None = None,
    universe: Any = None,
    extracted: int = 4,
) -> Promoted:
    """Every tradeable idea in a brief, stored. Returns what happened to each.

    ``setup_for(symbol, direction)`` is :func:`genesis.research.setup.compute_setup`
    when there is market data to reach -- injected rather than imported so this
    module stays testable without a bar store, and so a brief can still be
    promoted on a machine with no data at all.

    It is what turns a worded idea into a sizeable one. The brief gives a
    direction and an invalidation in words; the setup adds the entry zone, the
    stop and the targets, computed from bars by the charting engine. Without it
    the idea is stored anyway and shown unsized -- an idea with no numeric
    invalidation is not a guess, it is an idea the gate declines to size.
    """
    body = brief.get("body") if isinstance(brief.get("body"), dict) else brief
    brief_id = str(brief.get("id") or body.get("id") or "")
    title = str(brief.get("title") or "news brief")
    out = Promoted(ideas=[], watching=[], dropped=[])

    for raw in body.get("trade_ideas") or []:
        if not isinstance(raw, dict):
            continue
        symbol = _symbol(raw)
        bias = str(raw.get("bias") or "").strip().lower()
        thesis = _thesis(raw)
        invalidation = str(raw.get("invalidation") or "").strip()
        label = f"{symbol or '?'}: {str(raw.get('idea') or '')[:60]}"

        if not symbol:
            out.dropped.append(f"{label} — the brief named no symbol")
            continue
        if not invalidation:
            # Idea Schema's rule, applied to a model's output exactly as it is
            # applied to the trader's: no invalidation, no idea.
            out.dropped.append(f"{label} — no invalidation stated")
            continue
        if bias not in ("long", "short"):
            out.watching.append(_watch(store, raw, symbol, brief_id, title, trace_id).id)
            continue

        setup = _setup(setup_for, symbol, bias, out, label)
        try:
            idea = Idea(
                symbol=symbol,
                direction=bias,
                thesis=thesis,
                invalidation=invalidation,
                invalidation_reason=(
                    f"stated in the brief “{title}”"
                    + (f"; priced from the chart — {setup['stop_why']}" if setup else "")
                ),
                # Honest rather than empty. Idea Schema: an absent
                # counter-argument usually means nobody looked -- and here
                # nobody did. A brief argues one side by construction.
                conflicts="not assessed — a news brief states one side; check it before sizing",
                timeframe="swing",
                horizon_days=horizon_days,
                confidence=float(body.get("confidence") or 0.4),
                evidence=tuple(filter(None, [brief_id])),
                setup="news catalyst",
                author=NEWS_AUTHOR,
                # The computed half. Absent when there were no bars, which is a
                # state the plan already knows how to show: unsized, with the
                # reason.
                entry_zone=tuple(setup["entry_zone"]) if setup else None,
                stop_price=setup["stop"] if setup else None,
                targets=tuple(setup["targets"]) if setup else (),
            )
        except Exception as exc:  # noqa: BLE001 - a malformed idea is dropped, never patched
            out.dropped.append(f"{label} — {type(exc).__name__}")
            continue
        out.ideas.append(_store_idea(store, idea, raw, brief_id, title, trace_id, setup).id)

    if universe is not None and extracted:
        _from_text(store, body, brief_id, title, out, trace_id,
                   universe=universe, setup_for=setup_for,
                   horizon_days=horizon_days, limit=extracted)
    return out


def _from_text(
    store: ResearchStore, body: dict[str, Any], brief_id: str, title: str,
    out: Promoted, trace_id: str | None, *, universe: Any,
    setup_for: Callable[[str, str], Any] | None, horizon_days: int, limit: int,
) -> None:
    """Ideas for the symbols the brief is *about* but never wrote a trade for.

    A brief ends with two or three trade ideas and mentions a dozen companies.
    The rest are where the reading actually happened — a bearish story naming
    four names produces no trade idea at all, and those four were the point.

    The invalidation for one of these comes from the **chart**, not the text:
    the story is the thesis, and the structural stop is what would prove it
    wrong. That inversion is what makes it a legitimate idea rather than a
    headline with a ticker attached — and it means a symbol whose chart cannot
    be read produces nothing, because there would be no invalidation.
    """
    from genesis.news.symbols import extract

    already = {
        str((raw.get("symbols") or [""])[0]).upper()
        for raw in body.get("trade_ideas") or []
        if isinstance(raw, dict) and raw.get("symbols")
    }
    for mention in extract(body, universe=universe, limit=limit + len(already)):
        if mention.symbol in already or len(out.extracted) >= limit:
            continue
        label = f"{mention.symbol}: {(mention.stories or [''])[0][:50]}"
        if mention.direction == "watch":
            # No side. Kept as something to look at, never sized -- and a
            # conflicted symbol says so, because "the brief argues both ways"
            # is more useful than silence.
            out.watching.append(_watch(store, {
                "idea": (mention.stories or [mention.symbol])[0],
                "rationale": "; ".join(mention.why[:3]),
                "invalidation": ("the brief points both ways on this one"
                                 if mention.conflicted else "no direction stated"),
                "symbols": [mention.symbol],
            }, mention.symbol, brief_id, title, trace_id).id)
            continue

        setup = _setup(setup_for, mention.symbol, mention.direction, out, label)
        if not setup:
            out.dropped.append(f"{label} — no chart, so no invalidation price")
            continue

        thesis = "\n\n".join(filter(None, [
            (mention.stories or [""])[0],
            "Found in the brief by: " + "; ".join(mention.why[:3]) + ".",
        ]))
        try:
            idea = Idea(
                symbol=mention.symbol,
                direction=mention.direction,
                thesis=thesis or f"{mention.symbol} is what the brief is about.",
                # Stated as a price, because that is where it came from.
                invalidation=(
                    f"a close beyond {setup['stop']:,.2f} — {setup['stop_why']}"
                ),
                invalidation_reason=(
                    f"the brief gave the thesis, the chart gave the level "
                    f"(ATR {setup['atr']:,.2f}, {setup['trend']})"
                ),
                conflicts=(
                    "not assessed — extracted from a news story, which argues one side"
                ),
                timeframe="swing",
                horizon_days=horizon_days,
                # Never as confident as an idea the brief wrote on purpose.
                confidence=min(0.45, float(body.get("confidence") or 0.4)),
                evidence=tuple(filter(None, [brief_id])),
                setup="news mention",
                author=NEWS_AUTHOR,
                entry_zone=tuple(setup["entry_zone"]),
                stop_price=setup["stop"],
                targets=tuple(setup["targets"]),
            )
        except Exception as exc:  # noqa: BLE001
            out.dropped.append(f"{label} — {type(exc).__name__}")
            continue
        note = _store_idea(store, idea, {
            "idea": (mention.stories or [mention.symbol])[0],
            "symbols": [mention.symbol],
        }, brief_id, title, trace_id, setup, mention=mention)
        out.extracted.append(note.id)


def _setup(
    setup_for: Callable[[str, str], Any] | None,
    symbol: str, direction: str, out: Promoted, label: str,
) -> dict[str, Any] | None:
    """The computed setup, or ``None`` with the reason noted.

    Never fatal. A symbol with no bars, a vendor that is down, an ATR of zero --
    all of them mean *this idea is unsized*, which the desk already displays
    honestly. Losing the whole idea because its chart could not be read would
    throw away the thesis as well as the prices.
    """
    if setup_for is None:
        return None
    try:
        computed = setup_for(symbol, direction)
    except Exception as exc:  # noqa: BLE001 - a chart that cannot be read is not a fatal error
        out.dropped.append(f"{label} — kept unsized: {getattr(exc, 'reason', None) or exc}")
        return None
    return computed.as_dict() if hasattr(computed, "as_dict") else dict(computed)


def _store_idea(
    store: ResearchStore, idea: Idea, raw: dict[str, Any],
    brief_id: str, title: str, trace_id: str | None,
    setup: dict[str, Any] | None = None,
    mention: Any = None,
) -> ResearchNote:
    body = "\n\n".join([
        f"## Thesis\n\n{idea.thesis}",
        f"## Invalidation\n\n**{idea.invalidation}**\n\n{idea.invalidation_reason}",
        f"## Against it\n\n{idea.conflicts}",
        _setup_markdown(setup),
        f"## Source\n\nFrom the news brief *{title}*"
        + (f" (`{brief_id}`)" if brief_id else "") + ".",
    ])
    return store.put(ResearchNote(
        id=new_note_id(),
        kind="idea",
        title=f"{idea.symbol} {idea.direction} — news catalyst",
        # Its own subject namespace, like the trader's `nq-long` and the
        # synthesizer's `nq`: a news idea must not supersede either of theirs,
        # and theirs must not silently overwrite one of these.
        subject=f"{idea.symbol.lower()}-news-{idea.direction}",
        created_by=NEWS_AUTHOR,
        summary=f"{idea.direction.capitalize()} {idea.symbol} — {str(raw.get('idea') or '')[:90]}",
        body=body,
        tags=("idea", "news", idea.symbol.lower(), idea.timeframe),
        data={**idea.model_dump(mode="json"), "status": "active",
              "brief_id": brief_id, "brief_title": title,
              # The whole computation, kept: the levels it chose between, the
              # trend it read, the bars and the feed they came from. An idea
              # that cannot show its work is an assertion.
              #
              # `chart_setup`, NOT `setup`: `Idea.setup` is already a string
              # field ("news catalyst"), and writing a dict over it made
              # `live_ideas` fail to revalidate the note and skip it. Silently
              # -- a malformed stored idea is skipped by design, so every
              # priced idea simply stopped existing on the desk.
              "chart_setup": setup,
              # How this symbol was found, when it was not handed over tagged.
              # `TI` shows it, because "extracted from the text" and "the brief
              # wrote this trade" are different claims.
              "found_by": mention.as_dict() if mention is not None else None,
              "symbols": [str(s).upper() for s in (raw.get("symbols") or [])]},
        half_life_hours=max(24.0, idea.horizon_days * 24.0),
        confidence=idea.confidence,
        trace_id=trace_id,
    ))


def _setup_markdown(setup: dict[str, Any] | None) -> str:
    """The computed setup as prose, for the note a person reads in Obsidian."""
    if not setup:
        return "## Setup\n\nNot priced — no usable bars for this symbol."
    low, high = setup["entry_zone"]
    return "\n".join([
        "## Setup",
        "",
        f"- Spot **{setup['spot']:,.2f}** · ATR(14) {setup['atr']:,.2f} · "
        f"{setup['trend']} / {setup['swing']}",
        f"- Entry **{low:,.2f} – {high:,.2f}**",
        f"- Stop **{setup['stop']:,.2f}** — {setup['stop_why']}",
        "- Targets " + " · ".join(f"**{t:,.2f}**" for t in setup["targets"])
        + f" ({setup['rr']}R)",
        f"- Risk {setup['risk_per_unit']:,.2f} per unit, from {setup['bars']} bars "
        f"({setup['source']}, tier {setup['tier']})",
        *[f"- ⚠️ {w}" for w in setup.get("warnings") or ()],
    ])


def _watch(
    store: ResearchStore, raw: dict[str, Any], symbol: str,
    brief_id: str, title: str, trace_id: str | None,
) -> ResearchNote:
    """A brief's `watch` item: a reason to look, with no side.

    Stored as a `finding`, not an `idea`, which is what keeps it out of every
    path that sizes. `live_ideas` reads `kind="idea"` and will never see it.
    """
    return store.put(ResearchNote(
        id=new_note_id(),
        kind="finding",
        title=f"{symbol} — watching (news)",
        subject=f"{symbol.lower()}-watch",
        created_by=NEWS_AUTHOR,
        summary=str(raw.get("idea") or "")[:120],
        body="\n\n".join([
            f"## Why\n\n{str(raw.get('rationale') or '').strip()}",
            f"## What would settle it\n\n{str(raw.get('invalidation') or '').strip()}",
            f"## Source\n\nFrom the news brief *{title}*"
            + (f" (`{brief_id}`)" if brief_id else "") + ".",
        ]),
        tags=("watch", "news", symbol.lower()),
        data={"symbol": symbol, "bias": "watch", "status": "active",
              "idea": str(raw.get("idea") or ""),
              "rationale": str(raw.get("rationale") or ""),
              "invalidation": str(raw.get("invalidation") or ""),
              "symbols": [str(s).upper() for s in (raw.get("symbols") or [])],
              "brief_id": brief_id, "brief_title": title},
        half_life_hours=72.0,
        trace_id=trace_id,
    ))
