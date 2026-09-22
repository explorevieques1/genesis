# Spec: Genesis Markdown/20-Agents/Execution/Agent — Broker Adapter.md
"""Agent — Broker Adapter, for IB Gateway. The only module that sends orders.

Efferent, and built as one (Biological Design §afferent ≠ efferent): its own
connection, its own fixed client id, Read-Only off -- separate from every data
connection in `genesis.marketdata`, which stay read-only.

**Only :class:`~genesis.execution.order_manager.OrderManager` calls this**, and
only on the thread that owns it: ``ib_async`` is not thread-safe and runs its
event loop wherever it is pumped.

Three things verified against the paper gateway on 2026-09-13 shape it:

- Native brackets work, trailing-stop children included, and ``orderRef``
  round-trips -- so the ``client_order_id`` travels with the order and is how
  every broker event is matched back to the ledger.
- Reconnecting with the **same** client id returns that client's working
  orders and can manage them. That is why orders survive Genesis closing.
- Another client id sees those orders but cannot cancel them (error 10147).
  The kill switch is designed around that.

**Paper only.** :meth:`connect` refuses an account whose id does not start with
``D`` (IBKR paper accounts are ``DU…``), independently of the config flag the
order manager also checks. Two locks, one per side of the socket.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

from genesis.errors import DegradedError, FatalError, TransientError

__all__ = ["ContractInfo", "IbkrBroker", "in_session", "round_to_tick", "status_to_state"]

log = logging.getLogger(__name__)

#: IBKR order status -> Order And Fill Schema state.
_STATES = {
    "PendingSubmit": "submitted", "ApiPending": "submitted", "PendingCancel": "accepted",
    "PreSubmitted": "accepted", "Submitted": "accepted", "Filled": "filled",
    "Cancelled": "cancelled", "ApiCancelled": "cancelled", "Inactive": "rejected",
}
WORKING = frozenset({"PendingSubmit", "ApiPending", "PreSubmitted", "Submitted", "PendingCancel"})
_TYPES = {"MKT": "market", "LMT": "limit", "STP": "stop", "TRAIL": "trail"}


def status_to_state(status: str, filled: float, remaining: float) -> str:
    if status in ("PreSubmitted", "Submitted") and filled > 0 and remaining > 0:
        return "partially_filled"
    return _STATES.get(status, "submitted")


def round_to_tick(price: Decimal, tick: Decimal, *, up: bool | None = None) -> Decimal:
    """Snap to the tick grid. ``up`` None rounds to nearest; True/False direct it."""
    steps = price / tick
    n = steps.to_integral_value(rounding="ROUND_CEILING" if up else "ROUND_FLOOR" if up is False else "ROUND_HALF_UP")
    return n * tick


def in_session(trading_hours: str, tz: str, now: datetime) -> bool | None:
    """Is ``now`` inside one of IBKR's ``tradingHours`` sessions?

    Format: ``20260913:1700-20260914:1600;20260919:CLOSED``. ``None`` when the
    string cannot be read -- the risk engine rejects on that, it does not guess.
    """
    try:
        zone = ZoneInfo(tz)
        local = now.astimezone(zone)
        seen = False
        for part in filter(None, trading_hours.split(";")):
            if "CLOSED" in part:
                seen = True
                continue
            start, end = part.split("-")
            s = datetime.strptime(start, "%Y%m%d:%H%M").replace(tzinfo=zone)
            e = datetime.strptime(end, "%Y%m%d:%H%M").replace(tzinfo=zone)
            seen = True
            if s <= local < e:
                return True
        return False if seen else None
    except Exception:  # noqa: BLE001 — unreadable hours are unknown, not open
        return None


def _dec(value: Any) -> Decimal | None:
    """A broker float as Decimal. NaN, blanks, and IBKR's 1.79e308 'unset' are None."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f) or abs(f) > 1e300:
        return None
    return Decimal(str(value))


def _transmits(specs: list[dict[str, Any]], i: int) -> bool:
    """IBKR bracket rule: every order in a parent/child group but the last waits."""
    group = specs[i].get("parent_ref") or specs[i]["ref"]
    return not any((s.get("parent_ref") or s["ref"]) == group for s in specs[i + 1:])


@dataclass(frozen=True)
class ContractInfo:
    symbol_id: str
    root: str
    local_symbol: str
    con_id: int
    multiplier: Decimal
    min_tick: Decimal
    trading_hours: str
    time_zone: str
    contract: Any


class IbkrBroker:
    """Synchronous, single-threaded. Callbacks fire from inside :meth:`pump`."""

    def __init__(self, *, host: str, port: int, client_id: int, market_data_type: str = "delayed",
                 ib_factory: Callable[[], Any] | None = None) -> None:
        self.host, self.port, self.client_id = host, port, client_id
        self.market_data_type = market_data_type
        self._factory = ib_factory
        self.ib: Any = None
        self.account: str | None = None
        self._contracts: dict[str, ContractInfo] = {}
        self._by_con: dict[int, ContractInfo] = {}
        self._tickers: dict[int, Any] = {}
        self._pnl_single: dict[int, Any] = {}
        self._pnl: Any = None
        self._errors: dict[int, str] = {}
        self._fill_seen: set[str] = set()
        self.on_status: Callable[[dict[str, Any]], None] = lambda view: None
        self.on_fill: Callable[[dict[str, Any]], None] = lambda fill: None

    # -- lifecycle ----------------------------------------------------------

    def connected(self) -> bool:
        return self.ib is not None and bool(self.ib.isConnected())

    def connect(self) -> str:
        if self._factory:
            ib = self._factory()
        else:
            from ib_async import IB

            ib = IB()
        try:
            ib.connect(self.host, self.port, clientId=self.client_id, timeout=15, readonly=False)
        except Exception as exc:
            raise TransientError(f"order connection to IB Gateway {self.host}:{self.port} failed: {exc}") from exc
        accounts = list(ib.managedAccounts())
        if not accounts or not all(a.startswith("D") for a in accounts):
            ib.disconnect()
            raise FatalError(
                f"refusing to trade: IBKR account(s) {accounts or '—'} are not paper (DU…). "
                f"Live trading needs Paper To Live Promotion, not a login change."
            )
        self.ib, self.account = ib, accounts[0]
        code = {"realtime": 1, "frozen": 2, "delayed": 3, "delayed_frozen": 4}.get(self.market_data_type, 3)
        ib.reqMarketDataType(code)
        ib.errorEvent += self._on_error
        ib.orderStatusEvent += self._on_trade
        ib.openOrderEvent += self._on_trade
        ib.commissionReportEvent += self._on_commission
        # Orders from every client, so the kill switch's and TWS's are visible.
        ib.reqAllOpenOrders()
        self._pnl = ib.reqPnL(self.account)
        return self.account

    def disconnect(self) -> None:
        if self.ib is not None:
            try:
                self.ib.disconnect()
            except Exception:  # noqa: BLE001 — teardown must not raise
                pass
        self.ib = None
        self._tickers.clear()
        self._pnl_single.clear()

    def pump(self, seconds: float) -> None:
        self.ib.sleep(seconds)

    # -- contracts and quotes -----------------------------------------------

    def qualify(self, symbol_id: str) -> ContractInfo:
        if symbol_id in self._contracts:
            return self._contracts[symbol_id]
        from genesis.marketdata.adapters.ibkr import IbkrAdapter
        from genesis.marketdata.normalize import parse_instrument_id

        instrument = parse_instrument_id(symbol_id)
        contract = IbkrAdapter._qualify(IbkrAdapter(), self.ib, instrument)
        details = self.ib.reqContractDetails(contract)
        if not details:
            raise DegradedError(f"IBKR returned no contract details for {symbol_id}")
        d = details[0]
        info = ContractInfo(
            symbol_id=symbol_id, root=instrument.root, local_symbol=contract.localSymbol or instrument.root,
            con_id=int(contract.conId), multiplier=_dec(contract.multiplier) or Decimal(1),
            min_tick=_dec(d.minTick) or Decimal(0), trading_hours=d.tradingHours or "",
            time_zone=d.timeZoneId or "", contract=contract,
        )
        self._contracts[symbol_id] = info
        self._by_con[info.con_id] = info
        return info

    def info_for_con(self, con_id: int) -> ContractInfo | None:
        return self._by_con.get(con_id)

    def quote(self, info: ContractInfo) -> dict[str, Any]:
        ticker = self._tickers.get(info.con_id)
        if ticker is None:
            ticker = self._tickers[info.con_id] = self.ib.reqMktData(info.contract, "", False, False)
            self.ib.sleep(1.5)  # first quote; later calls read the live subscription
        # IBKR sends -1 (and briefly 0) for "no bid/ask"; averaging one in
        # halved the mid on 2026-09-14. Only a positive price is a price.
        bid, ask, last = (x if x is not None and x > 0 else None
                          for x in (_dec(ticker.bid), _dec(ticker.ask), _dec(ticker.last)))
        mid = (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid else last
        source = {1: "realtime", 2: "frozen", 3: "delayed", 4: "delayed_frozen"}.get(ticker.marketDataType)
        return {"bid": bid, "ask": ask, "last": last, "mid": mid, "source": source,
                "ts": datetime.now(UTC).isoformat()}

    def what_if_margin(self, info: ContractInfo, side: str, qty: int) -> Decimal | None:
        from ib_async import MarketOrder

        try:
            # An explicit TIF: left blank, the gateway applies its order preset,
            # warns 10349, and the what-if comes back empty (seen 2026-09-14).
            state = self.ib.whatIfOrder(info.contract, MarketOrder(side.upper(), qty, tif="GTC"))
        except Exception as exc:  # noqa: BLE001 — unknown margin is None; the gate rejects
            log.warning("whatIf failed for %s: %s", info.local_symbol, exc)
            return None
        return _dec(getattr(state, "initMarginChange", None))

    def available_funds(self) -> Decimal | None:
        for v in self.ib.accountValues():
            if v.tag == "AvailableFunds" and v.currency not in ("BASE", ""):
                return _dec(v.value)
        return None

    def net_liquidation(self) -> Decimal | None:
        for v in self.ib.accountValues():
            if v.tag == "NetLiquidation" and v.currency not in ("BASE", ""):
                return _dec(v.value)
        return None

    def daily_pnl(self) -> Decimal | None:
        return _dec(getattr(self._pnl, "dailyPnL", None)) if self._pnl is not None else None

    # -- positions -----------------------------------------------------------

    def positions(self) -> list[dict[str, Any]]:
        out = []
        for p in self.ib.positions():
            if p.account != self.account or not p.position:
                continue
            c = p.contract
            mult = _dec(c.multiplier) or Decimal(1)
            con = int(c.conId)
            pnl = self._pnl_single.get(con)
            if pnl is None:
                pnl = self._pnl_single[con] = self.ib.reqPnLSingle(self.account, "", con)
            out.append({
                "con_id": con, "local_symbol": c.localSymbol or c.symbol, "root": c.symbol,
                "exchange": c.exchange or c.primaryExchange, "contract_month": c.lastTradeDateOrContractMonth,
                "sec_type": c.secType, "qty": int(p.position), "multiplier": mult,
                "avg_price": (_dec(p.avgCost) or Decimal(0)) / mult,
                "unrealized_pnl": _dec(pnl.unrealizedPnL), "realized_pnl": _dec(pnl.realizedPnL),
                "daily_pnl": _dec(pnl.dailyPnL), "value": _dec(pnl.value),
            })
        return out

    def position_qty(self, con_id: int) -> int:
        return sum(p["qty"] for p in self.positions() if p["con_id"] == con_id)

    # -- orders --------------------------------------------------------------

    def open_orders(self) -> list[dict[str, Any]]:
        return [self._view(t) for t in self.ib.openTrades()]

    def place(self, info: ContractInfo, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Place one order or a bracket. ``specs`` are parent-first; children name
        their parent by ``parent_ref``. Only the last order transmits, so IBKR
        receives the group whole or not at all."""
        from ib_async import Order

        ids: dict[str, int] = {}
        trades = []
        for i, spec in enumerate(specs):
            order = Order(
                action=spec["side"].upper(), totalQuantity=spec["qty"],
                orderType={"market": "MKT", "limit": "LMT", "stop": "STP", "trail": "TRAIL"}[spec["type"]],
                orderRef=spec["ref"], tif=spec.get("tif", "GTC"), outsideRth=True,
                # Hold only a parent (or a child) with more of its bracket still
                # to come. Independent orders each transmit: holding one because
                # it is not last in the list leaves it unsent at the gateway,
                # which is how a stop went missing on 2026-09-14.
                transmit=_transmits(specs, i),
            )
            order.orderId = self.ib.client.getReqId()
            ids[spec["ref"]] = order.orderId
            if spec.get("limit") is not None:
                order.lmtPrice = float(spec["limit"])
            if spec["type"] == "stop":
                order.auxPrice = float(spec["stop"])
            if spec["type"] == "trail":
                order.auxPrice = float(spec["trail"])
                if spec.get("stop") is not None:
                    order.trailStopPrice = float(spec["stop"])
            if spec.get("parent_ref"):
                order.parentId = ids[spec["parent_ref"]]
            if spec.get("oca"):
                order.ocaGroup, order.ocaType = spec["oca"], 1
            trades.append(self.ib.placeOrder(info.contract, order))
        self.ib.sleep(0.3)
        return [self._view(t) for t in trades]

    def _trade(self, ref: str) -> Any:
        for t in self.ib.openTrades():
            if t.order.orderRef == ref:
                return t
        raise DegradedError(f"no working order {ref}")

    def modify(self, ref: str, *, limit: Decimal | None = None, stop: Decimal | None = None,
               trail: Decimal | None = None, qty: int | None = None) -> dict[str, Any]:
        t = self._trade(ref)
        if t.order.clientId != self.client_id:
            raise DegradedError(f"{ref} belongs to client {t.order.clientId}; IBKR lets only that client change it")
        o = t.order
        if limit is not None:
            o.lmtPrice = float(limit)
        if stop is not None:
            if o.orderType == "TRAIL":
                o.trailStopPrice = float(stop)
            else:
                o.auxPrice = float(stop)
        if trail is not None:
            o.auxPrice = float(trail)
        if qty is not None:
            o.totalQuantity = qty
        o.transmit = True
        self.ib.placeOrder(t.contract, o)
        self.ib.sleep(0.2)
        return self._view(t)

    def cancel(self, ref: str) -> None:
        """Idempotent. An order already gone -- filled, or cancelled with its OCA
        group or parent -- is not an error: a flatten that raised here would
        stop before sending the close."""
        try:
            t = self._trade(ref)
        except DegradedError:
            return
        if t.orderStatus.status in WORKING and t.orderStatus.status != "PendingCancel":
            self.ib.cancelOrder(t.order)

    # -- events --------------------------------------------------------------

    def _on_error(self, req_id: int, code: int, message: str, *_: Any) -> None:
        if req_id > 0 and code not in (399, 2104, 2106, 2158):
            self._errors[req_id] = f"{code}: {message}"

    #: True while an ib_async event is being dispatched. A handler must not
    #: make a blocking IB call then -- ``ib.sleep`` inside the running loop
    #: raises "This event loop is already running", after the order has
    #: already been sent (seen 2026-09-14). The order manager defers on it.
    in_callback = False

    def _on_trade(self, trade: Any) -> None:
        if trade.order.orderRef:
            self.in_callback = True
            try:
                self.on_status(self._view(trade))
            finally:
                self.in_callback = False

    def _on_commission(self, trade: Any, fill: Any, report: Any) -> None:
        self.in_callback = True
        try:
            self._emit_fill(trade, fill, _dec(report.commission))
        finally:
            self.in_callback = False

    def _emit_fill(self, trade: Any, fill: Any, fee: Decimal | None) -> None:
        e = fill.execution
        if e.execId in self._fill_seen:
            return
        self._fill_seen.add(e.execId)
        self.on_fill(self.fill_row(trade.contract, e, fee))

    @staticmethod
    def fill_row(contract: Any, e: Any, fee: Decimal | None) -> dict[str, Any]:
        when = e.time if isinstance(e.time, datetime) else datetime.now(UTC)
        return {
            "exec_id": e.execId, "ref": e.orderRef, "perm_id": e.permId, "con_id": int(contract.conId),
            "side": "buy" if e.side in ("BOT", "BUY") else "sell", "qty": int(e.shares),
            "price": Decimal(str(e.price)), "fee": fee if fee is not None else Decimal(0),
            "fee_known": fee is not None, "venue": e.exchange,
            "ts": when.astimezone(UTC).isoformat(), "client_id": e.clientId,
        }

    def executions(self) -> list[dict[str, Any]]:
        """Today's executions for the account, all clients -- for reconciliation."""
        out = []
        for f in self.ib.reqExecutions():
            report = f.commissionReport
            fee = _dec(report.commission) if report and report.execId else None
            out.append(self.fill_row(f.contract, f.execution, fee))
        return out

    def _view(self, t: Any) -> dict[str, Any]:
        o, s, c = t.order, t.orderStatus, t.contract
        stop = _dec(o.trailStopPrice) if o.orderType == "TRAIL" else _dec(o.auxPrice) if o.orderType == "STP" else None
        return {
            "ref": o.orderRef, "order_id": o.orderId, "perm_id": o.permId, "client_id": o.clientId,
            "con_id": int(c.conId), "local_symbol": c.localSymbol, "side": o.action.lower(),
            "qty": int(o.totalQuantity), "filled": float(s.filled), "remaining": float(s.remaining),
            "avg_fill_price": _dec(s.avgFillPrice) if s.filled else None,
            "type": _TYPES.get(o.orderType, o.orderType.lower()), "limit": _dec(o.lmtPrice),
            "stop": stop, "trail": _dec(o.auxPrice) if o.orderType == "TRAIL" else None,
            "parent_id": o.parentId, "oca": o.ocaGroup, "status": s.status,
            "state": status_to_state(s.status, s.filled, s.remaining),
            "working": s.status in WORKING, "error": self._errors.get(o.orderId),
        }
