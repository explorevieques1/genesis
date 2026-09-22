# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""CME futures history, from the archive. Historical only, by decision.

Open Questions §6 (2026-09-04) buys Databento for **history and nothing else**,
on free signup credits, and the reason is a hard limit in the live vendor rather
than a preference: IBKR drops expired futures contracts more than roughly two
years past expiry, and paces its historical endpoint at 60 requests per ten
minutes. Neither of those can be worked around, and both are fatal to a
backtest that wants ten years of ES. Databento has the full GLBX.MDP3 archive
with no pacing wall.

That split -- **Databento for history, the broker for live** -- is the single
constraint this whole package is shaped around. It is why there is an adapter
layer at all: one vendor answers "what happened in 2019" and a different one
answers "what is happening now", and no single interface would have been drawn
if one vendor could do both.

**Decimal from the vendor, not from a float.** ``to_df(price_type="decimal")``
returns ``Decimal`` objects directly, so a CME quarter-point never passes
through binary floating point on its way to the store. Databento's wire format
is fixed-point integers, which means this path is exact end to end -- the only
adapter here of which that is true.

**Costs money, so it is metered.** The free credits are finite and the budget
rules below are conservative on purpose: a runaway backfill loop that burns the
credits in an afternoon is a real failure mode, and the daily quota exists to
make it a refusal rather than an invoice.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from genesis.errors import DegradedError, FatalError, TransientError
from genesis.marketdata.interface import AdapterCapabilities, BarRequest, PacingRule
from genesis.marketdata.normalize import Bar, normalise_bars, parse_instrument_id

__all__ = ["DATASETS", "DatabentoAdapter", "SCHEMAS"]

log = logging.getLogger(__name__)

#: Our timeframe label -> Databento schema. Only the four they publish; a
#: timeframe absent here is genuinely unavailable and must fail rather than be
#: resampled behind the caller's back. Resampling 1h into 4h is fine and is the
#: store's job -- doing it silently *inside* an adapter is how a "4H bar from
#: Databento" turns out to be nothing of the sort.
SCHEMAS = {
    "1m": "ohlcv-1m",
    "1H": "ohlcv-1h",
    "1D": "ohlcv-1d",
}

#: Exchange -> Databento dataset. CME's is GLBX.MDP3, which covers CME, CBOT,
#: NYMEX and COMEX -- all four of the exchanges a futures trader means when
#: they say "CME".
DATASETS = {
    "CME": "GLBX.MDP3",
    "CBOT": "GLBX.MDP3",
    "NYMEX": "GLBX.MDP3",
    "COMEX": "GLBX.MDP3",
    "XNAS": "XNAS.ITCH",
}


@dataclass
class DatabentoAdapter:
    """Historical CME bars. Tier 3.

    Tier 3 rather than tier 1 deserves a note, because the data is excellent:
    it is the exchange's own MDP3 feed, and it is more accurate than anything
    else in this package. But Market Data Sources defines tier 1 as **execution
    truth** -- the broker's own feed and account state -- and that is a
    statement about *which* feed the risk engine may read, not about quality. A
    perfect historical bar is still not the number a fill will happen at. The
    tiers rank authority, not accuracy, and conflating those two is how a
    backtest price ends up sizing a live position.
    """

    api_key: str | None = None
    tier: int = 3
    name: str = "databento"
    #: Free credits are finite. Refuse rather than spend when unsure.
    daily_request_quota: int = 200
    requests: int = field(default=0, init=False)
    _client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("DATABENTO_API_KEY")

    @property
    def available(self) -> bool:
        """Is this adapter usable at all? Cheap, and never raises.

        Callers check this to decide whether to fall back, so it must not be
        the kind of question that costs a request to answer.
        """
        return bool(self.api_key)

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self.name,
            tier=self.tier,
            timeframes=frozenset(SCHEMAS),
            asset_classes=frozenset({"FUT", "EQ"}),
            # No per-request span cap: their range endpoint streams a whole
            # window. The practical limit is credits, which is a quota rather
            # than a span, and quotas live in `pacing`.
            max_span={},
            # GLBX.MDP3 begins in 2010. Stated so a caller asking for 2005 is
            # told no rather than handed a short answer it reads as complete.
            earliest=datetime(2010, 6, 6, tzinfo=UTC),
            serves_expired_contracts=True,
            expired_contract_horizon=None,  # the archive: no horizon
            adjusted=False,  # futures are never split-adjusted
            supports_streaming=False,  # true of them, not of this adapter
            requires_session=False,
            pacing=(
                PacingRule(
                    name="daily-requests",
                    daily_quota=self.daily_request_quota,
                    key=lambda req: "*",
                ),
                # Politeness rather than a published limit. A backfill loop
                # with no gap is indistinguishable from a runaway, and the
                # overnight pass has hours of slack to spend on being polite.
                PacingRule(
                    name="burst",
                    limit=10,
                    window=timedelta(seconds=1),
                    key=lambda req: "*",
                ),
            ),
        )

    def fetch(self, request: BarRequest) -> Sequence[Bar]:
        if not self.available:
            raise DegradedError(
                "DATABENTO_API_KEY is not set; the Databento adapter is "
                "unavailable. Add it to ~/.genesis/.env (see .env.example)."
            )
        schema = SCHEMAS.get(request.timeframe)
        if schema is None:
            raise DegradedError(
                f"databento publishes {sorted(SCHEMAS)}, not "
                f"{request.timeframe}. Resample from a finer bar rather than "
                f"asking for one that does not exist."
            )

        instrument = parse_instrument_id(request.symbol_id)
        dataset = DATASETS.get(instrument.exchange)
        if dataset is None:
            raise DegradedError(
                f"no databento dataset mapped for exchange "
                f"{instrument.exchange!r}"
            )
        vendor_symbol = self._vendor_symbol(instrument)

        client = self._ensure_client()
        end = request.end
        data = None
        for attempt in (1, 2):
            self.requests += 1
            try:
                data = client.timeseries.get_range(
                    dataset=dataset,
                    symbols=[vendor_symbol],
                    schema=schema,
                    start=request.start,
                    end=end,
                    stype_in="raw_symbol",
                )
                break
            except Exception as exc:
                # The recent-data embargo, and the one place a retry is
                # genuinely better than a failure.
                #
                # Free credits do not cover the most recent ~24h of GLBX.MDP3 --
                # that window needs a CME licence. The boundary moves every
                # day, so hardcoding it would be wrong within hours. But the
                # vendor's own error names the exact cutoff ("Try again with an
                # end time before ..."), so the honest move is to believe it
                # and retry once with what it asked for.
                #
                # Only once, and only when a bound was actually parsed: a retry
                # loop against a vendor that keeps refusing is how free credits
                # become an invoice.
                bound = self._licensed_end(exc) if attempt == 1 else None
                if bound is None or bound <= request.start:
                    raise self._classify(exc, vendor_symbol) from exc
                log.info(
                    "databento: %s is beyond the licensed range; retrying to %s",
                    end, bound,
                )
                end = bound

        frame = data.to_df(price_type="decimal", pretty_ts=True, tz="UTC")
        if frame.empty:
            # Not an error. An empty window is a fact -- a holiday, a contract
            # not yet listed -- and the store records it as coverage so we
            # never ask again.
            return []

        rows = [
            {
                "ts": index,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row.get("volume", 0),
            }
            for index, row in frame.iterrows()
        ]
        return normalise_bars(
            rows,
            symbol_id=request.symbol_id,
            timeframe=request.timeframe,
            source=self.name,
            tier=self.tier,
            adjusted=False,
        )

    # -- internals ---------------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                import databento
            except ImportError as exc:
                raise DegradedError(
                    "the `databento` package is not installed; "
                    "`uv pip install databento`"
                ) from exc
            self._client = databento.Historical(key=self.api_key)
        return self._client

    @staticmethod
    def _vendor_symbol(instrument: Any) -> str:
        """``FUT:CME:ES:2025-12`` -> ``ESZ5``, CME's own spelling.

        Databento's ``raw_symbol`` for a CME future is the exchange's
        single-digit-year code. Note this is genuinely ambiguous across decades
        -- ``ESZ5`` is 2025 here and was 2015 then -- which is precisely why our
        canonical id carries the full year and this lossy form appears only at
        the vendor boundary, converted per request from a window that already
        knows the decade.
        """
        if instrument.is_future:
            code = instrument.month_code
            if not code:
                raise DegradedError(
                    f"{instrument.symbol_id}: no contract month to build a "
                    f"databento symbol from"
                )
            return f"{instrument.root}{code}"
        return instrument.root

    @staticmethod
    def _licensed_end(exc: Exception) -> datetime | None:
        """The cutoff Databento suggests, parsed out of its own 422.

        Returns ``None`` for any error that is not the embargo, so an
        unrelated failure never turns into a silently narrowed request.
        """
        text = str(exc)
        if "dataset_unavailable_range" not in text and "available_end" not in text:
            return None
        match = re.search(
            r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z?", text
        )
        if not match:
            return None
        try:
            stamp = datetime.fromisoformat(match.group(1).replace(" ", "T"))
        except ValueError:
            return None
        stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
        # A second inside the boundary: the vendor said "before", not "at".
        return stamp - timedelta(seconds=1)

    @staticmethod
    def _classify(exc: Exception, symbol: str) -> Exception:
        """Vendor exception -> one of ours, per Conventions.md §Errors.

        The distinction that matters: a 401 is fatal (the key is wrong and
        retrying spends nothing but time), a 429 or a timeout is transient
        (wait and it works), and a 404 is degraded (this contract has no data;
        fall down the chain). Collapsing these into one class is how a bad key
        becomes a retry loop.
        """
        text = str(exc)
        lowered = text.lower()
        if "401" in text or "authentication" in lowered or "api key" in lowered:
            return FatalError(
                f"databento rejected the API key: {text}. "
                f"Check DATABENTO_API_KEY in ~/.genesis/.env."
            )
        if "402" in text or "credit" in lowered or "insufficient" in lowered:
            return FatalError(
                f"databento credits exhausted: {text}. "
                f"Historical backfill is paused until this is resolved; "
                f"the store still answers from held history."
            )
        if "429" in text or "rate" in lowered or "timeout" in lowered:
            return TransientError(f"databento rate limited or timed out: {text}")
        if "404" in text or "not found" in lowered or "no data" in lowered:
            return DegradedError(f"databento has no data for {symbol}: {text}")
        return DegradedError(f"databento request failed for {symbol}: {text}")
