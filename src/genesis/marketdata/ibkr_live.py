# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""The IBKR session `genesis serve` holds open: live bars, and the account.

One thread, one read-only connection. It does three things, in this order,
every time it (re)connects:

1. **Backfill.** For each ``marketdata.live`` series, fetch from the last bar
   on disk to now. This is what makes a closed laptop harmless: whatever
   printed while Genesis was off is pulled from IBKR's history on the next
   start, so the chart has no hole.
2. **Stream.** ``keepUpToDate`` subscriptions. Closed bars go to the store;
   the forming bar goes only to the UI, as ``market.bar`` with
   ``closed: false``. The store's promise -- closed bars are immutable -- is
   kept by :meth:`IbkrAdapter.stream_bars`, which never hands it a forming bar.
3. **Account.** ``ib_async`` syncs account values and the portfolio on connect
   and keeps them current; this copies them into :attr:`account` once a second
   for ``/v1/broker/account``. Paper or live is read from the account id the
   broker returns (``DU…`` is paper), never from our own port number.

It runs inside the server rather than as its own process because DuckDB allows
one writer per file: a separate recorder would lock the UI out of the store.

Read-only, like the adapter. There is no order path here.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any, Callable

from genesis.charting.source import lookback_start
from genesis.charting.timeframes import resolve
from genesis.config import Config
from genesis.errors import TransientError
from genesis.marketdata.adapters.ibkr import IbkrAdapter, IbkrConnection
from genesis.marketdata.normalize import Bar

__all__ = ["IbkrLive", "apply", "current", "start", "stop"]

log = logging.getLogger(__name__)

#: No update on any subscription for this long is treated as a wedge, and the
#: session is rebuilt (which re-backfills, so nothing is lost).
# ponytail: also fires through the CME daily halt and weekends, costing one
# resubscribe every few minutes. Gate on the market calendar if it gets noisy.
IDLE_REBUILD_SEC = 180.0
RETRY_SEC = 30.0

ACCOUNT_TAGS = (
    "NetLiquidation", "TotalCashValue", "BuyingPower", "AvailableFunds",
    "ExcessLiquidity", "InitMarginReq", "MaintMarginReq",
    "UnrealizedPnL", "RealizedPnL", "GrossPositionValue",
)

Emit = Callable[[str, dict[str, Any]], None]


class _Idle(TransientError):
    """The market went quiet, or the subscription wedged. Rebuild at once."""


class _Reload(TransientError):
    """Settings were saved from the UI. Rebuild with them."""


class IbkrLive:
    def __init__(self, config: Config, emit: Emit) -> None:
        self.config = config
        self.emit = emit
        self.status: dict[str, Any] = {"state": "starting", "detail": "", "since": _now()}
        self.account: dict[str, Any] | None = None
        self._last_update = time.monotonic()
        self._stop = threading.Event()
        self._reload = threading.Event()
        #: Set by stop() and reconfigure(), so neither waits out a retry pause.
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ibkr-live", daemon=True)
        self._configure()

    def _configure(self) -> None:
        """Connection and series from :attr:`config`. Re-run at every session start."""
        config = self.config
        spec = config.marketdata.adapters["ibkr"]
        self.series = [(s["symbol_id"], s["timeframe"]) for s in config.marketdata.live]
        self.connection = IbkrConnection(
            host=spec.host or "127.0.0.1",
            port=spec.port or 4002,
            # One above the adapter's, so `genesis ibkr check` or a chart
            # command can connect while the server holds this session.
            client_id=(spec.client_id if spec.client_id is not None else 17) + 1,
            market_data_type=spec.market_data_type or "delayed",
            # This loop is its own watchdog: it resubscribes after a reconnect,
            # which ib_async's Watchdog does not.
            use_watchdog=False,
        )
        self.adapter = IbkrAdapter(connection=self.connection, tier=spec.tier)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=5)

    def reconfigure(self, config: Config) -> None:
        """Apply new settings on this thread's next session -- one connection
        at a time, so the client id is never held twice."""
        self.config = config
        self._reload.set()
        self._wake.set()

    def snapshot(self) -> dict[str, Any]:
        c = self.connection
        return {
            "available": True,
            "gateway": f"{c.host}:{c.port}",
            "client_id": c.client_id,
            "market_data_type": c.market_data_type,
            "series": [{"symbol_id": s, "timeframe": tf} for s, tf in self.series],
            **self.status,
            "account": self.account,
        }

    # -- the loop ----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            wait = RETRY_SEC
            try:
                self._session()
            except _Idle as exc:
                self._set("quiet", exc.reason)
                wait = 1.0
            except _Reload:
                wait = 0.0
            except Exception as exc:  # noqa: BLE001 — a dead gateway is expected, not fatal
                self._set("down", getattr(exc, "reason", None) or str(exc))
                log.warning("ibkr live session ended: %s", exc)
            finally:
                self.connection.disconnect()
            self._wake.wait(wait)
            self._wake.clear()

    def _session(self) -> None:
        from genesis.marketdata.budget import Budget
        from genesis.marketdata.source import StoreBarSource
        from genesis.marketdata.store import open_store

        self._reload.clear()
        self._configure()
        self._set("connecting", self.snapshot()["gateway"])
        ib = self.connection.connect()
        # The account first: it is synced by the time connect returns, and it
        # must not wait behind a backfill that can take minutes on a first run.
        self.account = account_snapshot(ib)
        self.emit("broker.account", self.account)
        self._set("syncing", f"logged in · backfilling {len(self.series)} series")
        store = open_store(self.config.marketdata.store_path)
        source = StoreBarSource(
            store=store,
            adapters=[self.adapter],
            # Created in this thread: sqlite handles do not cross threads.
            budget=Budget(self.config.marketdata.budget_path),
        )

        for symbol_id, timeframe in self.series:
            self._backfill(source, store, symbol_id, timeframe)
            self.adapter.stream_bars(
                symbol_id, timeframe,
                on_bar=lambda bar, s=store: self._closed(s, bar),
                on_forming=lambda row, sid=symbol_id, tf=timeframe: self._forming(sid, tf, row),
            )

        self._set("live", f"{len(self.series)} series streaming")
        self._last_update = time.monotonic()
        while not self._stop.is_set():
            ib.sleep(1.0)  # pumps ib_async's loop; updates are delivered here
            if self._reload.is_set():
                raise _Reload("settings changed")
            if not ib.isConnected():
                raise TransientError("gateway disconnected")
            snap = account_snapshot(ib)
            if self.account is None or {**snap, "as_of": None} != {**self.account, "as_of": None}:
                self.emit("broker.account", snap)  # pushed, so the panel never polls
            self.account = snap
            if self.series and time.monotonic() - self._last_update > IDLE_REBUILD_SEC:
                raise _Idle(f"no updates for {IDLE_REBUILD_SEC:.0f}s — resubscribing")

    def _backfill(self, source: Any, store: Any, symbol_id: str, timeframe: str) -> None:
        tf = resolve(timeframe)
        start = store.last_bar_time(symbol_id, tf.label) or lookback_start(
            tf.label, tf.default_lookback_bars
        )
        try:
            counts = source.fill(symbol_id, tf.label, start, datetime.now(UTC))
            log.info("ibkr backfill %s %s: %s", symbol_id, timeframe, counts)
        except Exception as exc:  # noqa: BLE001 — a short window is not a dead session
            log.info("ibkr backfill %s %s: %s", symbol_id, timeframe, exc)

    def _closed(self, store: Any, bar: Bar) -> None:
        store.write([bar])
        self._last_update = time.monotonic()
        self.emit("market.bar", {
            "symbol_id": bar.symbol_id, "timeframe": bar.timeframe, "closed": True,
            "bar": bar_row(bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume,
                           bar.source, bar.tier),
        })

    def _forming(self, symbol_id: str, timeframe: str, row: dict[str, Any]) -> None:
        self._last_update = time.monotonic()
        self.emit("market.bar", {
            "symbol_id": symbol_id, "timeframe": timeframe, "closed": False,
            "bar": bar_row(row["ts"], row["open"], row["high"], row["low"], row["close"],
                           row["volume"], self.adapter.name, self.adapter.tier),
        })

    def _set(self, state: str, detail: str) -> None:
        if state != self.status["state"]:
            self.emit("broker.connection", {"broker": "ibkr", "state": state, "detail": detail})
        self.status = {"state": state, "detail": detail, "since": _now()}


# --------------------------------------------------------------------------
# pure helpers — tested without a gateway
# --------------------------------------------------------------------------


def bar_row(ts: datetime, o: Any, h: Any, l: Any, c: Any, v: Any, source: str, tier: int) -> dict[str, Any]:  # noqa: E741
    """The ``BarRow`` shape `/v1/market/bars` serves, so the chart merges it as-is."""
    return {
        "time": int(ts.timestamp()), "ts": ts.isoformat(),
        "open": str(o), "high": str(h), "low": str(l), "close": str(c), "volume": str(v),
        "source": source, "tier": tier, "adjusted": False,
    }


def account_snapshot(ib: Any) -> dict[str, Any]:
    """Balances and positions, as the broker last reported them."""
    accounts = list(ib.managedAccounts())
    values: dict[str, dict[str, dict[str, str]]] = {a: {} for a in accounts}
    for v in ib.accountValues():
        # `BASE` repeats a value already given in the base currency's own code.
        if v.tag in ACCOUNT_TAGS and v.currency != "BASE":
            values.setdefault(v.account, {}).setdefault(
                v.tag, {"value": v.value, "currency": v.currency}
            )
    positions = [
        {
            "account": p.account,
            "symbol": p.contract.localSymbol or p.contract.symbol,
            "sec_type": p.contract.secType,
            "position": p.position,
            "market_price": p.marketPrice,
            "market_value": p.marketValue,
            "average_cost": p.averageCost,
            "unrealized_pnl": p.unrealizedPNL,
            "realized_pnl": p.realizedPNL,
        }
        for p in ib.portfolio()
    ]
    return {
        "as_of": _now(),
        # IBKR paper accounts are `DU…` (or `DF…` for advisors); live are `U…`.
        "mode": "paper" if accounts and all(a.startswith("D") for a in accounts) else "live",
        "accounts": accounts,
        "values": values,
        "positions": positions,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------
# the process's one session
# --------------------------------------------------------------------------

_LIVE: IbkrLive | None = None
_EMIT: Emit | None = None


def current() -> IbkrLive | None:
    return _LIVE


def start(config: Config, emit: Emit) -> IbkrLive | None:
    """Start the session if IBKR is enabled. Returns ``None`` when it is not."""
    global _LIVE, _EMIT
    _EMIT = emit
    spec = config.marketdata.adapters.get("ibkr")
    if spec is None or not spec.enabled or _LIVE is not None:
        return _LIVE
    _LIVE = IbkrLive(config, emit)
    _LIVE.start()
    return _LIVE


def stop() -> None:
    global _LIVE
    if _LIVE is not None:
        _LIVE.stop()
        _LIVE = None


def apply(config: Config) -> None:
    """Bring the running session in line with freshly saved config."""
    spec = config.marketdata.adapters.get("ibkr")
    if spec is None or not spec.enabled:
        stop()
    elif _LIVE is not None:
        _LIVE.reconfigure(config)
    elif _EMIT is not None:
        start(config, _EMIT)
