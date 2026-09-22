# Spec: Genesis Markdown/50-Risk/Kill Switch.md
"""The kill switch. A separate process that works when everything else is broken.

    python -m genesis.execution.killswitch          # or: genesis killswitch serve

No LLM, no bus, no daemon. It holds its own IBKR connection (its own client
id), a loopback HTTP endpoint the UI's kill button calls directly, and the halt
flag file the order manager obeys.

**Why halt has two stages.** IBKR lets only the client that placed an order
cancel it; this process can see the order manager's orders but not cancel them
(error 10147, verified 2026-09-13). So ``halt``:

1. raises the flag -- the order manager, if alive, cancels its own entries
   within one tick and leaves every exit order (stops and targets) on an
   open position alone;
2. within 0.9 s looks at the broker itself. If a non-exit order is still
   working, the daemon is not doing its job, and it escalates: note every
   protective stop, ``reqGlobalCancel`` (which does cross clients), and
   re-place those stops under its own client id at once.

The escalation has a sub-second window without stops. It exists for the case
where the alternative is a wedged daemon with live entries, and it says so in
its response rather than reporting a clean halt.

``flatten`` raises the flag, global-cancels, closes every position at market
and verifies flat. Only this process closes positions on a flatten; the order
manager only cancels, so the two can never both sell.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from concurrent.futures import Future
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from genesis.execution import halt

__all__ = ["KillSwitch", "main"]

log = logging.getLogger("genesis.killswitch")

WORKING = {"PendingSubmit", "ApiPending", "PreSubmitted", "Submitted"}
ALLOWED_ORIGIN = ("http://localhost", "http://127.0.0.1")


class KillSwitch:
    def __init__(self, *, state_dir: Path, host: str, port: int, client_id: int) -> None:
        self.halt_path = halt.path_for(state_dir)
        self.host, self.port, self.client_id = host, port, client_id
        self.ib: Any = None
        self._jobs: queue.Queue[tuple[Callable[[], Any], Future[Any]]] = queue.Queue()
        self._lock = threading.Lock()  # idempotent under concurrent triggers
        self._thread = threading.Thread(target=self._worker, name="killswitch-ib", daemon=True)

    # -- the IB thread -------------------------------------------------------

    def start(self) -> None:
        self._thread.start()

    def _connect(self) -> None:
        from ib_async import IB

        ib = IB()
        ib.connect(self.host, self.port, clientId=self.client_id, timeout=10, readonly=False)
        ib.reqAllOpenOrders()
        self.ib = ib
        log.info("kill switch connected to %s:%s as client %s", self.host, self.port, self.client_id)

    def _worker(self) -> None:
        while True:
            try:
                if self.ib is None or not self.ib.isConnected():
                    self.ib = None
                    self._connect()
                self.ib.sleep(0.1)
            except Exception as exc:  # noqa: BLE001 — keep trying; the flag still works without it
                log.warning("kill switch broker connection: %s", exc)
                self.ib = None
                time.sleep(2)
            while True:
                try:
                    fn, fut = self._jobs.get_nowait()
                except queue.Empty:
                    break
                try:
                    fut.set_result(fn())
                except BaseException as exc:  # noqa: BLE001
                    fut.set_exception(exc)

    def _on_ib(self, fn: Callable[[], Any], timeout: float = 10) -> Any:
        fut: Future[Any] = Future()
        self._jobs.put((fn, fut))
        return fut.result(timeout=timeout)

    # -- actions -------------------------------------------------------------

    def fire(self, level: str, trigger: str) -> dict[str, Any]:
        started = time.monotonic()
        with self._lock:
            doc = halt.engage(self.halt_path, level=level, trigger=trigger)
            out: dict[str, Any] = {"ok": True, "halt": {k: doc.get(k) for k in ("id", "level", "trigger", "at")},
                                   "flag_raised_ms": round((time.monotonic() - started) * 1000, 1)}
            if self.ib is None:
                out.update(ok=False, broker="unreachable",
                           detail="halt flag raised; the kill switch has no broker connection, so broker "
                                  "state is NOT verified. Check IBKR directly.")
                return out
            try:
                if doc.get("level") == "flatten":
                    out.update(self._on_ib(lambda: self._flatten(doc["id"])))
                else:
                    out.update(self._on_ib(lambda: self._verify_halt(doc["id"])))
            except Exception as exc:  # noqa: BLE001 — say it failed, loudly
                out.update(ok=False, detail=f"flag raised, broker step failed: {exc}")
            out["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
            log.warning("kill switch %s: %s", level, json.dumps(out, default=str))
            return out

    def _open(self) -> list[Any]:
        """Working orders, from a fresh request -- never from the cache.

        IBKR does not tell this client when another client's order is
        cancelled, so ``ib.openTrades()`` keeps showing the order manager's
        cancelled orders as Submitted. Judging by that cache made the kill
        switch escalate against a daemon that had done its job, and its global
        cancel took the protective stop with it (seen 2026-09-14). The
        request's own return value is current, in about 5 ms.
        """
        return [t for t in self.ib.reqAllOpenOrders() if t.orderStatus.status in WORKING]

    def _exit(self, t: Any, trades: list[Any]) -> bool:
        """An order that can only reduce a position: opposite side to what the
        account holds, and not the child of an entry still waiting to fill.
        The order manager keeps these on a halt; so does this check."""
        held = {p.contract.conId: p.position for p in self.ib.positions()}
        pos = held.get(t.contract.conId, 0)
        unfilled_parents = {x.order.orderId for x in trades if x.orderStatus.filled == 0}
        reduces = pos > 0 and t.order.action == "SELL" or pos < 0 and t.order.action == "BUY"
        return bool(reduces) and t.order.parentId not in unfilled_parents

    def _verify_halt(self, halt_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 0.9
        self.ib.sleep(0.15)  # one order-manager tick, and IBKR's cancel acknowledgement
        trades = self._open()
        while time.monotonic() < deadline and any(not self._exit(t, trades) for t in trades):
            self.ib.sleep(0.1)
            trades = self._open()
        rogue = [t for t in trades if not self._exit(t, trades)]
        if not rogue:
            stops = sum(t.order.orderType in ("STP", "TRAIL") for t in trades)
            return {"verified": True, "working_exit_orders": len(trades),
                    "detail": f"halted; entries cancelled, {stops} stop(s) and "
                              f"{len(trades) - stops} target(s) still protecting positions"}
        stops = [(t.contract, t.order) for t in trades
                 if self._exit(t, trades) and t.order.orderType in ("STP", "TRAIL")]
        self.ib.reqGlobalCancel()
        self.ib.sleep(0.5)
        replaced = self._replace_stops(halt_id, stops)
        left = [t for t in self._open() if not t.order.orderRef.startswith("kill_")]
        return {"verified": not left, "escalated": True, "rogue_orders": len(rogue), "stops_replaced": replaced,
                "detail": f"order manager did not cancel {len(rogue)} order(s) in time — global cancel sent and "
                          f"{replaced} protective stop(s) re-placed by the kill switch"
                          + ("" if not left else f"; {len(left)} order(s) STILL working")}

    def _replace_stops(self, halt_id: str, stops: list[tuple[Any, Any]]) -> int:
        from ib_async import Order

        n = 0
        for contract, old in stops:
            n += 1
            o = Order(action=old.action, totalQuantity=old.totalQuantity, orderType=old.orderType,
                      auxPrice=old.auxPrice, trailStopPrice=old.trailStopPrice, tif="GTC",
                      orderRef=f"kill_{halt_id}_stop{n}", outsideRth=True)
            self.ib.placeOrder(contract, o)
        return n

    def _flatten(self, halt_id: str) -> dict[str, Any]:
        from ib_async import MarketOrder

        self.ib.reqGlobalCancel()
        self.ib.sleep(0.5)
        closes = []
        from ib_async import Contract

        for n, p in enumerate([p for p in self.ib.positions() if p.position], start=1):
            # A position's contract carries no exchange, and futures cannot route
            # SMART -- the close was rejected and nothing closed (2026-09-14).
            # Qualify by contract id instead.
            contract = Contract(conId=p.contract.conId)
            if not self.ib.qualifyContracts(contract):
                closes.append(f"COULD NOT RESOLVE {p.contract.localSymbol} (conId {p.contract.conId})")
                continue
            action = "SELL" if p.position > 0 else "BUY"
            self.ib.placeOrder(contract, MarketOrder(action, abs(p.position), orderRef=f"kill_{halt_id}_{n}",
                                                     tif="DAY", outsideRth=True))
            closes.append(f"{action} {abs(p.position)} {contract.localSymbol}")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and any(p.position for p in self.ib.positions()):
            self.ib.sleep(0.2)
        left = [f"{p.position} {p.contract.localSymbol}" for p in self.ib.positions() if p.position]
        return {"verified": not left, "closes": closes, "still_open": left,
                "detail": "flattened" if not left else f"close orders sent, NOT yet flat: {', '.join(left)}"}

    def status(self) -> dict[str, Any]:
        try:
            doc = halt.read(self.halt_path)
        except halt.HaltUnreadable as exc:
            doc = {"engaged": True, "detail": str(exc)}
        return {"ok": True, "broker_connected": bool(self.ib and self.ib.isConnected()),
                "halt": {k: doc.get(k) for k in ("engaged", "level", "trigger", "at", "id")},
                "as_of": datetime.now(UTC).isoformat()}


def _handler(ks: KillSwitch) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body, default=str).encode()
            self.send_response(code)
            origin = self.headers.get("Origin", "")
            if origin.startswith(ALLOWED_ORIGIN):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "content-type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(204, {})

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, ks.status())
            else:
                self._send(404, {"ok": False, "reason": "GET /health, POST /halt, POST /flatten"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                body = {}
            reason = str(body.get("reason") or "operator")[:200]
            if self.path == "/halt":
                self._send(200, ks.fire("halt", reason))
            elif self.path == "/flatten":
                self._send(200, ks.fire("flatten", reason))
            else:
                self._send(404, {"ok": False, "reason": "POST /halt or /flatten"})

        def log_message(self, fmt: str, *args: Any) -> None:
            log.info("%s %s", self.address_string(), fmt % args)

    return Handler


def main() -> None:
    from genesis.config import load_config

    logging.basicConfig(level=logging.INFO, format="%(asctime)s killswitch %(levelname)s %(message)s")
    config = load_config()
    ibkr = config.marketdata.adapters.get("ibkr")
    ex = config.execution
    ks = KillSwitch(state_dir=ex.state_dir, host=(ibkr.host if ibkr else None) or "127.0.0.1",
                    port=(ibkr.port if ibkr else None) or 4002, client_id=ex.killswitch_client_id)
    ks.start()
    server = ThreadingHTTPServer(("127.0.0.1", ex.killswitch_port), _handler(ks))
    log.info("kill switch listening on http://127.0.0.1:%s", ex.killswitch_port)
    server.serve_forever()


if __name__ == "__main__":
    main()
