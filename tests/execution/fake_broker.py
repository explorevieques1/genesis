# Spec: Genesis Markdown/20-Agents/Execution/Agent — Broker Adapter.md
"""An in-memory IbkrBroker with the behaviour the paper gateway showed on 2026-09-13:
brackets, children that activate on the parent's fill, cancels that cascade to
children, and positions that follow fills."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

from genesis.execution.ibkr_broker import ContractInfo


def hours_around(now: datetime) -> str:
    start = (now - timedelta(hours=2)).astimezone(UTC)
    end = (now + timedelta(hours=2)).astimezone(UTC)
    return f"{start:%Y%m%d:%H%M}-{end:%Y%m%d:%H%M}"


class FakeBroker:
    host, port, client_id = "127.0.0.1", 4002, 30

    def __init__(self) -> None:
        self.account: str | None = None
        self.up = False
        self.orders: list[dict[str, Any]] = []
        self.pos: dict[int, tuple[int, D]] = {}
        self.fills: list[dict[str, Any]] = []
        self.placed: list[dict[str, Any]] = []
        self.mid = D("29365.25")
        self.pnl = D(0)
        self.margin = D(30000)
        self.fail_place = False
        #: Fill market orders inside place(), the way IBKR paper does.
        self.fill_market_on_place = False
        self.in_callback = False
        self.next_id = 100
        self.on_status = lambda v: None
        self.on_fill = lambda f: None
        now = datetime.now(UTC)
        self.info = ContractInfo(symbol_id="FUT:CME:NQ:2026-12", root="NQ", local_symbol="NQZ6", con_id=555,
                                 multiplier=D(20), min_tick=D("0.25"), trading_hours=hours_around(now),
                                 time_zone="UTC", contract=None)

    # lifecycle
    def connected(self) -> bool:
        return self.up

    def connect(self) -> str:
        self.up, self.account = True, "DU123"
        return self.account

    def disconnect(self) -> None:
        self.up = False

    def pump(self, seconds: float) -> None:
        pass


    # contracts
    def qualify(self, symbol_id: str) -> ContractInfo:
        assert symbol_id == self.info.symbol_id, symbol_id
        return self.info

    def info_for_con(self, con_id: int) -> ContractInfo | None:
        return self.info if con_id == self.info.con_id else None

    def quote(self, info: ContractInfo) -> dict[str, Any]:
        return {"bid": self.mid - D("0.25"), "ask": self.mid + D("0.25"), "last": self.mid, "mid": self.mid,
                "source": "delayed", "ts": datetime.now(UTC).isoformat()}

    def what_if_margin(self, info, side, qty):
        return self.margin * qty

    def available_funds(self):
        return D(1_000_000)

    def daily_pnl(self):
        return self.pnl

    def net_liquidation(self):
        return D(1_000_000)

    # positions
    def positions(self) -> list[dict[str, Any]]:
        return [{"con_id": c, "local_symbol": "NQZ6", "root": "NQ", "exchange": "CME", "contract_month": "202612",
                 "sec_type": "FUT", "qty": q, "multiplier": D(20), "avg_price": avg, "unrealized_pnl": None,
                 "realized_pnl": None, "daily_pnl": None, "value": None}
                for c, (q, avg) in self.pos.items() if q]

    def position_qty(self, con_id: int) -> int:
        return self.pos.get(con_id, (0, D(0)))[0]

    # orders
    def _view(self, o: dict[str, Any]) -> dict[str, Any]:
        return dict(o)

    def open_orders(self) -> list[dict[str, Any]]:
        return [self._view(o) for o in self.orders]

    def place(self, info: ContractInfo, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        assert not self.in_callback, "place() inside an IB callback: This event loop is already running"
        if self.fail_place:
            raise RuntimeError("201: Order rejected")
        ids: dict[str, int] = {}
        out = []
        for spec in specs:
            self.next_id += 1
            ids[spec["ref"]] = self.next_id
            parent = ids.get(spec.get("parent_ref") or "", 0)
            o = {"ref": spec["ref"], "order_id": self.next_id, "perm_id": 9000 + self.next_id,
                 "client_id": self.client_id, "con_id": info.con_id, "local_symbol": info.local_symbol,
                 "side": spec["side"], "qty": spec["qty"], "filled": 0.0, "remaining": float(spec["qty"]),
                 "avg_fill_price": None, "type": spec["type"], "limit": spec.get("limit"),
                 "stop": spec.get("stop"), "trail": spec.get("trail"), "parent_id": parent,
                 "oca": spec.get("oca") or "", "status": "PreSubmitted" if parent else "Submitted",
                 "state": "accepted", "working": True, "error": None}
            self.orders.append(o)
            self.placed.append(spec)
            out.append(o)
        if self.fill_market_on_place:
            for o in [o for o in out if o["type"] == "market" and not o["parent_id"]]:
                self.fill(o["ref"], self.mid)
        return [dict(o) for o in out]

    def _find(self, ref: str) -> dict[str, Any]:
        return next(o for o in self.orders if o["ref"] == ref and o["working"])

    def modify(self, ref, *, limit=None, stop=None, trail=None, qty=None):
        assert not self.in_callback, "modify() inside an IB callback"
        o = self._find(ref)
        if o["parent_id"] and o["oca"]:
            # IBKR 10326: a bracket child with an explicit OCA group cannot be revised.
            o.update(status="Cancelled", state="cancelled", working=False)
            raise RuntimeError("10326: OCA group revision is not allowed")
        for k, v in (("limit", limit), ("stop", stop), ("trail", trail)):
            if v is not None:
                o[k] = v
        if qty is not None:
            o["qty"], o["remaining"] = qty, float(qty)
        return dict(o)

    def cancel(self, ref: str) -> None:
        if not any(o["ref"] == ref and o["working"] for o in self.orders):
            return
        o = self._find(ref)
        # A parent takes its children; an OCA member takes its whole group (IBKR, 2026-09-14).
        group = [c for c in self.orders if c["working"] and (c["parent_id"] == o["order_id"]
                                                              or (o["oca"] and c["oca"] == o["oca"]))]
        for x in [o] + [c for c in group if c is not o]:
            x.update(status="Cancelled", state="cancelled", working=False)
            self.on_status(dict(x))

    # driving the fake from a test
    def fill(self, ref: str, price: D) -> None:
        o = self._find(ref)
        qty = int(o["remaining"])
        o.update(filled=float(qty), remaining=0.0, avg_fill_price=price, status="Filled", state="filled", working=False)
        signed = qty if o["side"] == "buy" else -qty
        held, avg = self.pos.get(o["con_id"], (0, D(0)))
        new = held + signed
        self.pos[o["con_id"]] = (new, price if held == 0 or (held > 0) != (new > 0) else avg)
        for c in self.orders:
            if c["parent_id"] == o["order_id"] and c["working"]:
                c["status"] = "Submitted"
        # Siblings: native bracket children (same parent) and members of an OCA group.
        for c in self.orders:
            if c is o or not c["working"]:
                continue
            same_bracket = o["parent_id"] and c["parent_id"] == o["parent_id"]
            same_group = o["oca"] and c["oca"] == o["oca"]
            if same_bracket or same_group:
                c.update(status="Cancelled", state="cancelled", working=False)
        fill = {"exec_id": f"exec_{len(self.fills) + 1}", "ref": ref, "perm_id": o["perm_id"], "con_id": o["con_id"],
                "side": o["side"], "qty": qty, "price": price, "fee": D("2.25"), "fee_known": True, "venue": "CME",
                "ts": datetime.now(UTC).isoformat(), "client_id": self.client_id}
        self.fills.append(fill)
        # Delivered the way ib_async delivers them: inside a dispatch, where a
        # blocking broker call is not allowed.
        self.in_callback = True
        try:
            self.on_status(dict(o))
            self.on_status(dict(o))  # IBKR repeats the Filled status
            self.on_fill(fill)
        finally:
            self.in_callback = False

    def executions(self) -> list[dict[str, Any]]:
        return list(self.fills)
