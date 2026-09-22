# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""What a vendor must satisfy to be a source of bars.

The Protocol here was written against the *hardest* vendor rather than the
easiest, deliberately. Databento, yfinance and a CSV file all fit almost any
interface you draw; IBKR does not, and an interface that fits only the easy
three has to be broken open the moment the broker arrives -- which is Phase 7,
which is the phase where breaking things open is most expensive.

So this was checked on paper against ``reqHistoricalData`` before it was
written. Four of its constraints do not fit a naive ``fetch(symbol, start,
end)`` and each one changed the shape below:

**1. IBKR asks for an end plus a duration, not a start plus an end.** So the
adapter, not the caller, owns turning a window into vendor arguments.
:class:`BarRequest` is expressed as ``(start, end)`` because that is what the
store can reason about; converting it to ``endDateTime`` + ``durationStr`` is
the IBKR adapter's job and nobody else's.

**2. Its window is capped per bar size, and the cap is not one number.** One
request may return 30 days of hourly bars or 1 day of one-minute bars. So
:class:`AdapterCapabilities` reports ``max_span`` *per timeframe*, and the
caller chunks. A single ``max_bars`` integer would have been wrong here, and
wrong quietly -- it would truncate rather than fail.

**3. Its pacing rules are three different shapes at once**, and none of them is
a simple rate:

  - no more than 60 requests in any 10 minutes  (a sliding window)
  - no *identical* request within 15 seconds     (a per-fingerprint cooldown)
  - no more than 6 requests for the same contract+exchange+tick type in 2s
    (a sliding window on a composite key)

That is why :attr:`AdapterCapabilities.pacing` is a list of rules with a
*key function*, not a requests-per-second number. See
:mod:`genesis.marketdata.budget`. A rate limiter that could only express
"N per second globally" would have forced the IBKR adapter to enforce its own
limits internally, which is precisely the thing Market Data Plane says must
live in one place.

**4. Expired futures fall off a cliff.** IBKR serves an expired contract only
within roughly two years of its expiry, and only when the contract is requested
with ``includeExpired``. That is not a rate limit or a bug, it is a hard edge in
what the vendor *has*, so it belongs in the capability report as
:attr:`earliest` / :attr:`serves_expired_contracts` and the store consults it
before asking. This single fact is why the plane needs Databento at all --
see Open Questions §6.

**Verdict: the constraints fit.** No pause was needed. The one thing the
Protocol deliberately does *not* express is ``keepUpToDate`` streaming, because
this session is closed bars only; :attr:`supports_streaming` is reported so the
gap is visible in data rather than implied by an adapter's absence, and the
streaming method is a separate Protocol that does not exist yet. Adding it
later widens the surface without reshaping this one, which is the test of
whether an interface was drawn in the right place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from genesis.marketdata.normalize import Bar

__all__ = [
    "Adapter",
    "AdapterCapabilities",
    "BarRequest",
    "PacingRule",
    "chunk_request",
]


@dataclass(frozen=True)
class PacingRule:
    """One vendor limit, in the only shape that covers all of IBKR's three.

    ``key`` turns a request into the bucket the rule counts against. A global
    rule returns a constant; IBKR's 6-per-contract-per-2s returns the contract.
    Making the key a function rather than an enum is what lets a vendor's own
    quirks be expressed without :mod:`genesis.marketdata.budget` learning about
    that vendor.

    ``min_interval`` covers the "no identical request within 15 seconds" shape,
    which is a cooldown rather than a count and would otherwise need its own
    mechanism.
    """

    name: str
    #: Maximum permitted events per ``window``. ``None`` for a pure cooldown.
    limit: int | None = None
    window: timedelta = timedelta(seconds=1)
    #: Minimum gap between two events on the same key. ``None`` for none.
    min_interval: timedelta | None = None
    #: Requests to a bucket key. Defaults to one global bucket.
    key: Callable[["BarRequest"], str] = lambda req: "*"
    #: Hard per-calendar-day ceiling, checked separately from the window.
    daily_quota: int | None = None


@dataclass(frozen=True)
class AdapterCapabilities:
    """What this vendor can actually do, as data the plane can reason about.

    Reported rather than assumed, because every field here is something that
    otherwise gets encoded as a comment in one place and a magic number in
    another. A caller that must ask "can this adapter give me 1-minute futures
    bars from 2019" should get a checkable answer, not a failed request.
    """

    name: str
    tier: int
    #: Timeframe labels from :mod:`genesis.charting.timeframes`.
    timeframes: frozenset[str]
    asset_classes: frozenset[str]
    #: Longest window one request may cover, per timeframe. Absent means
    #: unlimited. This is IBKR's per-bar-size duration cap.
    max_span: dict[str, timedelta] = field(default_factory=dict)
    #: Oldest data the vendor holds at all. ``None`` means no known floor.
    earliest: datetime | None = None
    #: For futures: does the vendor serve contracts that have already expired,
    #: and how far back? IBKR is roughly two years; Databento is the archive.
    serves_expired_contracts: bool = True
    expired_contract_horizon: timedelta | None = None
    pacing: tuple[PacingRule, ...] = ()
    #: True when bars come back split/dividend adjusted.
    adjusted: bool = False
    #: True when the adapter can stream. Nothing in this session uses it; it is
    #: reported so the absence of live data is a visible fact rather than an
    #: inference from which files exist.
    supports_streaming: bool = False
    #: True when the adapter needs something outside this process to be running
    #: and logged in -- a TWS session, a GUI. The 3am market-closed loop must
    #: be able to see this before it schedules against it.
    requires_session: bool = False


@dataclass(frozen=True)
class BarRequest:
    """A window of bars, in the terms the store thinks in.

    ``start`` and ``end`` are both UTC and the interval is half-open --
    ``start <= ts < end`` -- so two adjacent requests can be concatenated
    without a duplicate or a hole at the seam. Closed intervals are how the
    same bar ends up written twice with two different provenance stamps.
    """

    symbol_id: str
    timeframe: str
    start: datetime
    end: datetime
    #: Ask the vendor for split/dividend adjusted prices where it offers the
    #: choice. Recorded on every resulting bar either way.
    adjusted: bool = False
    #: Vendor-specific escape hatch (IBKR's ``whatToShow``, Databento's
    #: ``schema``). Never interpreted by the plane; passed through so a vendor
    #: quirk does not require widening this dataclass for everybody.
    vendor_options: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Identity of this exact request, for the identical-request cooldown."""
        return (
            f"{self.symbol_id}|{self.timeframe}|{self.start.isoformat()}"
            f"|{self.end.isoformat()}|{self.adjusted}"
        )

    def with_window(self, start: datetime, end: datetime) -> "BarRequest":
        return BarRequest(
            symbol_id=self.symbol_id,
            timeframe=self.timeframe,
            start=start,
            end=end,
            adjusted=self.adjusted,
            vendor_options=self.vendor_options,
        )


@runtime_checkable
class Adapter(Protocol):
    """Anything that can answer a :class:`BarRequest` with canonical bars.

    Two methods, and the asymmetry between them is the point: ``capabilities``
    is free and answers "could you", ``fetch`` costs quota and answers "here".
    Asking the first before spending the second is what keeps the budget layer
    from being the only thing standing between an agent and a vendor's patience.

    Every implementation is **afferent** in Biological Design's sense: read
    only, retryable, no approval, no model. There is deliberately no ``write``
    or ``submit`` anywhere in this Protocol, and there never will be -- an
    adapter that could place an order would put the execution path behind an
    interface designed for cheap parallel reads, which is exactly the
    undifferentiated tool list that note forbids.
    """

    def capabilities(self) -> AdapterCapabilities: ...

    def fetch(self, request: BarRequest) -> Sequence[Bar]: ...


def chunk_request(
    request: BarRequest, capabilities: AdapterCapabilities
) -> list[BarRequest]:
    """Split a window into pieces the vendor will actually serve.

    Returns ``[request]`` unchanged when the vendor has no cap for this
    timeframe, so the easy adapters pay nothing for IBKR's constraint existing.

    The chunks are walked forward from ``start`` rather than backward from
    ``end`` so that a partial failure leaves a contiguous prefix in the store
    rather than an island with a hole before it. A hole is worse than a short
    history: a short history is visibly short, and a hole reads as real data.
    """
    span = capabilities.max_span.get(request.timeframe)
    if span is None or request.end - request.start <= span:
        return [request]
    out: list[BarRequest] = []
    cursor = request.start
    while cursor < request.end:
        stop = min(cursor + span, request.end)
        out.append(request.with_window(cursor, stop))
        cursor = stop
    return out
