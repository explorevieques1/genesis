# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Where bars come from, for code that draws them.

The obvious design is wrong, and it is worth being explicit about why, because
it is the design a reasonable person reaches for first: *"the charting tools
take bars as an argument."*

They cannot. A markup tool is reached by a language model, and a model can only
pass an argument it has written -- so ``compute_levels(bars=[...200 rows...])``
means two hundred bars going *out* through the model's context, one token at a
time, before any level is computed. That is the exact failure Orchestrator
Tools.md forbids in one line: **the orchestrator moves ids and summaries, never
rows.**

So the tool surface takes a *symbol and a timeframe*, and the bars are fetched
on this side of the model by deterministic Python. The fetch is an **afferent**
path in Biological Design's sense -- cheap, safe, retryable, read-only -- so it
needs no approval and no model in the loop. :class:`GatewayBarSource` calls the
[[MCP Gateway]] directly for that, which keeps the allow-list, the SSRF guard,
the cache and the rate limit all in force: the gateway does not care whether its
caller is a model or a function, and that is what makes bypassing the model safe
rather than a hole.

When [[Market Data Plane]]'s store lands, ``GatewayBarSource`` is the thing it
replaces, and nothing above this interface changes -- which is the point of the
interface existing before the store does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from genesis.charting.bars import Bars, BarParseError, parse_bars
from genesis.charting.timeframes import resolve
from genesis.errors import DegradedError, TransientError

__all__ = ["BarSource", "GatewayBarSource", "StaticBarSource", "lookback_start"]

#: Trust tier of what comes back. Everything free is tier 3 (Market Data
#: Sources), and the tier travels with the bars into the spec so an answer read
#: aloud can name its source and age.
DEFAULT_TIER = 3


class BarSource(Protocol):
    """Anything that can produce bars for a symbol and timeframe."""

    def fetch(self, symbol: str, timeframe: str, *, bars: int = 0) -> Bars: ...


def lookback_start(timeframe: str, bars: int, *, end: datetime | None = None) -> datetime:
    """How far back to ask for ``bars`` bars on this timeframe.

    Inflated by 40% plus a week, because calendar days are not session days: 252
    trading days is 366 calendar days, and asking for exactly the bar count
    returns a window a third too short. Over-fetching is free -- the extra bars
    are trimmed locally -- and under-fetching silently truncates the very
    history the levels are computed from.
    """
    tf = resolve(timeframe)
    minutes = tf.minutes * max(bars, 1) * 1.4
    return (end or datetime.now(UTC)) - timedelta(minutes=minutes, days=7)


@dataclass
class GatewayBarSource:
    """Bars via the MCP gateway's ``market-data.ohlcv``.

    ``agent`` is the identity the allow-list is checked against, so a charting
    agent gets exactly the grant its declaration names and nothing more. Passing
    the caller's own id rather than a shared "charting" identity is what keeps
    the per-agent allow-list meaningful.
    """

    gateway: Any
    agent: str = "chart-markup"
    capability: str = "market-data.ohlcv"
    tier: int = DEFAULT_TIER
    #: Argument names differ per vendor. Overridable so swapping the owner of
    #: ``market-data.ohlcv`` is a config change, not a code change.
    arg_names: dict[str, str] = field(
        default_factory=lambda: {
            "symbol": "symbol",
            "period": "period",
            "interval": "interval",
            "start": "start_date",
            "end": "end_date",
        }
    )

    def fetch(self, symbol: str, timeframe: str, *, bars: int = 0) -> Bars:
        tf = resolve(timeframe)
        count = bars or tf.default_lookback_bars
        start = lookback_start(tf.label, count)
        arguments = {
            self.arg_names["symbol"]: symbol.upper(),
            self.arg_names["interval"]: _vendor_interval(tf.label),
            self.arg_names["start"]: start.date().isoformat(),
            self.arg_names["end"]: datetime.now(UTC).date().isoformat(),
        }
        result = self.gateway.call(self.agent, self.capability, arguments)
        content = getattr(result, "content", result)
        try:
            frame = parse_bars(
                content,
                symbol=symbol,
                timeframe=tf.label,
                source=getattr(result, "server", self.capability),
                tier=self.tier,
            )
        except BarParseError:
            raise
        if len(frame) < 20:
            # Twenty bars computes an ATR of sorts and nothing else worth
            # drawing. Better a typed failure the agent reports than a chart of
            # levels derived from a fortnight.
            raise DegradedError(
                f"{symbol} {tf.label}: only {len(frame)} bars returned; "
                f"too short to compute structure",
                spoken_summary=f"I only got {len(frame)} bars for {symbol}.",
            )
        return frame.tail(count)


@dataclass
class StaticBarSource:
    """Bars from a dict. For tests, backfills, and re-rendering a stored spec."""

    frames: dict[tuple[str, str], Bars]

    def fetch(self, symbol: str, timeframe: str, *, bars: int = 0) -> Bars:
        key = (symbol.upper(), resolve(timeframe).label)
        frame = self.frames.get(key)
        if frame is None:
            raise DegradedError(f"no bars held for {key[0]} {key[1]}")
        return frame.tail(bars) if bars else frame


def _vendor_interval(label: str) -> str:
    """Our timeframe label in the spelling the free vendors use.

    yfinance and its wrappers want ``1d``/``1wk``/``1mo``/``60m``. One mapping,
    here, rather than in each agent -- a per-agent mapping is how one agent ends
    up silently asking for daily bars when it wanted hourly.
    """
    return {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1H": "60m", "4H": "60m", "1D": "1d", "1W": "1wk", "1M": "1mo",
    }[label]
