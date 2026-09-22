# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Interactive Brokers. The tier-1 feed — once it has earned the label.

Open Questions §1 (2026-09-04) makes IBKR the broker and CME futures the asset
class, for one reason: **data and execution arrive over one connection**, so the
chart, the signal and the fill cannot disagree with each other.

This is the file the rest of the plane was shaped for. Nothing above
:class:`~genesis.marketdata.interface.Adapter` changed to accommodate it, which
was the whole test of whether the Protocol was drawn in the right place. Four
IBKR constraints that would break a naive interface are handled here and are
invisible to every caller:

**1. End plus duration, not start plus end.** IBKR asks "how far back from
when", the store thinks in windows. :func:`_duration_str` converts, and the
caller never learns that it happened.

**2. Per-bar-size window caps.** One request may cover a year of daily bars or
one day of minute bars. Declared in :attr:`MAX_SPANS` and applied by the
Protocol's own ``chunk_request``, which existed before this adapter did.

**3. Three simultaneous pacing rules**, in three different shapes — a sliding
window, a per-fingerprint cooldown, and a sliding window on a composite key.
Declared in :meth:`capabilities` and enforced by
:mod:`genesis.marketdata.budget`, which has never heard of IBKR. These rules
were expressible, and tested, before this file existed.

**4. Expired contracts fall off a cliff** at roughly two years past expiry, and
need ``includeExpired``. Declared as :attr:`AdapterCapabilities.earliest`-style
data so the chain routes around it rather than discovering it as a short
answer. This limit is the entire reason Databento is bought (§6).

## It arrives at tier 3, deliberately

Not tier 1. Tier 1 is what [[Pre-Trade Risk Engine]] reads in Phase 7 and
nothing else, and promoting a source because it connected successfully is
exactly the drift between believed and actual state that *proprioception before
ambition* warns about. Promotion requires the reconciliation in
:mod:`genesis.marketdata.reconcile`: measure the difference against Databento,
record the tolerance in Market Data Sources.md, make it a test. Then promote,
in config, as a decision someone made.

## Read-only, twice

``IB.connect(readonly=True)`` here, and ``READ_ONLY_API=yes`` at the gateway
(`deploy/ib-gateway/`). The gateway's flag is the real one — it is enforced by
the broker and survives a bug in this file. The client flag is a second, weaker
statement of the same intent, which is worth having because it makes the intent
legible at the call site.

There is no order path in this module and there will not be one. Phase 7's
execution connection is a separate object with a separate decision attached.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Sequence

from genesis.errors import (
    DegradedError,
    FatalError,
    GenesisError,
    TransientError,
)
from genesis.marketdata.interface import AdapterCapabilities, BarRequest, PacingRule
from genesis.marketdata.normalize import Bar, normalise_bars, parse_instrument_id

__all__ = [
    "BAR_SIZES",
    "DockerGatewayController",
    "IBKR_PACING",
    "IbkrAdapter",
    "IbkrConnection",
    "MARKET_DATA_TYPES",
    "MAX_SPANS",
]

log = logging.getLogger(__name__)

#: Our timeframe -> IBKR ``barSizeSetting``. IBKR's spelling is not guessable
#: ("1 min" but "5 mins", "1 hour" but "4 hours"), which is exactly the kind of
#: thing that belongs in one table rather than in an f-string at the call site.
BAR_SIZES = {
    "1m": "1 min",
    "5m": "5 mins",
    "15m": "15 mins",
    "30m": "30 mins",
    "1H": "1 hour",
    "4H": "4 hours",
    "1D": "1 day",
    "1W": "1 week",
    "1M": "1 month",
}

#: Longest window one request may cover, per bar size. Conservative against
#: IBKR's published table: exceeding it returns an error, and an error costs a
#: request against the 60-per-10-minutes budget, so guessing high is expensive
#: in the one currency this vendor charges in.
MAX_SPANS = {
    "1m": timedelta(days=1),
    "5m": timedelta(days=7),
    "15m": timedelta(days=14),
    "30m": timedelta(days=28),
    "1H": timedelta(days=28),
    "4H": timedelta(days=180),
    "1D": timedelta(days=365),
    "1W": timedelta(days=730),
    "1M": timedelta(days=3650),
}

#: ``reqMarketDataType``. Delayed is the honest default: it is free, needs no
#: subscription, and exercises every line of this file. When the CME bundle
#: clears, this changes and nothing else does.
MARKET_DATA_TYPES = {"realtime": 1, "frozen": 2, "delayed": 3, "delayed_frozen": 4}

#: Our exchange -> IBKR's. Equities route through SMART; futures name their
#: exchange, and CME/CBOT/NYMEX/COMEX are distinct to IBKR even though a trader
#: says "CME" for all four.
_EXCHANGES = {
    "CME": "CME", "CBOT": "CBOT", "NYMEX": "NYMEX", "COMEX": "COMEX",
    "XNAS": "SMART", "XNYS": "SMART", "ARCA": "SMART",
}

#: IBKR's three published historical-data pacing rules. Declared as data, in
#: the vocabulary `budget.py` already spoke before this adapter existed.
#:
#: These are the reason PacingRule has a `key` function rather than a
#: requests-per-second number: no two of these three count the same thing.
IBKR_PACING: tuple[PacingRule, ...] = (
    PacingRule(
        name="sixty-per-ten-minutes",
        limit=60,
        window=timedelta(minutes=10),
        key=lambda req: "*",
    ),
    PacingRule(
        name="no-identical-within-15s",
        min_interval=timedelta(seconds=15),
        key=lambda req: req.fingerprint(),
    ),
    PacingRule(
        name="six-per-contract-per-2s",
        limit=6,
        window=timedelta(seconds=2),
        key=lambda req: req.symbol_id,
    ),
)

#: IBKR connectivity notices. 1100/1101/1102/2110 concern the gateway's own link
#: to IBKR; the 21xx pairs concern one data farm, named after the colon.
_LINK_BROKEN = frozenset({1100, 2110, 2103, 2105, 2157})
_LINK_OK = frozenset({1101, 1102, 2104, 2106, 2158})


def _link_name(code: int, message: str) -> str:
    return "server" if code in (1100, 1101, 1102, 2110) else message.rsplit(":", 1)[-1].strip()


#: How far back IBKR serves a contract that has already expired. Past this it
#: has nothing, at any request rate — see Open Questions §6.
EXPIRED_HORIZON = timedelta(days=730)


class DockerGatewayController:
    """A Watchdog controller for a gateway this process does not own.

    ``ib_async.Watchdog`` expects an :class:`~ib_async.IBC` that can start and
    kill a local Java app. Under `deploy/ib-gateway/` that is wrong in both
    directions: IBC already runs *inside* the container, and this process has
    no business terminating it — Docker owns the lifecycle, including the daily
    restart IBKR forces on every session.

    But Watchdog's value here is not process management. It is the **soft
    timeout probe**: when the API goes quiet, Watchdog issues a historical
    request and, if that does not answer, tears the connection down and
    rebuilds it. That is the defence against the failure mode that actually
    bites — a ``keepUpToDate`` subscription wedging after a network blip while
    our code still believes it is subscribed. Silent, and indistinguishable
    from a quiet market until someone checks.

    So: ``startAsync`` waits for the container's gateway to be reachable rather
    than launching anything, and ``terminateAsync`` does nothing. Watchdog's
    reconnect loop and probe are preserved; its process control is declined.
    Being explicit about which half we want is the point — a controller that
    pretended to start the app would be a lie that surfaces at 4am.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 4002, wait: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.wait = wait

    async def startAsync(self) -> None:  # noqa: N802 — ib_async's spelling
        """Wait for the container's gateway, do not start one."""
        import asyncio
        import socket as _socket

        deadline = asyncio.get_event_loop().time() + self.wait
        while asyncio.get_event_loop().time() < deadline:
            try:
                with _socket.create_connection((self.host, self.port), timeout=1):
                    return
            except OSError:
                await asyncio.sleep(0.5)
        # Not an error: Watchdog's own connect will fail and it will retry with
        # its backoff. Raising here would duplicate that machinery badly.
        log.warning(
            "ib-gateway not reachable at %s:%s — is the container up? "
            "(cd deploy/ib-gateway && docker compose ps)",
            self.host, self.port,
        )

    async def terminateAsync(self) -> None:  # noqa: N802
        """Do nothing. Docker owns this process's life, not us."""
        return None


@dataclass
class IbkrConnection:
    """One IB client connection, with reconnect supervision.

    Lazily connected: constructing this costs nothing and touches no socket, so
    an :class:`IbkrAdapter` can sit in a fallback chain on a machine with no
    gateway and simply report itself unavailable.
    """

    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 17
    #: delayed | realtime | frozen | delayed_frozen. Delayed by default: free,
    #: no subscription, and it exercises every line of this file.
    market_data_type: str = "delayed"
    connect_timeout: float = 8.0
    #: Watchdog's idle threshold before it probes. IBKR sends nothing at all on
    #: a quiet overnight session, so this must be generous or the probe becomes
    #: the traffic it is checking for.
    idle_timeout: float = 60.0
    use_watchdog: bool = True

    _ib: Any = field(default=None, init=False, repr=False)
    _watchdog: Any = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    #: Links the gateway reports broken, name -> IBKR's message. Written from
    #: its connectivity notices (see :data:`_LINK_BROKEN`).
    _broken: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    # -- lifecycle ---------------------------------------------------------

    @property
    def available(self) -> bool:
        """Is the library importable? Cheap; says nothing about the gateway."""
        try:
            import ib_async  # noqa: F401
        except ImportError:
            return False
        return True

    def is_connected(self) -> bool:
        return self._ib is not None and bool(self._ib.isConnected())

    def connect(self) -> Any:
        """Connect if not already. Returns the live ``IB`` instance.

        Serialised: several supervised workers may reach for the connection at
        once, and two simultaneous connects with the same ``clientId`` is how
        IBKR ejects both.
        """
        with self._lock:
            if self.is_connected():
                self._require_links()
                return self._ib
            ib = self._make_ib()
            self._broken.clear()
            ib.errorEvent += self._on_notice
            try:
                if self.use_watchdog:
                    self._start_watchdog(ib)
                else:
                    ib.connect(
                        self.host,
                        self.port,
                        clientId=self.client_id,
                        timeout=self.connect_timeout,
                        # Second statement of read-only intent. The gateway's
                        # READ_ONLY_API is the enforcement; this makes it
                        # legible at the call site.
                        readonly=True,
                    )
            except GenesisError:
                # Already ours, already precise. Re-classifying would wrap a
                # good message in a vaguer one -- "connect failed: <the actual
                # reason>" reads like two problems.
                raise
            except Exception as exc:
                raise self._classify_connect(exc) from exc

            self._ib = ib
            # The link notices arrive during the handshake, so they are in by now.
            self._require_links()
            self._apply_market_data_type(ib)
            return ib

    def _on_notice(self, _req_id: int, code: int, message: str, *_: Any) -> None:
        if code in _LINK_BROKEN:
            self._broken[_link_name(code, message)] = message
        elif code in _LINK_OK:
            self._broken.pop(_link_name(code, message), None)

    def _require_links(self) -> None:
        """Fail closed when the socket is up but the gateway is cut off from IBKR.

        That state is invisible to ``isConnected()``: the API answers, requests
        are accepted, and nothing ever comes back -- ``qualifyContracts`` waits
        forever. Seen live on 2026-09-13: a re-login during IBKR's weekend reset
        was refused, and IBC parked on the dialog for 17 hours behind a healthy
        container.
        """
        if self._broken and self._ib is not None:
            # Notices are only delivered while the loop is pumped; an idle
            # connection may be holding an "OK" it has not read yet.
            self._ib.sleep(0.25)
        if self._broken:
            raise TransientError(
                "IB Gateway is connected but cut off from IBKR's servers ("
                + "; ".join(self._broken.values())
                + "). It usually restores itself; if it lasts more than a few "
                "minutes the gateway is stuck at login -- `docker logs "
                "genesis-ib-gateway | grep -v 'remove Client' | tail`, then "
                "`docker restart genesis-ib-gateway`."
            )

    def disconnect(self) -> None:
        with self._lock:
            if self._watchdog is not None:
                try:
                    self._watchdog.stop()
                except Exception:  # noqa: BLE001 — teardown must not raise
                    pass
                self._watchdog = None
            if self._ib is not None:
                try:
                    self._ib.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                self._ib = None

    def __enter__(self) -> "IbkrConnection":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()

    # -- internals ---------------------------------------------------------

    def _make_ib(self) -> Any:
        try:
            from ib_async import IB
        except ImportError as exc:
            raise DegradedError(
                "the `ib_async` package is not installed; "
                "`uv pip install ib_async` (or install the `ibkr` extra)"
            ) from exc
        return IB()

    def _start_watchdog(self, ib: Any) -> None:
        """Watchdog with a controller that declines to own the process.

        See :class:`DockerGatewayController` for why. In short: we want the
        soft-timeout probe that catches a wedged subscription, and we do not
        want a Python process killing a container's gateway.
        """
        from ib_async import Watchdog

        self._watchdog = Watchdog(
            controller=DockerGatewayController(self.host, self.port),
            ib=ib,
            host=self.host,
            port=self.port,
            clientId=self.client_id,
            connectTimeout=self.connect_timeout,
            readonly=True,
            appStartupTime=0.0,  # the container is already up or it is not
            appTimeout=self.idle_timeout,
        )
        self._watchdog.start()
        # Watchdog connects asynchronously. Wait for it rather than returning a
        # connection that is not yet one -- a caller handed a half-open client
        # gets a confusing timeout instead of a clear connect failure.
        ib.sleep(0.1)
        deadline = self.connect_timeout + 2.0
        waited = 0.0
        while not ib.isConnected() and waited < deadline:
            ib.sleep(0.25)
            waited += 0.25
        if not ib.isConnected():
            raise TransientError(
                f"IB Gateway at {self.host}:{self.port} did not accept a "
                f"connection within {deadline:.0f}s. Is the container up and "
                f"logged in? `cd deploy/ib-gateway && docker compose logs`"
            )

    def _apply_market_data_type(self, ib: Any) -> None:
        code = MARKET_DATA_TYPES.get(self.market_data_type)
        if code is None:
            raise FatalError(
                f"unknown market_data_type {self.market_data_type!r}; "
                f"expected one of {sorted(MARKET_DATA_TYPES)}"
            )
        ib.reqMarketDataType(code)

    @staticmethod
    def _classify_connect(exc: Exception) -> Exception:
        text = str(exc)
        lowered = text.lower()
        # Before the OSError branch: TimeoutError IS an OSError, and it means
        # the opposite of refused -- the port answered, the API handshake did
        # not, which is a gateway that is up but not logged in.
        if isinstance(exc, TimeoutError):
            return TransientError(
                "IB Gateway is up but did not complete the API handshake -- it is "
                "not logged in yet. Waiting on a 2FA approval, an 'Existing "
                "session detected' prompt, or a wrong password: "
                "`cd deploy/ib-gateway && docker compose logs --tail 40`"
            )
        if isinstance(exc, (ConnectionRefusedError, OSError)) or "refused" in lowered:
            return TransientError(
                f"IB Gateway is not accepting connections: {text}. "
                f"Start it with `cd deploy/ib-gateway && docker compose up -d`."
            )
        if "timeout" in lowered:
            return TransientError(f"IB Gateway connect timed out: {text}")
        if "clientid" in lowered or "already in use" in lowered:
            return FatalError(
                f"IBKR rejected the client id: {text}. Another process is "
                f"connected with the same clientId; change marketdata."
                f"adapters.ibkr.client_id."
            )
        return TransientError(f"IB Gateway connect failed: {text}")


@dataclass
class IbkrAdapter:
    """Historical bars from IBKR. Tier 3 until reconciled.

    Satisfies :class:`~genesis.marketdata.interface.Adapter` and nothing wider.
    Live streaming is :meth:`stream_bars`, which is deliberately *not* part of
    that Protocol -- a streaming subscription has a lifecycle, and putting it
    behind the same two-method interface as a cheap retryable read would blur
    the one distinction this package is built on.
    """

    connection: IbkrConnection = field(default_factory=IbkrConnection)
    #: TIER 3, NOT 1. Promotion requires the reconciliation in
    #: `genesis.marketdata.reconcile` -- measured, recorded in Market Data
    #: Sources.md, and made a test. See the module docstring.
    tier: int = 3
    name: str = "ibkr"
    #: TRADES is the right default for futures and equities. MIDPOINT exists
    #: for instruments with no trade prints; it is a per-request override
    #: through `BarRequest.vendor_options`, not a global setting.
    what_to_show: str = "TRADES"
    #: Regular trading hours only. False for futures: ES trades nearly 24x5 and
    #: RTH-only bars silently discard the overnight session, which is where a
    #: large share of the move often happens.
    use_rth: bool = False
    requests: int = field(default=0, init=False)

    @property
    def available(self) -> bool:
        return self.connection.available

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self.name,
            tier=self.tier,
            timeframes=frozenset(BAR_SIZES),
            asset_classes=frozenset({"FUT", "EQ", "IDX", "FX", "CRYPTO"}),
            max_span=dict(MAX_SPANS),
            earliest=None,
            # It serves expired contracts, but only just -- and this horizon is
            # why Databento exists in the chain at all.
            serves_expired_contracts=True,
            expired_contract_horizon=EXPIRED_HORIZON,
            adjusted=False,
            supports_streaming=True,
            # A gateway must be up and logged in. The 3am market-closed loop has
            # to be able to see this before it schedules against it.
            requires_session=True,
            pacing=IBKR_PACING,
        )

    # -- historical --------------------------------------------------------

    def fetch(self, request: BarRequest) -> Sequence[Bar]:
        bar_size = BAR_SIZES.get(request.timeframe)
        if bar_size is None:
            raise DegradedError(
                f"IBKR has no bar size for {request.timeframe}; "
                f"known: {sorted(BAR_SIZES)}"
            )

        instrument = parse_instrument_id(request.symbol_id)
        if instrument.is_continuous:
            raise DegradedError(
                f"{request.symbol_id}: continuous contracts are not built "
                f"(Open Questions §13). IBKR's own CONTFUT exists but its roll "
                f"convention is undocumented, which is the same problem."
            )
        self._guard_expiry(instrument, request)

        ib = self.connection.connect()
        contract = self._qualify(ib, instrument)

        self.requests += 1
        try:
            raw = ib.reqHistoricalData(
                contract,
                endDateTime=request.end,
                durationStr=_duration_str(request.start, request.end),
                barSizeSetting=bar_size,
                whatToShow=request.vendor_options.get(
                    "whatToShow", self._what_to_show(instrument)
                ),
                useRTH=request.vendor_options.get("useRTH", self.use_rth),
                # 2 = epoch seconds, UTC. The only unambiguous option: 1
                # formats in the *account's* timezone, which makes every bar's
                # calendar day a function of a setting in a GUI nobody looks at.
                formatDate=2,
                keepUpToDate=False,
                timeout=request.vendor_options.get("timeout", 60),
            )
        except Exception as exc:
            raise self._classify(exc, request.symbol_id) from exc

        if not raw:
            # A fact, not a failure. The store records the empty window as
            # coverage so we never ask again.
            return []

        return normalise_bars(
            (_row(b) for b in raw),
            symbol_id=request.symbol_id,
            timeframe=request.timeframe,
            source=self.name,
            tier=self.tier,
            adjusted=False,
        )

    # -- live --------------------------------------------------------------

    def stream_bars(
        self,
        symbol_id: str,
        timeframe: str,
        *,
        on_bar: Callable[[Bar], None],
        on_forming: Callable[[dict[str, Any]], None] | None = None,
        lookback: timedelta = timedelta(days=1),
    ) -> Any:
        """Subscribe to updates on the forming bar. Returns the subscription.

        ``keepUpToDate=True`` streams updates to the last bar and appends a new
        one when it closes. Two things about it are worth stating plainly,
        because both are ways to be wrong quietly:

        **Only closed bars are handed to ``on_bar``.** The final element of an
        IBKR bar list with ``keepUpToDate`` is the *forming* bar and it changes
        on every tick. Writing it to the store would violate the store's
        central promise -- closed bars are immutable -- and would poison every
        backtest with a bar that never actually printed that way. So the
        forming bar is watched and only emitted once a later bar supersedes it.

        **This is the subscription that wedges.** After a network blip IBKR can
        stop sending while the client still believes it is subscribed: no
        error, no disconnect, just a market that appears to have gone quiet.
        That is why :class:`IbkrConnection` runs a Watchdog whose probe catches
        exactly this, and why ``use_watchdog=False`` is a testing convenience
        rather than a deployment option.

        ``on_forming`` receives the forming bar as a raw row on every update.
        It is for drawing the right edge of a live chart and nothing else --
        it is never a :class:`Bar`, so it cannot be written to the store.
        """
        bar_size = BAR_SIZES.get(timeframe)
        if bar_size is None:
            raise DegradedError(f"IBKR has no bar size for {timeframe}")

        instrument = parse_instrument_id(symbol_id)
        ib = self.connection.connect()
        contract = self._qualify(ib, instrument)

        end = datetime.now(UTC)
        subscription = ib.reqHistoricalData(
            contract,
            endDateTime="",  # required to be empty when keepUpToDate is set
            durationStr=_duration_str(end - lookback, end),
            barSizeSetting=bar_size,
            whatToShow=self._what_to_show(instrument),
            useRTH=self.use_rth,
            formatDate=2,
            keepUpToDate=True,
        )

        # The last bar is always the forming one. Track how many have closed so
        # far, and emit only as that count grows.
        closed = max(len(subscription) - 1, 0)

        def _on_update(bars: Any, has_new_bar: bool) -> None:
            nonlocal closed
            # `has_new_bar` is IBKR telling us a bar rolled over -- but trust
            # the length rather than the flag, because the flag is advisory and
            # a missed one would mean a permanently skipped bar.
            newly_closed = max(len(bars) - 1, 0)
            while closed < newly_closed:
                row = _row(bars[closed])
                (bar,) = normalise_bars(
                    [row],
                    symbol_id=symbol_id,
                    timeframe=timeframe,
                    source=self.name,
                    tier=self.tier,
                )
                closed += 1
                on_bar(bar)
            if on_forming is not None and bars:
                on_forming(_row(bars[-1]))

        subscription.updateEvent += _on_update
        return subscription

    def cancel_stream(self, subscription: Any) -> None:
        """Stop a subscription. Safe to call on one already cancelled."""
        if not self.connection.is_connected():
            return
        try:
            self.connection.connect().cancelHistoricalData(subscription)
        except Exception as exc:  # noqa: BLE001
            log.warning("cancelling IBKR subscription failed: %s", exc)

    # -- contracts ---------------------------------------------------------

    def _qualify(self, ib: Any, instrument: Any) -> Any:
        """Canonical symbol id -> a fully-qualified IBKR contract.

        This is where the §13 work pays off. IBKR wants
        ``Future(symbol='ES', exchange='CME', lastTradeDateOrContractMonth=
        '202512')``, and our id carries exactly that with the full year --
        which is what makes the mapping total rather than a guess. Had bare
        ``ES`` been allowed to mean "the front month", this is the line where
        it would have resolved to a different contract depending on the day
        the code ran.

        ``qualifyContracts`` is not optional: an unqualified contract is
        ambiguous to IBKR and it will either error or, worse, resolve to
        something adjacent.
        """
        from ib_async import Contract, Crypto, Forex, Future, Index, Stock

        exchange = _EXCHANGES.get(instrument.exchange, instrument.exchange)

        if instrument.is_future:
            if not instrument.contract_month:
                raise DegradedError(
                    f"{instrument.symbol_id}: no contract month. "
                    f"Open Questions §13 -- never guess the front month."
                )
            year, month = instrument.contract_month.split("-")
            contract: Contract = Future(
                symbol=instrument.root,
                exchange=exchange,
                lastTradeDateOrContractMonth=f"{year}{month}",
                currency=instrument.currency,
                # Without this, an already-expired contract simply does not
                # resolve -- and the failure reads like a bad symbol rather
                # than like a horizon.
                includeExpired=True,
            )
        elif instrument.asset_class == "IDX":
            # No currency: an index's is its venue's (DAX is EUR), and the id
            # does not carry it. IBKR resolves symbol + exchange uniquely.
            contract = Index(symbol=instrument.root, exchange=exchange)
        elif instrument.asset_class == "FX":
            contract = Forex(pair=instrument.root, exchange=exchange)
        elif instrument.asset_class == "CRYPTO":
            contract = Crypto(symbol=instrument.root, exchange=exchange, currency="USD")
        elif instrument.exchange in _EXCHANGES:
            contract = Stock(
                symbol=instrument.root,
                exchange=exchange,
                currency=instrument.currency,
            )
        else:
            # A venue we have no MIC for (LSE, TSEJ, ...): the id carries
            # IBKR's own code, so route SMART with it as the primary listing and
            # let qualification supply the currency rather than assuming USD.
            contract = Stock(
                symbol=instrument.root, exchange="SMART", primaryExchange=instrument.exchange,
            )

        try:
            qualified = ib.qualifyContracts(contract)
        except Exception as exc:
            raise self._classify(exc, instrument.symbol_id) from exc

        if not qualified:
            raise DegradedError(
                f"IBKR could not resolve {instrument.symbol_id} "
                f"(tried {contract}). For an expired contract, check it is "
                f"within {EXPIRED_HORIZON.days} days of expiry -- past that "
                f"IBKR has nothing and Databento is the only source."
            )
        return qualified[0]

    def _what_to_show(self, instrument: Any) -> str:
        """FX has no trade prints and IBKR refuses TRADES for it; PAXOS crypto
        only answers AGGTRADES. Everything else keeps :attr:`what_to_show`."""
        return {"FX": "MIDPOINT", "CRYPTO": "AGGTRADES"}.get(
            instrument.asset_class, self.what_to_show
        )

    def _guard_expiry(self, instrument: Any, request: BarRequest) -> None:
        """Refuse before spending a request we know will come back empty.

        A request against a long-expired contract is not an error to IBKR --
        it answers with nothing. That costs one of sixty requests per ten
        minutes and teaches the caller nothing, so the horizon is checked here
        where it can be explained.
        """
        if not instrument.is_future or not instrument.contract_month:
            return
        year, month = (int(x) for x in instrument.contract_month.split("-"))
        # Expiry is mid-month for the quarterly equity index contracts; the
        # month's end is close enough for a two-year horizon check and errs
        # towards allowing the request.
        expiry = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=UTC)
        age = datetime.now(UTC) - expiry
        if age > EXPIRED_HORIZON:
            raise DegradedError(
                f"{instrument.symbol_id} expired {age.days} days ago; IBKR "
                f"serves expired contracts for about "
                f"{EXPIRED_HORIZON.days} days. Use databento for this history "
                f"-- that limit is why it is in the chain (Open Questions §6)."
            )

    # -- errors ------------------------------------------------------------

    @staticmethod
    def _classify(exc: Exception, symbol: str) -> Exception:
        """IBKR error -> one of ours, per Conventions.md §Errors.

        The distinctions that matter operationally: a pacing violation is
        transient and self-heals, a missing subscription is fatal and needs a
        human with a credit card, and "no data" is degraded and should fall
        down the chain.
        """
        text = str(exc)
        lowered = text.lower()
        if "pacing" in lowered or "max rate" in lowered or "162" in text:
            return TransientError(
                f"IBKR pacing violation on {symbol}: {text}. "
                f"budget.py should have prevented this -- if it recurs, the "
                f"declared rules are wrong, not the vendor."
            )
        if "market data" in lowered and (
            "subscri" in lowered or "permission" in lowered or "354" in text
        ):
            return FatalError(
                f"no market data permission for {symbol}: {text}. "
                f"Either subscribe to the CME bundle (~$10/month) or run in "
                f"delayed mode (market_data_type: delayed), which is free."
            )
        if "not connected" in lowered or "disconnect" in lowered:
            return TransientError(f"IBKR connection lost during {symbol}: {text}")
        if "timeout" in lowered:
            return TransientError(f"IBKR timed out on {symbol}: {text}")
        if "no security definition" in lowered or "200" in text:
            return DegradedError(
                f"IBKR does not know {symbol}: {text}. Check the contract "
                f"month, or the contract may be beyond the expired horizon."
            )
        return DegradedError(f"IBKR request failed for {symbol}: {text}")


# --------------------------------------------------------------------------
# Conversion helpers
# --------------------------------------------------------------------------


def _duration_str(start: datetime, end: datetime) -> str:
    """A window as IBKR's ``durationStr``. Constraint #1, absorbed here.

    Rounds **up**, always. Asking for slightly more than the window costs
    nothing -- the extra bars are trimmed by the half-open filter downstream --
    while asking for slightly less silently truncates the history the whole
    request was for, and a short answer is indistinguishable from a thin
    market.
    """
    span = max(end - start, timedelta(seconds=30))
    seconds = span.total_seconds()
    if seconds <= 86_400:
        # IBKR accepts seconds only up to a day, and only in whole seconds.
        # Capped at exactly 86400: rounding a one-day window up to "86401 S"
        # is rejected (error 321), and ib_async reports that as a warning, so
        # the request silently waits out its timeout and returns nothing.
        return f"{min(int(seconds) + 1, 86_400)} S"
    days = int(seconds // 86_400) + 1
    if days <= 365:
        return f"{days} D"
    return f"{days // 365 + 1} Y"


def _row(bar: Any) -> dict[str, Any]:
    """One ``ib_async.BarData`` as a normalise-able row.

    ``bar.date`` arrives as an aware datetime, a naive datetime, or a plain
    ``date`` depending on bar size and ``formatDate`` -- daily bars in
    particular come back as a date. A naive value is UTC here because
    ``formatDate=2`` was requested; assuming that anywhere else in the stack
    would be a guess, which is why the conversion lives next to the flag that
    justifies it.
    """
    when = bar.date
    if isinstance(when, datetime):
        ts = when if when.tzinfo else when.replace(tzinfo=UTC)
    elif isinstance(when, date):
        ts = datetime(when.year, when.month, when.day, tzinfo=UTC)
    else:
        ts = when  # an epoch int or ISO string; normalize.utc handles both
    volume = bar.volume
    return {
        "ts": ts,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        # IBKR reports -1 for "no volume data" on some instruments. That is not
        # zero volume, and storing it as a negative number would corrupt every
        # volume-weighted calculation downstream.
        "volume": 0 if volume is None or float(volume) < 0 else volume,
    }
