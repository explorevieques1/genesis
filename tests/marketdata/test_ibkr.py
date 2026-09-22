# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""The IBKR adapter, without an IBKR.

No gateway is contacted. The parts tested are the ones that are wrong or right
*before* a socket opens — duration conversion, contract qualification, the
expired-contract horizon, error classification, tier discipline, and the
closed-bar rule on the streaming path. Those are also the parts that a live
smoke test would not check carefully, because a live test tends to prove only
that something came back.

The fake IB implements the handful of methods the adapter actually calls, with
the real shapes: `BarData`-like rows, `qualifyContracts` returning a list, and
`reqHistoricalData` accepting IBKR's own argument names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from genesis.errors import DegradedError, FatalError, TransientError
from genesis.marketdata.adapters.ibkr import (
    BAR_SIZES,
    EXPIRED_HORIZON,
    IBKR_PACING,
    IbkrAdapter,
    IbkrConnection,
    MAX_SPANS,
    _duration_str,
    _row,
)
from genesis.marketdata.interface import Adapter, BarRequest, chunk_request

pytest.importorskip("ib_async")


def _front_month() -> str:
    """A contract comfortably inside IBKR's expired horizon."""
    soon = datetime.now(UTC) + timedelta(days=60)
    return f"FUT:CME:ES:{soon.year}-{soon.month:02d}"


ES = _front_month()


@dataclass
class FakeBar:
    date: Any
    open: float
    high: float
    low: float
    close: float
    volume: float
    average: float = 0.0
    barCount: int = 0


class FakeEvent(list):
    """ib_async's ``Event``: ``+=`` a handler, ``emit`` to call them all."""

    def __iadd__(self, handler):
        self.append(handler)
        return self

    def emit(self, *args) -> None:
        for handler in self:
            handler(*args)


class FakeIB:
    """The five methods the adapter calls, with the real shapes."""

    def __init__(self, bars: list[FakeBar] | None = None, raises: Exception | None = None):
        self.bars = bars if bars is not None else _default_bars()
        self.raises = raises
        self.calls: list[dict[str, Any]] = []
        self.qualified: list[Any] = []
        self.market_data_type: int | None = None
        self._connected = True
        self.errorEvent = FakeEvent()

    def isConnected(self) -> bool:  # noqa: N802
        return self._connected

    def connect(self, *a, **k) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def reqMarketDataType(self, code: int) -> None:  # noqa: N802
        self.market_data_type = code

    def qualifyContracts(self, *contracts):  # noqa: N802
        self.qualified.extend(contracts)
        return list(contracts)

    def reqHistoricalData(self, contract, **kwargs):  # noqa: N802
        if self.raises:
            raise self.raises
        self.calls.append({"contract": contract, **kwargs})
        return list(self.bars)

    def sleep(self, _seconds: float) -> None:
        return None


def _default_bars() -> list[FakeBar]:
    base = datetime(2026, 9, 3, 13, 0, tzinfo=UTC)
    return [
        FakeBar(base + timedelta(hours=i), 4500.0 + i, 4510.25 + i,
                4495.5 + i, 4505.75 + i, 1000 + i)
        for i in range(6)
    ]


def adapter_with(ib: FakeIB, **kw) -> IbkrAdapter:
    connection = IbkrConnection(use_watchdog=False, **kw)
    connection._ib = ib
    return IbkrAdapter(connection=connection)


def request(symbol: str = ES, tf: str = "1H", days: int = 2) -> BarRequest:
    end = datetime.now(UTC)
    return BarRequest(symbol, tf, end - timedelta(days=days), end)


# -- the Protocol ----------------------------------------------------------


def test_the_adapter_satisfies_the_protocol():
    """The point of the whole session: IBKR fits the interface unchanged."""
    assert isinstance(IbkrAdapter(), Adapter)


def test_it_arrives_at_tier_3_not_tier_1():
    """Promotion is a decision made on reconciliation evidence, in config.
    A default of tier 1 would make it an accident."""
    assert IbkrAdapter().capabilities().tier == 3


def test_it_declares_that_it_needs_a_session():
    """The 3am market-closed loop must be able to see this before scheduling
    against it."""
    assert IbkrAdapter().capabilities().requires_session is True


# -- constraint 1: end + duration ------------------------------------------


def test_duration_rounds_up_never_down():
    """A short answer is indistinguishable from a thin market, so err long --
    the extra bars are trimmed downstream and cost nothing."""
    end = datetime(2026, 9, 4, tzinfo=UTC)
    assert _duration_str(end - timedelta(hours=2), end) == "7201 S"
    assert _duration_str(end - timedelta(days=3), end) == "4 D"
    assert _duration_str(end - timedelta(days=800), end).endswith(" Y")


def test_a_one_day_window_never_exceeds_ibkrs_seconds_limit():
    """Found against a real gateway: "86401 S" is rejected with error 321,
    silently, and the 1m backfill and the live stream both ask for one day."""
    end = datetime(2026, 9, 4, tzinfo=UTC)
    assert _duration_str(end - timedelta(days=1), end) == "86400 S"
    assert _duration_str(end - timedelta(seconds=86_399.5), end) == "86400 S"


def test_a_zero_width_window_still_asks_for_something():
    end = datetime(2026, 9, 4, tzinfo=UTC)
    assert _duration_str(end, end) == "31 S"


# -- constraint 2: per-bar-size caps ---------------------------------------


def test_every_timeframe_has_both_a_bar_size_and_a_span_cap():
    """A timeframe present in one table and missing from the other would
    chunk wrongly or not at all."""
    assert set(BAR_SIZES) == set(MAX_SPANS)


def test_a_long_minute_window_is_chunked():
    caps = IbkrAdapter().capabilities()
    pieces = chunk_request(request(tf="1m", days=10), caps)
    assert len(pieces) >= 10
    for a, b in zip(pieces, pieces[1:]):
        assert a.end == b.start


# -- constraint 3: pacing --------------------------------------------------


def test_the_three_pacing_rules_are_all_declared():
    names = {r.name for r in IbkrAdapter().capabilities().pacing}
    assert names == {
        "sixty-per-ten-minutes",
        "no-identical-within-15s",
        "six-per-contract-per-2s",
    }


def test_the_pacing_rules_key_on_three_different_things():
    """The reason PacingRule takes a key function rather than a rate: no two
    of IBKR's three rules count the same bucket."""
    a, b = request(days=2), request(days=5)
    by_name = {r.name: r for r in IBKR_PACING}
    assert by_name["sixty-per-ten-minutes"].key(a) == by_name[
        "sixty-per-ten-minutes"
    ].key(b)
    assert by_name["six-per-contract-per-2s"].key(a) == by_name[
        "six-per-contract-per-2s"
    ].key(b)
    assert by_name["no-identical-within-15s"].key(a) != by_name[
        "no-identical-within-15s"
    ].key(b)


# -- constraint 4: the expired horizon -------------------------------------


def test_a_long_expired_contract_is_refused_before_a_request_is_spent():
    """It costs one of sixty requests per ten minutes to learn nothing."""
    ib = FakeIB()
    old = "FUT:CME:ES:2019-12"
    with pytest.raises(DegradedError, match="databento"):
        adapter_with(ib).fetch(request(old))
    assert ib.calls == []


def test_the_horizon_is_declared_as_data():
    caps = IbkrAdapter().capabilities()
    assert caps.serves_expired_contracts
    assert caps.expired_contract_horizon == EXPIRED_HORIZON


# -- contracts -------------------------------------------------------------


def test_a_dated_contract_maps_to_a_qualified_ibkr_future():
    """Where §13 pays off: the canonical id carries the full year, so this
    mapping is total rather than a guess about the front month."""
    ib = FakeIB()
    adapter_with(ib).fetch(request())

    (contract,) = ib.qualified
    assert contract.symbol == "ES"
    assert contract.exchange == "CME"
    assert contract.lastTradeDateOrContractMonth == ES.split(":")[-1].replace("-", "")
    assert contract.includeExpired is True


def test_an_equity_routes_through_smart():
    ib = FakeIB()
    adapter_with(ib).fetch(request("EQ:XNAS:AAPL"))
    (contract,) = ib.qualified
    assert contract.exchange == "SMART"


def test_an_unresolvable_contract_degrades_with_the_horizon_explained():
    class NoQualify(FakeIB):
        def qualifyContracts(self, *contracts):  # noqa: N802
            return []

    with pytest.raises(DegradedError, match="expired"):
        adapter_with(NoQualify()).fetch(request())


def test_continuous_contracts_are_refused():
    with pytest.raises(DegradedError, match="§13"):
        adapter_with(FakeIB()).fetch(request("CONT:CME:ES:volume:back"))


# -- request shape ---------------------------------------------------------


def test_requests_use_utc_epoch_dates_and_extended_hours():
    """formatDate=2 is the only unambiguous option -- 1 formats in the
    account's timezone, making a bar's calendar day depend on a GUI setting.
    useRTH=False because ES trades nearly 24x5 and RTH-only silently drops
    the overnight session."""
    ib = FakeIB()
    adapter_with(ib).fetch(request())
    (call,) = ib.calls
    assert call["formatDate"] == 2
    assert call["useRTH"] is False
    assert call["keepUpToDate"] is False
    assert call["barSizeSetting"] == "1 hour"
    assert call["whatToShow"] == "TRADES"


def test_vendor_options_override_per_request():
    ib = FakeIB()
    req = BarRequest(
        ES, "1H",
        datetime.now(UTC) - timedelta(days=1), datetime.now(UTC),
        vendor_options={"whatToShow": "MIDPOINT", "useRTH": True},
    )
    adapter_with(ib).fetch(req)
    (call,) = ib.calls
    assert call["whatToShow"] == "MIDPOINT"
    assert call["useRTH"] is True


def test_the_market_data_type_is_applied_on_connect():
    """Delayed is free and needs no subscription, which is why it is the
    default and why every line of this adapter is exercisable today."""
    connection = IbkrConnection(use_watchdog=False, market_data_type="delayed")
    ib = FakeIB()
    connection._make_ib = lambda: ib  # type: ignore[method-assign]
    connection.connect()
    assert ib.market_data_type == 3


def test_an_unknown_market_data_type_is_fatal():
    connection = IbkrConnection(use_watchdog=False, market_data_type="realish")
    connection._make_ib = lambda: FakeIB()  # type: ignore[method-assign]
    with pytest.raises(FatalError, match="market_data_type"):
        connection.connect()


# -- results ---------------------------------------------------------------


def test_bars_come_back_canonical_with_provenance():
    bars = adapter_with(FakeIB()).fetch(request())
    assert len(bars) == 6
    assert all(b.source == "ibkr" and b.tier == 3 for b in bars)
    assert all(isinstance(b.close, Decimal) for b in bars)
    assert all(b.ts.tzinfo is not None for b in bars)
    assert bars == sorted(bars, key=lambda b: b.ts)


def test_an_empty_answer_is_a_fact_not_an_error():
    assert adapter_with(FakeIB(bars=[])).fetch(request()) == []


def test_a_daily_bars_plain_date_becomes_a_utc_midnight():
    """Daily bars come back as a `date`, not a datetime. Left naive it would
    be a bar in an unknown session."""
    row = _row(FakeBar(date(2026, 9, 3), 1, 2, 0.5, 1.5, 100))
    assert row["ts"] == datetime(2026, 9, 3, tzinfo=UTC)


def test_negative_volume_becomes_zero_not_a_negative():
    """IBKR reports -1 for 'no volume data'. That is not zero volume, and a
    negative would corrupt every volume-weighted calculation downstream."""
    assert _row(FakeBar(datetime(2026, 9, 3, tzinfo=UTC), 1, 2, 0.5, 1.5, -1))[
        "volume"
    ] == 0


# -- errors ----------------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("pacing violation", TransientError),
        ("Historical Market Data Service error: no subscription", FatalError),
        ("Not connected", TransientError),
        ("Request timeout", TransientError),
        ("No security definition has been found", DegradedError),
        ("something else entirely", DegradedError),
    ],
)
def test_errors_are_classified_by_what_they_require(message, expected):
    """A pacing violation self-heals, a missing subscription needs a human
    with a credit card, and 'no data' should fall down the chain. Collapsing
    them into one class turns a bad subscription into a retry loop."""
    with pytest.raises(expected):
        adapter_with(FakeIB(raises=RuntimeError(message))).fetch(request())


def test_a_missing_gateway_is_transient_not_fatal():
    connection = IbkrConnection(port=1, use_watchdog=False)

    class Refusing(FakeIB):
        def connect(self, *a, **k):
            raise ConnectionRefusedError(111, "refused")

    connection._make_ib = lambda: Refusing()  # type: ignore[method-assign]
    with pytest.raises(TransientError, match="docker compose"):
        connection.connect()


# -- streaming -------------------------------------------------------------


class FakeSubscription(list):
    """A BarDataList stand-in: a list with an updateEvent."""

    def __init__(self, bars):
        super().__init__(bars)
        self.handlers: list[Any] = []
        self.updateEvent = self  # so `+=` lands on __iadd__

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def push(self, bar, *, has_new_bar=True):
        self.append(bar)
        for handler in self.handlers:
            handler(self, has_new_bar)


def test_streaming_never_emits_the_forming_bar():
    """The last element with keepUpToDate is the FORMING bar and it changes on
    every tick. Writing it would violate the store's central promise -- closed
    bars are immutable -- and poison backtests with a bar that never printed
    that way."""
    bars = _default_bars()
    subscription = FakeSubscription(bars)

    class StreamingIB(FakeIB):
        def reqHistoricalData(self, contract, **kwargs):  # noqa: N802
            assert kwargs["keepUpToDate"] is True
            assert kwargs["endDateTime"] == ""
            return subscription

    seen = []
    adapter_with(StreamingIB()).stream_bars(
        ES, "1H", on_bar=seen.append
    )

    # Nothing yet: five closed, one forming, and we started knowing that.
    assert seen == []

    # A new bar appears -> the previously-forming one has now closed.
    subscription.push(
        FakeBar(datetime(2026, 9, 3, 19, tzinfo=UTC), 1, 2, 0.5, 1.5, 10)
    )
    assert len(seen) == 1
    assert seen[0].ts == bars[-1].date


def test_streaming_trusts_the_length_not_the_new_bar_flag():
    """`has_new_bar` is advisory. A missed flag would mean a permanently
    skipped bar, so the count is the source of truth."""
    subscription = FakeSubscription(_default_bars())
    seen = []

    class StreamingIB(FakeIB):
        def reqHistoricalData(self, contract, **kwargs):  # noqa: N802
            return subscription

    adapter_with(StreamingIB()).stream_bars(ES, "1H", on_bar=seen.append)
    subscription.push(
        FakeBar(datetime(2026, 9, 3, 19, tzinfo=UTC), 1, 2, 0.5, 1.5, 10),
        has_new_bar=False,
    )
    assert len(seen) == 1


def test_streaming_catches_up_if_several_bars_arrive_at_once():
    subscription = FakeSubscription(_default_bars())
    seen = []

    class StreamingIB(FakeIB):
        def reqHistoricalData(self, contract, **kwargs):  # noqa: N802
            return subscription

    adapter_with(StreamingIB()).stream_bars(ES, "1H", on_bar=seen.append)
    for i in range(3):
        subscription.append(
            FakeBar(datetime(2026, 9, 3, 19 + i, tzinfo=UTC), 1, 2, 0.5, 1.5, 10)
        )
    for handler in subscription.handlers:
        handler(subscription, True)
    assert len(seen) == 3


def test_gateway_cut_off_from_ibkr_fails_fast_and_recovers():
    """Socket up, farms down: refuse instead of hanging in qualifyContracts."""

    class CutOff(FakeIB):
        def connect(self, *a, **k):
            super().connect()
            self.errorEvent.emit(-1, 2110, "Connectivity between Trader Workstation and server is broken.", None)
            self.errorEvent.emit(-1, 2105, "HMDS data farm connection is broken:ushmds", None)

    ib = CutOff()
    ib._connected = False
    connection = IbkrConnection(use_watchdog=False)
    connection._make_ib = lambda: ib  # type: ignore[method-assign]
    adapter = IbkrAdapter(connection=connection)
    with pytest.raises(TransientError, match="cut off"):
        adapter.fetch(request())
    assert ib.qualified == []
    ib.errorEvent.emit(-1, 2106, "HMDS data farm connection is OK:ushmds", None)
    ib.errorEvent.emit(-1, 1102, "Connectivity restored - data maintained.", None)
    assert adapter.fetch(request())
