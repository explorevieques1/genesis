# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Free equity and index bars. No key, no signup, no futures.

The last clause is the important one and it is a refusal, not a gap.

yfinance *will* answer ``ES=F``. What it returns is a **continuous front-month
series** -- Yahoo's own roll convention, undocumented, unadjusted, and stitched
by rules nobody outside Yahoo can state. That is one of the four different
things Open Questions §13 warns are all spelled "ES", and it is the one that
looks most like the others. Writing it into the store beside a dated contract
would put two incompatible price series under keys that differ by nothing a
reader would notice.

So this adapter refuses ``FUT`` outright. It is a worse answer than a futures
bar and a much better one than a futures bar that is quietly a different
instrument -- and Conventions.md §Errors settles which of those we prefer:
*fail honestly, never confabulate*.

What it is genuinely good for: twenty years of daily equity and index bars,
free, keyless, adjusted, instantly. That covers research, backtests on
equities, and every chart of a stock -- which is most charts.

**Tier 3.** Free public data, per Market Data Sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Sequence

from genesis.errors import DegradedError, TransientError
from genesis.marketdata.interface import AdapterCapabilities, BarRequest, PacingRule
from genesis.marketdata.normalize import Bar, normalise_bars, parse_instrument_id

__all__ = ["INTERVALS", "YFinanceAdapter"]

#: Our timeframe -> yfinance interval. Their intraday history is short (60 days
#: for 1m, 730 for anything under an hour), which is expressed as `max_span` in
#: the capabilities rather than discovered as a truncated answer.
INTERVALS = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1H": "1h", "1D": "1d", "1W": "1wk", "1M": "1mo",
}


@dataclass
class YFinanceAdapter:
    """Equity and index bars from Yahoo. Tier 3, keyless, no futures."""

    tier: int = 3
    name: str = "yfinance"
    requests: int = field(default=0, init=False)

    @property
    def available(self) -> bool:
        try:
            import yfinance  # noqa: F401
        except ImportError:
            return False
        return True

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self.name,
            tier=self.tier,
            timeframes=frozenset(INTERVALS),
            # No FUT. See the module docstring -- this is the refusal, declared
            # as data so a caller can route around it without a failed request.
            asset_classes=frozenset({"EQ", "IDX"}),
            max_span={
                "1m": timedelta(days=7),
                "5m": timedelta(days=60),
                "15m": timedelta(days=60),
                "30m": timedelta(days=60),
                "1H": timedelta(days=730),
            },
            earliest=None,
            serves_expired_contracts=False,
            adjusted=True,
            supports_streaming=False,
            requires_session=False,
            pacing=(
                # Yahoo publishes no limit and enforces one anyway, by IP, with
                # no warning. Two per second is well under anything observed
                # and costs the overnight pass nothing.
                PacingRule(
                    name="burst", limit=2, window=timedelta(seconds=1),
                    key=lambda req: "*",
                ),
            ),
        )

    def fetch(self, request: BarRequest) -> Sequence[Bar]:
        instrument = parse_instrument_id(request.symbol_id)
        if instrument.is_future or instrument.is_continuous:
            raise DegradedError(
                f"{request.symbol_id}: yfinance cannot serve dated futures. "
                f"Its 'ES=F' is a continuous front-month series with an "
                f"undocumented roll, which is a different instrument -- see "
                f"Open Questions §13. Use databento for CME history."
            )
        interval = INTERVALS.get(request.timeframe)
        if interval is None:
            raise DegradedError(
                f"yfinance has no interval for {request.timeframe}"
            )

        try:
            import yfinance
        except ImportError as exc:
            raise DegradedError(
                "the `yfinance` package is not installed; "
                "`uv pip install yfinance`"
            ) from exc

        self.requests += 1
        try:
            frame = yfinance.Ticker(instrument.root).history(
                start=request.start,
                end=request.end,
                interval=interval,
                auto_adjust=True,
                raise_errors=True,
            )
        except Exception as exc:
            lowered = str(exc).lower()
            if "rate" in lowered or "too many" in lowered or "timeout" in lowered:
                raise TransientError(f"yfinance rate limited: {exc}") from exc
            raise DegradedError(
                f"yfinance failed for {instrument.root}: {exc}"
            ) from exc

        if frame.empty:
            return []

        rows = [
            {
                "ts": index,
                "open": row["Open"],
                "high": row["High"],
                "low": row["Low"],
                "close": row["Close"],
                "volume": row.get("Volume", 0),
            }
            for index, row in frame.iterrows()
        ]
        return normalise_bars(
            rows,
            symbol_id=request.symbol_id,
            timeframe=request.timeframe,
            source=self.name,
            tier=self.tier,
            # auto_adjust=True: these are split and dividend adjusted, and the
            # store records that, because an adjusted bar and a raw bar are not
            # interchangeable and the difference is invisible in the numbers.
            adjusted=True,
        )
