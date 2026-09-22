# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""The store, wearing the interface the Charting Engine already expects.

``charting/source.py`` says what this module has to be, in one sentence:

    When Market Data Plane's store lands, ``GatewayBarSource`` is the thing it
    replaces, and nothing above this interface changes -- which is the point of
    the interface existing before the store does.

So :class:`StoreBarSource` implements
:class:`~genesis.charting.source.BarSource` -- ``fetch(symbol, timeframe, *,
bars=0) -> Bars`` -- and that is the whole public surface. No new bar
interface was designed and none was needed. The Charting Family swaps over by
constructing a different object, and there is a test that proves it rather than
a comment that asserts it.

**Where the fallback chain lives.** Market Data Sources gives each consumer an
ordered list of sources; Market Data Plane says that chain must resolve in one
place instead of inside each agent. This is that place:

    store hit (fresh enough, at or above the minimum tier)
      └─ miss → the adapter chain, in order, first one that can answer
           └─ all fail → a typed failure. Never a guess.
      ↳ anything fetched is written to the store on the way back

**Why the second run makes no network calls.** The store is asked first, and
the coverage table -- not the presence of bars -- decides whether the window
has already been fetched. That distinction is what makes a holiday, a weekend
and an unlisted contract free to ask about twice. See
:mod:`genesis.marketdata.store`.

**Where Decimal becomes float.** Here, in :func:`to_bars`, and nowhere else.
The store is the money truth and holds ``Decimal``;
:class:`~genesis.charting.bars.Bars` is a drawing buffer full of numpy floats
because every consumer of it does element-wise arithmetic over a few hundred
values. Both are right for their job. What would be wrong is a float in the
store, and this is the seam that keeps one out.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Sequence

import numpy as np

from genesis.charting.bars import Bars
from genesis.charting.source import lookback_start
from genesis.charting.timeframes import resolve
from genesis.errors import DegradedError, GenesisError
from genesis.marketdata.budget import Budget, BudgetExceeded
from genesis.marketdata.interface import Adapter, BarRequest, chunk_request
from genesis.marketdata.normalize import Bar, parse_instrument_id
from genesis.marketdata.staleness import Freshness, assess
from genesis.marketdata.store import BarStore

#: A budget denial this short is waited out, not failed over. IBKR's per-second
#: rules (six per contract per 2s, no identical request within 15s) deny
#: a 1m chart's seventh one-day chunk for a fraction of a second; failing over
#: threw the six already fetched away and drew yfinance, or nothing for a future.
#: The ten-minute rule's denials are longer and still fall down the chain.
SHORT_WAIT = timedelta(seconds=16)

__all__ = ["StoreBarSource", "quantize", "resolve_symbol", "to_bars"]

#: Below this, a chart is not worth drawing. Same threshold and same reasoning
#: as GatewayBarSource: twenty bars computes an ATR of sorts and nothing else,
#: and a chart of structure derived from a fortnight is worse than an honest
#: refusal.
MIN_BARS = 20


def quantize(ts: datetime, timeframe: str) -> datetime:
    """Floor a timestamp onto the timeframe's own grid.

    This exists because of a subtle failure the coverage table alone does not
    fix: every request window ends at ``now``, so a window recorded one second
    ago never covers the next call, and "never re-fetch" silently becomes
    "re-fetch every time".

    Snapping both ends onto the bar grid makes every call within one bar period
    ask the *same* question -- which is correct rather than merely convenient,
    because within one bar period no new bar can have closed. The vendor has
    nothing new to tell us, so not asking is not a shortcut.
    """
    tf = resolve(timeframe)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    minutes = int((ts - epoch).total_seconds() // 60)
    return epoch + timedelta(minutes=minutes - (minutes % tf.minutes))


def to_bars(rows: Sequence[Bar], *, symbol: str | None = None) -> Bars:
    """Canonical store rows -> the Charting Engine's :class:`Bars`.

    The one place ``Decimal`` becomes ``float``. Provenance survives the
    crossing: ``source``, ``tier`` and ``adjusted`` are carried onto ``Bars``,
    which is what lets a level computed from these say which tier it came from
    when it is eventually read aloud.

    Mixed provenance is reported honestly. A window assembled from two vendors
    takes the *worst* tier present, never the best -- a window that is 90%
    tier 1 and 10% tier 3 is a tier 3 window, because the weakest row is the
    one that could be wrong.
    """
    if not rows:
        raise DegradedError("no bars to convert")
    sources = {b.source for b in rows}
    return Bars(
        symbol=symbol or rows[0].symbol_id,
        timeframe=rows[0].timeframe,
        times=tuple(b.ts for b in rows),
        open=np.array([float(b.open) for b in rows]),
        high=np.array([float(b.high) for b in rows]),
        low=np.array([float(b.low) for b in rows]),
        close=np.array([float(b.close) for b in rows]),
        volume=np.array([float(b.volume) for b in rows]),
        source="+".join(sorted(sources)) if len(sources) > 1 else rows[0].source,
        tier=max(b.tier for b in rows),
        adjusted=all(b.adjusted for b in rows),
        resorted=False,
    )


def resolve_symbol(symbol: str, *, default_exchange: str = "XNAS") -> str:
    """What a person typed -> a canonical symbol id.

    ``genesis chart ES 1D`` has to mean something, and Open Questions §13 says
    plainly that bare ``ES`` is not an instrument -- it is a family. So this
    resolves the *unambiguous* cases and refuses the rest by name:

      ``FUT:CME:ES:2025-12``  already canonical, passed through
      ``ESZ5``               CME month code -> the dated contract
      ``AAPL``               an equity
      ``ES``                 REFUSED, with the two things it might mean

    Refusing the bare root is the design working rather than a rough edge. It
    is the same refusal the store makes, moved to the place where a person can
    actually act on it.
    """
    raw = symbol.strip().upper()
    if ":" in raw:
        parse_instrument_id(raw)  # validates, raises if malformed
        return raw

    from genesis.marketdata.normalize import MONTH_CODES, instrument_id

    # A CME month code: root + month letter + single-digit year, e.g. ESZ5.
    if len(raw) >= 3 and raw[-2] in MONTH_CODES and raw[-1].isdigit():
        root, code, year_digit = raw[:-2], raw[-2], raw[-1]
        # Single-digit years are ambiguous by decade. Resolve to the nearest
        # such year, which is right for every contract anyone trades and
        # wrong only for history more than five years out -- and that case
        # must be written as a full id anyway.
        this_year = datetime.now(UTC).year
        candidates = [
            y for y in range(this_year - 5, this_year + 6) if y % 10 == int(year_digit)
        ]
        year = min(candidates, key=lambda y: abs(y - this_year))
        return instrument_id(
            "FUT", "CME", root, contract_month=f"{year}-{MONTH_CODES[code]:02d}"
        )

    if raw in _FUTURES_ROOTS:
        # An example only -- the next quarterly month, so the hint is never a
        # contract that expired years ago. Not a resolution: still refused.
        now = datetime.now(UTC)
        q_month = (now.month - 1) // 3 * 3 + 6
        q_year = now.year + (q_month > 12)
        q_month = q_month - 12 if q_month > 12 else q_month
        code = {3: "H", 6: "M", 9: "U", 12: "Z"}[q_month]
        raise DegradedError(
            f"'{raw}' is a futures family, not an instrument. It could mean a "
            f"dated contract (try {raw}{code}{q_year % 10}, or "
            f"FUT:CME:{raw}:{q_year}-{q_month:02d}) or a "
            f"continuous series, which Genesis does not build yet -- "
            f"Open Questions §13. Say which.",
            spoken_summary=f"{raw} needs a contract month — which one?",
        )
    return instrument_id("EQ", default_exchange, raw)


#: Roots common enough that a bare one is far more likely a slip than a ticker.
#: Not exhaustive and does not need to be -- anything not listed resolves as an
#: equity, which is the right default and is visible in the resulting id.
_FUTURES_ROOTS = frozenset(
    {"ES", "NQ", "YM", "RTY", "CL", "GC", "SI", "ZB", "ZN", "ZC", "ZS", "NG", "HG"}
)


@dataclass
class StoreBarSource:
    """Bars from the store, filling from adapters on a miss.

    Satisfies :class:`~genesis.charting.source.BarSource`. Constructed with a
    store and an ordered adapter chain; the chain is Market Data Sources'
    per-consumer fallback list, and it is ordered by trust rather than by
    convenience -- first adapter that can answer wins, so the most trusted
    capable source is asked first.

    ``allow_fetch=False`` makes this store-only. Backtests use it, per Market
    Data Sources' chain table ("stored bars only"), and so does the test that
    proves a second run touches no network.
    """

    store: BarStore
    adapters: Sequence[Adapter] = ()
    budget: Budget | None = None
    #: Minimum trust tier a bar must have to satisfy a read. ``None`` accepts
    #: anything held.
    min_tier: int | None = None
    allow_fetch: bool = True
    #: Set by the most recent :meth:`fetch`, so a caller that is about to speak
    #: can say how old the answer is without asking a second question.
    last_freshness: Freshness | None = field(default=None, init=False)

    def fetch(self, symbol: str, timeframe: str, *, bars: int = 0) -> Bars:
        """The BarSource contract. Symbol may be canonical or human."""
        symbol_id = resolve_symbol(symbol)
        tf = resolve(timeframe)
        count = bars or tf.default_lookback_bars
        start = lookback_start(tf.label, count)
        end = datetime.now(UTC)

        rows = self.store.read(
            symbol_id, tf.label, start=start, limit=count, min_tier=self.min_tier
        )

        if self._needs_fill(symbol_id, tf.label, start, end, rows, count):
            self.fill(symbol_id, tf.label, start, end)
            rows = self.store.read(
                symbol_id, tf.label, start=start, limit=count, min_tier=self.min_tier
            )

        if len(rows) < MIN_BARS:
            raise DegradedError(
                f"{symbol_id} {tf.label}: only {len(rows)} bars available; "
                f"too short to compute structure",
                spoken_summary=f"I only have {len(rows)} bars for {symbol}.",
            )

        self.last_freshness = assess(
            rows[-1].ts,
            tf.label,
            source=rows[-1].source,
            tier=rows[-1].tier,
        )
        return to_bars(rows, symbol=symbol_id)

    # -- filling -----------------------------------------------------------

    def fill(
        self, symbol_id: str, timeframe: str, start: datetime, end: datetime
    ) -> dict[str, int]:
        """Fetch and store a window, walking the adapter chain in order.

        Every adapter that is asked records coverage, whether or not it
        returned anything -- that is what makes an empty answer permanent
        instead of a question we ask again every night.

        Failures accumulate rather than propagate one at a time: only when
        *every* adapter has failed does this raise, and the message names each
        one. A chain that reports "yfinance failed" while databento was never
        tried is how a fallback chain silently stops being one.
        """
        if not self.allow_fetch:
            raise DegradedError(
                f"{symbol_id} {timeframe}: not held, and this source is "
                f"store-only (allow_fetch=False)"
            )

        # Snap the fetch window to the bar grid, exactly as the coverage check
        # does. Two reasons, and the second was found by running it:
        #
        # 1. The request and the coverage record must describe the SAME window,
        #    or a window is recorded as covered under one key and re-asked
        #    under another.
        # 2. `end` is `now`, which sits partway through the forming bar. Asking
        #    a vendor for a bar period that has not closed is asking for a bar
        #    that does not exist -- Databento answers 422
        #    `data_end_after_available_end` and the whole chain fails, even
        #    though every bar we actually wanted was available.
        start = quantize(start, timeframe)
        end = quantize(end, timeframe)
        if end <= start:
            raise DegradedError(
                f"{symbol_id} {timeframe}: the requested window is shorter "
                f"than one bar period; nothing has closed yet"
            )

        instrument = parse_instrument_id(symbol_id)
        failures: list[str] = []
        totals = {"written": 0, "held": 0, "superseded": 0}

        for adapter in self.adapters:
            caps = adapter.capabilities()
            if timeframe not in caps.timeframes:
                failures.append(f"{caps.name}: no {timeframe} bars")
                continue
            if instrument.asset_class not in caps.asset_classes:
                failures.append(
                    f"{caps.name}: does not serve {instrument.asset_class}"
                )
                continue
            if caps.earliest and start < caps.earliest:
                failures.append(
                    f"{caps.name}: history begins {caps.earliest:%Y-%m-%d}"
                )
                continue
            if self.min_tier is not None and caps.tier > self.min_tier:
                failures.append(
                    f"{caps.name}: tier {caps.tier} below required {self.min_tier}"
                )
                continue

            if self.budget is not None:
                self.budget.register(caps.name, caps.pacing)

            try:
                got = self._fetch_from(adapter, caps, symbol_id, timeframe, start, end)
            except BudgetExceeded as exc:
                # Not a vendor failure -- a scheduling one. Say so precisely,
                # because "rate limited, retry in 4 minutes" and "this vendor
                # has no such data" call for completely different responses.
                failures.append(
                    f"{caps.name}: rate limited, retry in "
                    f"{exc.retry_after.total_seconds():.0f}s"
                )
                continue
            except GenesisError as exc:
                failures.append(f"{caps.name}: {exc.reason}")
                continue

            counts = self.store.write(got) if got else {}
            for k in totals:
                totals[k] += counts.get(k, 0)
            # `start` and `end` are already on the grid the check uses.
            self.store.record_coverage(
                symbol_id, timeframe, start, end,
                source=caps.name, tier=caps.tier, bar_count=len(got),
            )
            if got:
                return totals
            failures.append(f"{caps.name}: no data in window")

        raise DegradedError(
            f"{symbol_id} {timeframe}: no source could answer. "
            + "; ".join(failures or ["no adapters configured"]),
            spoken_summary=f"I couldn't get bars for {symbol_id}.",
        )

    def _fetch_from(
        self,
        adapter: Adapter,
        caps: object,
        symbol_id: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Bar]:
        """One adapter, chunked to its span limit, metered by the budget."""
        request = BarRequest(
            symbol_id=symbol_id, timeframe=timeframe, start=start, end=end
        )
        out: list[Bar] = []
        for piece in chunk_request(request, caps):  # type: ignore[arg-type]
            if self.budget is not None:
                # Atomic: two supervised workers must not both pass on the
                # last slot. See `Budget.try_consume`.
                decision = self.budget.try_consume(caps.name, piece)  # type: ignore[attr-defined]
                deadline = time.monotonic() + SHORT_WAIT.total_seconds()
                while not decision.allowed and decision.retry_after <= SHORT_WAIT \
                        and time.monotonic() < deadline:
                    time.sleep(decision.retry_after.total_seconds() + 0.05)
                    decision = self.budget.try_consume(caps.name, piece)  # type: ignore[attr-defined]
                decision.raise_if_denied()
            got = adapter.fetch(piece)
            out.extend(got)
        return out

    def _needs_fill(
        self,
        symbol_id: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        rows: Sequence[Bar],
        wanted: int,
    ) -> bool:
        """Is a network call actually necessary?

        Coverage first, and this ordering is the whole "zero network calls on
        the second run" property. Asking "do I have enough bars?" would re-fetch
        forever for a thinly traded contract that legitimately has fewer bars
        than requested; asking "have I already looked?" terminates.
        """
        if not self.allow_fetch:
            return False
        if self.store.covers(
            symbol_id, timeframe,
            quantize(start, timeframe), quantize(end, timeframe),
        ):
            return False
        if len(rows) >= wanted:
            # Held the full request even without a coverage record -- history
            # written by an earlier ingest, or a restore. No reason to ask.
            return False
        return True
