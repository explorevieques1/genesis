# Spec: Genesis Markdown/20-Agents/Execution/Agent — Order Manager.md
"""Agent — Order Manager. The lifecycle of every order, and the only caller of
the broker.

One thread owns the IBKR order connection, the ledger handle and the approval
book. Everything else -- HTTP routes, the UI -- hands it work through
:meth:`call` and waits for the answer. That is not only ``ib_async``'s thread
rule; it also means two clicks can never interleave inside a placement.

What it guarantees, and where:

- **No order without an approval.** :meth:`_execute` is the one place
  ``broker.place`` is called, and it takes a redeemed :class:`Approval`. The
  ledger's ``approval_id NOT NULL`` is the second statement of the same rule.
- **Every order is in the ledger before it is at the broker.** A crash between
  the two leaves a ``new`` order the broker never saw -- recoverable. The other
  order would leave a broker order nobody can account for.
- **Never blind-retry.** A placement that raises is recorded as rejected and
  reported. The trader proposes again.
- **Restart adopts, never re-places.** Orders live at IBKR as GTC orders under
  a fixed client id; on reconnect they come back and :meth:`_reconcile` matches
  them to the ledger by ``orderRef``.
- **No unprotected position.** :meth:`_protect` closes any position the ledger
  holds that has had no working stop for ``protective_grace_sec``.
- **Halt is honoured without asking anyone.** :meth:`_watch_halt` reads the
  kill switch's flag file every tick.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import queue
import threading
import time
import urllib.request
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import yaml

from genesis.agents.execution.accountant import Accountant
from genesis.config import Config
from genesis.errors import GenesisError, TransientError
from genesis.execution import halt
from genesis.execution.approval import Approval, ApprovalBook, ApprovalError
from genesis.execution.ibkr_broker import ContractInfo, IbkrBroker, in_session, round_to_tick
from genesis.execution.risk import Decision, Proposal, RiskContext, evaluate, fingerprint
from genesis.ids import new_id, new_trace_id
from genesis.memory.ledger import Fill, TradeLedger

__all__ = ["OrderManager", "current", "start", "stop"]

log = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], None]
RETRY_SEC = 15.0
RECONCILE_SEC = 60.0
QUIET_SEC = 5.0
AUTONOMY = {"advisory": 0, "confirm": 1, "auto-within-limits": 2}


class Refused(GenesisError):
    """A request the order manager declines, with the reason for the trader."""


def _s(value: Any) -> str | None:
    return None if value is None else str(value)


def _money(value: Any, name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise Refused(f"{name} is not a number: {value!r}") from exc


class OrderManager:
    def __init__(self, config: Config, emit: Emit, *, broker: Any | None = None,
                 threaded: bool = True, clock: Callable[[], datetime] | None = None,
                 live_config: Any | None = None) -> None:
        self.config = config
        #: The risk envelope, re-read per proposal. A limit you must restart to
        #: tighten is one you will not tighten in a drawdown -- see
        #: :class:`~genesis.config.LiveConfig`. Everything else on ``config``
        #: is still boot-time state.
        self.live_config = live_config
        self.emit = emit
        ex = config.execution
        ibkr = config.marketdata.adapters.get("ibkr")
        self.broker = broker or IbkrBroker(
            host=(ibkr.host if ibkr else None) or "127.0.0.1", port=(ibkr.port if ibkr else None) or 4002,
            client_id=ex.client_id, market_data_type=(ibkr.market_data_type if ibkr else None) or "delayed",
        )
        self.broker.on_status = self._on_status
        self.broker.on_fill = self._on_fill
        self.threaded = threaded
        self.clock = clock or (lambda: datetime.now(UTC))
        self.state_dir = Path(ex.state_dir)
        self.halt_path = halt.path_for(self.state_dir)
        self.book = ApprovalBook(config.approval.confirmation_ttl_sec, clock=self.clock)
        self.mode = config.approval.mode
        self.ledger: TradeLedger | None = None
        self.quality: Any = None
        self.accountant: Any = None
        self._proposals: dict[str, Proposal] = {}
        self._pending: dict[str, dict[str, Any]] = {}
        self._recent: dict[str, float] = {}
        self._unprotected: dict[int, float] = {}
        self._flattening: dict[int, float] = {}
        self._adverse: list[tuple[float, str, int]] = []
        self._halt_seen: str | None = None
        self._halt_level: str | None = None
        self._recon: dict[str, Any] = {"matched": None, "detail": "not run yet", "at": None}
        self._status: dict[str, Any] = {"state": "starting", "detail": "", "since": self.clock().isoformat()}
        self._last_activity = 0.0
        self._killswitch_ok = False
        self._published: str | None = None
        #: Broker work a callback asked for, run once the callback has returned.
        self._deferred: list[Callable[[], None]] = []
        self._queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], cf.Future[Any]]] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="order-manager", daemon=True)
        self._ks_thread = threading.Thread(target=self._ping_killswitch, name="killswitch-ping", daemon=True)

    # ------------------------------------------------------------------
    # lifecycle and the thread boundary
    # ------------------------------------------------------------------

    @property
    def account(self) -> str:
        return self.broker.account or "unknown"

    def start(self) -> None:
        self._thread.start()
        self._ks_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def call(self, fn: Callable[..., Any], *args: Any, timeout: float = 30.0) -> Any:
        """Run ``fn`` on the order thread and return its result, or raise its error."""
        if not self.threaded:
            return fn(*args)
        if not self.broker.connected() or self.ledger is None:
            raise Refused(f"the order connection is {self._status['state']}: {self._status['detail'] or 'not up'}")
        fut: cf.Future[Any] = cf.Future()
        self._queue.put((fn, args, fut))
        return fut.result(timeout=timeout)

    def open(self) -> None:
        """Connect, open the stores, reconcile. On the order thread (or inline in tests)."""
        from genesis.agents.execution.execution_quality import QualityStore

        if self.config.brokers.primary.mode != "paper":
            raise Refused("brokers.primary.mode is not paper — the order path runs on paper only")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.ledger is None:
            self.ledger = TradeLedger(self.state_dir / "ledger.db")
            self.quality = QualityStore(self.state_dir / "quality.db")
            # Nothing computes its own idea of a position: the accountant is
            # the derivation, this manager keeps the halt. Biological Design
            # §3 -- the sense belongs beside the muscle, not inside it.
            self.accountant = Accountant(
                ledger=self.ledger, broker=self.broker, quote=self._mark,
                symbol_for_con=self._symbol_for_con, clock=self.clock,
            )
        self._set_status("connecting", f"{getattr(self.broker, 'host', '')}:{getattr(self.broker, 'port', '')}")
        self.broker.connect()
        self._set_status("reconciling", f"account {self.account}")
        self._reconcile(force=True)
        self._set_status("live", f"account {self.account} · client {getattr(self.broker, 'client_id', '')}")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.open()
                self.tick_forever()
            except Exception as exc:  # noqa: BLE001 — a dead gateway is expected, not fatal
                log.warning("order manager session ended: %s", exc)
                self._set_status("down", getattr(exc, "reason", None) or str(exc))
                if self.ledger is not None and self._ledger_positions():
                    self.emit("execution.fatal", {"reason": "broker unreachable with open positions",
                                                  "detail": str(exc)})
                self._publish(force=True)
            finally:
                self.broker.disconnect()
            self._stop.wait(RETRY_SEC)

    def tick_forever(self) -> None:
        last_second = last_recon = time.monotonic()
        while not self._stop.is_set():
            self.pump(0.05)
            self._drain()
            if not self.broker.connected():
                raise TransientError("gateway disconnected")
            self._watch_halt()
            now = time.monotonic()
            if now - last_second >= 1.0:
                last_second = now
                self.tick_second()
            if now - last_recon >= RECONCILE_SEC:
                last_recon = now
                self._reconcile()

    def tick_second(self) -> None:
        self._protect()
        self._sample_adverse()
        self._publish()

    def pump(self, seconds: float) -> None:
        """Let IBKR's events in, then run whatever they asked for."""
        self.broker.pump(seconds)
        self._run_deferred()

    def _defer_or_run(self, fn: Callable[[], None]) -> None:
        if getattr(self.broker, "in_callback", False):
            self._deferred.append(fn)
        else:
            fn()

    def _run_deferred(self) -> None:
        while self._deferred and not getattr(self.broker, "in_callback", False):
            fn = self._deferred.pop(0)
            try:
                fn()
            except Exception:  # noqa: BLE001 — one failed follow-up must not drop the rest
                log.exception("deferred order work failed")

    def _drain(self) -> None:
        while True:
            try:
                fn, args, fut = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                fut.set_result(fn(*args))
            except BaseException as exc:  # noqa: BLE001 — the caller re-raises it
                fut.set_exception(exc)

    def _ping_killswitch(self) -> None:
        url = f"http://127.0.0.1:{self.config.execution.killswitch_port}/health"
        while not self._stop.is_set():
            try:
                with urllib.request.urlopen(url, timeout=0.5) as r:  # noqa: S310 — loopback only
                    self._killswitch_ok = r.status == 200
            except Exception:  # noqa: BLE001
                self._killswitch_ok = False
            self._stop.wait(5)

    # ------------------------------------------------------------------
    # public API — every method runs on the order thread via call()
    # ------------------------------------------------------------------

    def propose(self, ticket: dict[str, Any]) -> dict[str, Any]:
        return self.call(self._propose_ticket, ticket)

    def dry_run(self, ticket: dict[str, Any]) -> dict[str, Any]:
        """What the gate would decide about this ticket. No approval, no order.

        The plan of action sizes ideas through *this*, so there is one sizing
        implementation in the system -- the gate's -- rather than a second one
        that agrees with it until the day it does not. Afferent: it mints no
        approval token, records nothing, and cannot place.
        """
        return self.call(self._dry_run, ticket)

    def place(self, approval_id: str, confirmation: dict[str, Any] | None) -> dict[str, Any]:
        return self.call(self._place, approval_id, confirmation, "dashboard")

    def submit(self, ticket: dict[str, Any]) -> dict[str, Any]:
        return self.call(self._submit, ticket)

    def modify(self, ref: str, changes: dict[str, Any]) -> dict[str, Any]:
        return self.call(self._modify, ref, changes)

    def cancel(self, ref: str) -> dict[str, Any]:
        return self.call(self._cancel, ref)

    def flatten(self, symbol_id: str, qty: int | None = None) -> dict[str, Any]:
        return self.call(self._flatten, symbol_id, qty, "human")

    def set_mode(self, mode: str, by: str) -> dict[str, Any]:
        # Not through call(): the mode is config, and must be settable while
        # the broker is down.
        return self._set_mode(mode, by)

    def resume(self, by: str, resolution: str) -> dict[str, Any]:
        return self.call(self._resume, by, resolution)

    def adopt(self, by: str) -> dict[str, Any]:
        return self.call(self._adopt, by)

    def snapshot(self) -> dict[str, Any]:
        if not self.threaded or (self.broker.connected() and self.ledger is not None):
            try:
                return self.call(self._state)
            except Exception:  # noqa: BLE001
                pass
        return self._state_offline()

    def quality_report(self, date: str | None = None) -> dict[str, Any]:
        return self.call(self._quality_report, date)

    # ------------------------------------------------------------------
    # propose / place
    # ------------------------------------------------------------------

    def _ticket_proposal(self, t: dict[str, Any], info: ContractInfo, quote: dict[str, Any]) -> Proposal:
        side = str(t.get("side", "")).lower()
        try:
            qty = int(t.get("qty", 0))
        except (TypeError, ValueError) as exc:
            raise Refused(f"qty is not a whole number: {t.get('qty')!r}") from exc
        if isinstance(t.get("qty"), float) and not float(t["qty"]).is_integer():
            raise Refused("qty is a whole number of contracts")
        stop = t.get("stop") or {}
        target = t.get("target") or {}
        intent = "reduce" if t.get("intent") == "close" else "open"
        now = self.clock().isoformat()
        return Proposal(
            id=new_id("ord_prop"), created=now, trace_id=str(t.get("trace_id") or new_trace_id()),
            symbol_id=info.symbol_id, root=info.root, local_symbol=info.local_symbol, con_id=info.con_id,
            multiplier=info.multiplier, min_tick=info.min_tick, side=side,  # type: ignore[arg-type]
            qty=qty, order_type=str(t.get("order_type", "market")),  # type: ignore[arg-type]
            intent=intent, origin=str(t.get("origin", "human")),
            limit_price=_money(t.get("limit_price"), "limit price"),
            stop_kind="none" if intent == "reduce" else str(stop.get("kind", "none")),  # type: ignore[arg-type]
            stop_offset=_money(stop.get("offset"), "stop offset"),
            stop_price=_money(stop.get("price"), "stop price"),
            trail_amount=_money(stop.get("trail"), "trail amount"),
            target_offset=_money(target.get("offset"), "target offset"),
            target_price=_money(target.get("price"), "target price"),
            tif="DAY" if str(t.get("tif", "GTC")).upper() == "DAY" else "GTC",
            arrival_mid=quote.get("mid"), arrival_bid=quote.get("bid"), arrival_ask=quote.get("ask"),
            arrival_ts=quote.get("ts"), arrival_source=quote.get("source"),
        )

    def _propose_ticket(self, t: dict[str, Any]) -> dict[str, Any]:
        symbol_id = str(t.get("symbol_id") or "")
        if not symbol_id:
            raise Refused("symbol_id is required — the chart's symbol")
        try:
            info = self.broker.qualify(symbol_id)
        except Exception as exc:  # noqa: BLE001
            raise Refused(f"IBKR could not resolve {symbol_id}: {exc}") from exc
        return self._propose(self._ticket_proposal(t, info, self.broker.quote(info)), info)

    def _dry_run(self, t: dict[str, Any]) -> dict[str, Any]:
        """Evaluate as if the session were open and nothing were halted.

        A plan is usually made before the open, and a gate that stops at
        "not trading now" says nothing about *how much* it would allow once it
        is. So the session, the halt and the mode are lifted for the sizing and
        reported beside it as they are right now -- the plan shows both, and
        never presents the lifted answer as the current one.
        """
        symbol_id = str(t.get("symbol_id") or "")
        if not symbol_id:
            raise Refused("symbol_id is required")
        try:
            info = self.broker.qualify(symbol_id)
        except Exception as exc:  # noqa: BLE001
            raise Refused(f"IBKR could not resolve {symbol_id}: {exc}") from exc
        quote = self.broker.quote(info)
        p = self._ticket_proposal(t, info, quote)
        ctx = self._context(p, info)
        now = {"in_session": ctx.in_session, "halted": ctx.halted, "mode": ctx.mode}
        decision = evaluate(
            p, replace(ctx, in_session=True, halted=False, mode="confirm", recent={}),
            now=self.clock(),
        )
        return {
            "decision": decision.to_dict(), "now": now, "local_symbol": info.local_symbol,
            "multiplier": str(info.multiplier), "mark": _s(quote.get("mid")),
            "quote_source": quote.get("source"), "quote_ts": quote.get("ts"),
        }

    def _context(self, p: Proposal, info: ContractInfo) -> RiskContext:
        risk = self.envelope()
        try:
            doc = halt.read(self.halt_path)
            halted: bool | None = bool(doc["engaged"])
        except halt.HaltUnreadable:
            halted = None
        position = self.broker.position_qty(info.con_id)
        working = 0
        for v in self.broker.open_orders():
            order = self.ledger.order(self.account, v["ref"]) if v["ref"] else None
            if v["con_id"] == info.con_id and v["working"] and order and order["role"] == "entry":
                working += int(v["remaining"]) * (1 if v["side"] == "buy" else -1)
        margin = self.broker.what_if_margin(info, p.side, p.qty) if p.intent == "open" else None
        return RiskContext(
            mode="halt" if halted else self.mode, halted=halted,
            allowlist=tuple(risk.symbol_allowlist), max_contracts=risk.max_contracts_per_symbol,
            max_daily_loss_usd=risk.max_daily_loss_usd, max_price_deviation_pct=risk.max_price_deviation_pct,
            in_session=in_session(info.trading_hours, info.time_zone, self.clock()),
            position_qty=position, working_entry_qty=working, daily_pnl=self._daily_pnl(),
            available_funds=self.broker.available_funds(), init_margin_change=margin,
            recent=dict(self._recent), now_mono=time.monotonic(),
            broker_healthy=self.broker.connected(), killswitch_healthy=self._killswitch_ok,
            **self._heat_inputs(risk),
        )

    def _heat_inputs(self, risk: Any) -> dict[str, Any]:
        """Check #8's inputs, from the accountant -- never computed here.

        Any failure leaves them ``None``, and the risk engine rejects on
        ``None``: an accountant that could not answer is not a book with zero
        risk in it.
        """
        inputs: dict[str, Any] = {
            "equity": None, "open_risk": None,
            "max_portfolio_heat_pct": getattr(risk, "max_portfolio_heat_pct", None),
        }
        if self.accountant is None:
            return inputs
        try:
            snap = self.accountant.snapshot(account=self.account)
        except Exception:  # noqa: BLE001 - unknown heat rejects, it never passes
            log.exception("accountant snapshot failed; heat is unknown")
            return inputs
        inputs["equity"] = snap.equity
        inputs["open_risk"] = snap.open_risk
        return inputs

    def envelope(self) -> Any:
        """The risk limits in force *now*, not at boot.

        Read once per proposal and handed to one :class:`RiskContext`, so a
        reload between two checks of one decision is impossible.
        """
        if self.live_config is None:
            return self.config.risk
        try:
            return self.live_config.get().risk
        except Exception:  # noqa: BLE001 - the boot envelope is the fallback
            return self.config.risk

    def _session_start(self) -> datetime:
        """The CME trading day opens at 18:00 New York the evening before."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        ny = self.clock().astimezone(ZoneInfo("America/New_York"))
        start = ny.replace(hour=18, minute=0, second=0, microsecond=0)
        return (start if ny >= start else start - timedelta(days=1)).astimezone(UTC)

    def _daily_pnl(self) -> Decimal | None:
        """Today's P&L, from the broker.

        IBKR's own ``dailyPnL`` when it sends one. It sends nothing at all on an
        account with no activity yet (seen 2026-09-14), so the fallback is net
        liquidation now against the first snapshot this session -- still the
        broker's numbers, never the ledger's. The first snapshot of a session
        is taken on first use, which makes P&L before Genesis connected
        invisible to this check; stated in Risk Envelope.md.
        """
        pnl = self.broker.daily_pnl()
        if pnl is not None:
            return pnl
        now_liq = self.broker.net_liquidation()
        if now_liq is None:
            return None
        start = self._session_start().isoformat()
        row = self.ledger.connection.execute(
            "SELECT equity FROM equity_snapshots WHERE account_id = ? AND ts >= ? ORDER BY ts LIMIT 1",
            (self.account, start)).fetchone()
        if row is None:
            from genesis.memory.db import transaction

            with transaction(self.ledger.connection) as tx:
                tx.execute("INSERT INTO equity_snapshots (id, account_id, equity, cash, ts) VALUES (?,?,?,?,?)",
                           (new_id("eq"), self.account, str(now_liq), str(self.broker.available_funds() or 0),
                            self._now()))
            return Decimal(0)
        return now_liq - Decimal(row["equity"])

    def _propose(self, p: Proposal, info: ContractInfo) -> dict[str, Any]:
        decision = evaluate(p, self._context(p, info), now=self.clock())
        self.emit("order.proposed", {"proposal_id": p.id, "symbol": p.local_symbol, "side": p.side,
                                     "qty": str(p.qty), "limit_price": _s(p.limit_price), "proposed_by": p.origin})
        self._audit("proposal", {"proposal": _jsonable(p), "decision": decision.to_dict()})
        body: dict[str, Any] = {"proposal": _jsonable(p), "decision": decision.to_dict()}
        if not decision.approved:
            self.emit("order.rejected", {"proposal_id": p.id, "checks": _ui_checks(decision)})
            return {"ok": False, "reason": decision.spoken_summary, **body}
        approval = self.book.issue(p, decision, self.mode)
        self._proposals[p.id] = p
        self.emit("order.approved", {"proposal_id": p.id, "approval_id": approval.approval_id,
                                     "token_bound_to": f"{p.side} {approval.approved_qty} {p.local_symbol}",
                                     "checks": _ui_checks(decision)})
        return {"ok": True, **body, "approval": {
            "approval_id": approval.approval_id, "approved_qty": approval.approved_qty,
            "local_symbol": p.local_symbol, "worst_case_loss": approval.worst_case_loss,
            "requires_confirmation": approval.requires_confirmation,
            "expires_at": approval.expires_at.isoformat(),
        }}

    def _place(self, approval_id: str, confirmation: dict[str, Any] | None, method: str) -> dict[str, Any]:
        issued = self.book.get(approval_id)
        if issued is None:
            raise Refused("unknown approval — propose again")
        p = self._proposals.get(issued.proposal_id)
        if p is None:
            raise Refused("the proposal behind this approval is gone — propose again")
        try:
            engaged = halt.read(self.halt_path)["engaged"]
        except halt.HaltUnreadable:
            engaged = True
        if engaged and p.intent != "reduce":
            raise Refused("kill switch engaged since this was approved — nothing was placed")
        try:
            approval = self.book.redeem(approval_id, issued.signature, p.binds(issued.approved_qty), confirmation)
        except ApprovalError as exc:
            raise Refused(str(exc)) from exc
        return self._execute(p, approval, method, confirmation)

    def _submit(self, ticket: dict[str, Any]) -> dict[str, Any]:
        """One click: propose and place in one call -- only in auto-within-limits."""
        if self.mode != "auto-within-limits":
            raise Refused(f"one-click trading is off (mode {self.mode}) — confirm the proposal instead")
        proposed = self._propose_ticket({**ticket, "origin": "human"})
        if not proposed["ok"] or proposed["approval"]["requires_confirmation"]:
            return {**proposed, "placed": False}
        placed = self._place(proposed["approval"]["approval_id"], None, "auto")
        return {**proposed, **placed, "placed": True}

    def _client_order_id(self, p: Proposal) -> str:
        stamp = self.clock().strftime("%Y%m%d_%H%M%S")
        base = f"gen_{stamp}_{p.local_symbol}_{p.side[0]}"
        seq = 1
        while self.ledger.order(self.account, f"{base}_{seq:02d}") is not None:
            seq += 1
        return f"{base}_{seq:02d}"

    def _execute(self, p: Proposal, approval: Approval, method: str,
                 confirmation: dict[str, Any] | None) -> dict[str, Any]:
        info = self.broker.qualify(p.symbol_id)
        qty = approval.approved_qty
        cid = self._client_order_id(p)
        group = new_id("brk")
        specs, pending = self._specs(p, qty, cid, group, info)
        if p.intent == "reduce":
            self._shrink_protection(info.con_id, abs(self.broker.position_qty(info.con_id)) - qty)
        detail = json.dumps({"proposal": _jsonable(p), "approval_id": approval.approval_id,
                             "confirmation": {"method": method, "given": confirmation,
                                              "at": self.clock().isoformat()}}, default=str)
        for spec in specs:
            self._record_spec(spec, p, approval.approval_id, group, info, detail)
        self._proposals[p.id] = p
        if pending:
            # Registered BEFORE sending: a market order can fill inside
            # broker.place(), and the fill must find its protection waiting.
            self._pending[cid] = {**pending, "proposal_id": p.id, "approval_id": approval.approval_id,
                                  "group": group, "attempts": 0, "symbol_id": p.symbol_id}
        try:
            views = self.broker.place(info, specs)
        except Exception as exc:  # noqa: BLE001 — never blind-retry
            self._pending.pop(cid, None)
            for spec in specs:
                self.ledger.record_order_event(self.account, spec["ref"], "rejected", self._now(), str(exc))
            self._audit("place_failed", {"client_order_id": cid, "error": str(exc)})
            raise Refused(f"IBKR did not accept the order: {exc}. Nothing was retried.") from exc
        for v in views:
            # The fill may have landed during placement, before any status
            # callback could see the pending protection; catch it here too.
            if v["ref"] in self._pending and v["state"] == "filled" and v["avg_fill_price"] is not None:
                self._place_pending(v["ref"], v["avg_fill_price"], int(v["filled"]))
        self._recent[fingerprint(p)] = time.monotonic()
        self._last_activity = time.monotonic()
        for v in views:
            self.ledger.record_order_event(self.account, v["ref"], v["state"], self._now(), v.get("error"))
            self.emit("order.placed", {"order_id": v["ref"], "approval_id": approval.approval_id,
                                       "broker_id": str(v["perm_id"]), "symbol": p.local_symbol})
        self._run_deferred()
        self._audit("placed", {"client_order_id": cid, "approval_id": approval.approval_id, "method": method,
                               "orders": [_jsonable(v) for v in views]})
        self._publish(force=True)
        return {"ok": True, "client_order_id": cid, "orders": [_jsonable(v) for v in views],
                "summary": f"{p.side} {qty} {p.local_symbol} {p.order_type} sent"}

    def _record_spec(self, spec: dict[str, Any], p: Proposal, approval_id: str, group: str,
                     info: ContractInfo, detail: str | None) -> None:
        self.ledger.record_order({
            "account_id": self.account, "client_order_id": spec["ref"], "approval_id": approval_id,
            "symbol": p.symbol_id, "side": spec["side"], "qty": spec["qty"], "order_type": spec["type"],
            "limit_price": spec.get("limit"), "stop_price": spec.get("stop"), "trail_amount": spec.get("trail"),
            "state": "new", "trace_id": p.trace_id, "ts": self._now(), "proposal_id": p.id,
            "con_id": info.con_id, "role": spec["role"], "bracket_group": group,
        }, detail if spec["role"] in ("entry", "close") else None)

    @staticmethod
    def _specs(p: Proposal, qty: int, cid: str, group: str, info: ContractInfo
               ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Parent-first order specs, plus whatever must wait for the fill price.

        A limit entry knows its price, so its stop and target go with it as a
        native bracket. A market entry does not -- and on a delayed quote an
        absolute price guessed now can land on the wrong side of the real
        fill -- so offset-based children are placed the moment the fill
        arrives, against the actual fill price. A trailing stop needs no
        price, so it always travels with the parent.
        """
        role = "close" if p.intent == "reduce" else "entry"
        specs = [{"ref": cid, "role": role, "side": p.side, "qty": qty, "type": p.order_type,
                  "limit": p.limit_price, "tif": p.tif}]
        if p.intent == "reduce":
            return specs, {}
        exit_side = "sell" if p.side == "buy" else "buy"
        sign = 1 if p.side == "buy" else -1
        ref = p.limit_price if p.order_type == "limit" else None
        tick = info.min_tick
        # No OCA group on native children: IBKR links a bracket's children to
        # their parent itself, and a child carrying an explicit group is
        # rejected on its first modification -- and cancelled (10326, seen
        # 2026-09-14). The group lives in the ledger's bracket_group only.
        child = {"side": exit_side, "qty": qty, "parent_ref": cid, "tif": "GTC"}
        pending: dict[str, Any] = {}

        if p.stop_kind == "trail":
            initial = round_to_tick(ref - sign * p.trail_amount, tick) if ref is not None else None
            specs.append({**child, "ref": f"{cid}_sl", "role": "stop", "type": "trail",
                          "trail": p.trail_amount, "stop": initial})
        elif p.stop_price is not None:
            specs.append({**child, "ref": f"{cid}_sl", "role": "stop", "type": "stop", "stop": p.stop_price})
        elif ref is not None:
            specs.append({**child, "ref": f"{cid}_sl", "role": "stop", "type": "stop",
                          "stop": round_to_tick(ref - sign * p.stop_offset, tick)})
        else:
            pending["stop_offset"] = p.stop_offset

        if p.target_price is not None:
            specs.append({**child, "ref": f"{cid}_tp", "role": "target", "type": "limit", "limit": p.target_price})
        elif p.target_offset is not None and ref is not None:
            specs.append({**child, "ref": f"{cid}_tp", "role": "target", "type": "limit",
                          "limit": round_to_tick(ref + sign * p.target_offset, tick)})
        elif p.target_offset is not None:
            pending["target_offset"] = p.target_offset
        return specs, pending

    def _place_pending(self, cid: str, avg_price: Decimal, filled: int) -> None:
        # Taken out before placing: place() pumps IBKR's events, IBKR repeats
        # "Filled", and a re-entrant call must find nothing to place twice.
        pend = self._pending.pop(cid, None)
        if pend is None:
            return
        entry_order = self.ledger.order(self.account, cid)
        exit_side = "sell" if entry_order and entry_order["side"] == "buy" else "buy"
        info_now = self.broker.qualify(pend["symbol_id"])
        covered = sum(int(o["remaining"]) for o in self.broker.open_orders()
                      if o["con_id"] == info_now.con_id and o["working"] and o["type"] in ("stop", "trail")
                      and o["side"] == exit_side)
        if covered >= abs(self.broker.position_qty(info_now.con_id)) > 0:
            return  # already protected -- a retry must never stack a second stop
        entry = self.ledger.order(self.account, cid)
        p = self._proposals.get(pend["proposal_id"])
        info = self.broker.qualify(pend["symbol_id"])
        sign = 1 if entry["side"] == "buy" else -1
        exit_side = "sell" if sign == 1 else "buy"
        n = pend["attempts"] + 1
        specs = []
        base = {"side": exit_side, "qty": filled, "oca": pend["group"], "tif": "GTC"}
        if pend.get("stop_offset") is not None:
            specs.append({**base, "ref": f"{cid}_sl{n}", "role": "stop", "type": "stop",
                          "stop": round_to_tick(avg_price - sign * pend["stop_offset"], info.min_tick)})
        if pend.get("target_offset") is not None:
            specs.append({**base, "ref": f"{cid}_tp{n}", "role": "target", "type": "limit",
                          "limit": round_to_tick(avg_price + sign * pend["target_offset"], info.min_tick)})
        pend["attempts"] = n
        proposal = p or _stub_proposal(entry, info)
        for spec in specs:
            self._record_spec(spec, proposal, pend["approval_id"], pend["group"], info, None)
        try:
            views = self.broker.place(info, specs)
        except Exception as exc:  # noqa: BLE001
            log.error("placing protection for %s failed (attempt %s): %s", cid, n, exc)
            for spec in specs:
                self.ledger.record_order_event(self.account, spec["ref"], "rejected", self._now(), str(exc))
            if n < 3:
                self._pending[cid] = pend  # the grace monitor retries it
            else:
                self.emit("execution.fatal", {"reason": f"stop for {cid} could not be placed — flattening",
                                              "detail": str(exc)})
                self._auto_flatten(info.con_id, "stop placement failed three times")
            return
        for v in views:
            self.ledger.record_order_event(self.account, v["ref"], v["state"], self._now(), v.get("error"))

    # ------------------------------------------------------------------
    # manage: modify, cancel, flatten
    # ------------------------------------------------------------------

    def _working(self, ref: str) -> dict[str, Any]:
        for v in self.broker.open_orders():
            if v["ref"] == ref and v["working"]:
                return v
        raise Refused(f"{ref} is not a working order")

    def _modify(self, ref: str, ch: dict[str, Any]) -> dict[str, Any]:
        order = self.ledger.order(self.account, ref)
        if order is None:
            raise Refused(f"{ref} is not a Genesis order")
        v = self._working(ref)
        info = self.broker.qualify(order["symbol"])
        quote = self.broker.quote(info)
        role = order["role"]
        pos = self.broker.position_qty(info.con_id)
        common = dict(id=new_id("ord_prop"), created=self._now(), trace_id=order["trace_id"],
                      symbol_id=info.symbol_id, root=info.root, local_symbol=info.local_symbol,
                      con_id=info.con_id, multiplier=info.multiplier, min_tick=info.min_tick,
                      side=v["side"], qty=max(int(v["remaining"]), 1), intent="modify", modifies=ref,
                      arrival_mid=quote["mid"], arrival_bid=quote["bid"], arrival_ask=quote["ask"],
                      arrival_ts=quote["ts"], arrival_source=quote["source"])
        actions: list[tuple[str, dict[str, Any]]] = []

        if role == "entry" and ch.get("limit_price") is not None:
            new = _money(ch["limit_price"], "limit price")
            if v["limit"] is None:
                raise Refused("only a limit entry has a price to move")
            delta = new - v["limit"]
            children = [c for c in self.broker.open_orders() if c["parent_id"] == v["order_id"] and c["working"]]
            stop_child = next((c for c in children if c["type"] in ("stop", "trail")), None)
            shifted = None if stop_child is None or stop_child["stop"] is None else stop_child["stop"] + delta
            p = Proposal(**common, order_type="limit", limit_price=new,
                         stop_kind="fixed" if shifted is not None else "none",
                         stop_price=shifted, current_stop_price=shifted)
            actions.append((ref, {"limit": new}))
            for c in children:
                if c["type"] == "limit" and c["limit"] is not None:
                    actions.append((c["ref"], {"limit": c["limit"] + delta}))
                elif c["stop"] is not None:
                    actions.append((c["ref"], {"stop": c["stop"] + delta}))
        elif role == "target" and ch.get("limit_price") is not None:
            new = _money(ch["limit_price"], "target price")
            p = Proposal(**common, order_type="limit", limit_price=new, target_price=new)
            actions.append((ref, {"limit": new}))
        elif role == "stop":
            if ch.get("breakeven"):
                if pos == 0:
                    raise Refused("no position — nothing to move to breakeven")
                avg = next(x["avg_price"] for x in self.broker.positions() if x["con_id"] == info.con_id)
                new = round_to_tick(avg, info.min_tick, up=pos > 0)
                mid = quote["mid"]
                if mid is None or (new >= mid if pos > 0 else new <= mid):
                    raise Refused(f"price is not past breakeven ({new}) — the stop would fire at once")
                ch = {"stop_price": new}
            if ch.get("stop_price") is not None:
                new = _money(ch["stop_price"], "stop price")
                p = Proposal(**common, order_type="market", stop_kind="fixed", stop_price=new,
                             current_stop_price=v["stop"])
                actions.append((ref, {"stop": new}))
            elif ch.get("trail_amount") is not None:
                trail = _money(ch["trail_amount"], "trail amount")
                p = Proposal(**common, order_type="market", stop_kind="trail", trail_amount=trail,
                             current_stop_price=v["stop"])
                if v["type"] == "trail":
                    actions.append((ref, {"trail": trail}))
                else:
                    actions.append(("__convert__", {"trail": trail}))
            else:
                raise Refused("a stop change is stop_price, trail_amount, or breakeven")
        else:
            raise Refused(f"nothing to change on a {role} order with {sorted(ch)}")

        decision = evaluate(p, self._context(p, info), now=self.clock())
        self._audit("modify_proposal", {"ref": ref, "changes": {k: _s(x) for k, x in ch.items()},
                                        "decision": decision.to_dict()})
        if not decision.approved:
            raise Refused(decision.spoken_summary)
        approval = self.book.issue(p, decision, self.mode)
        self.book.redeem(approval.approval_id, approval.signature, p.binds(decision.approved_qty),
                         {"symbol": p.local_symbol, "qty": decision.approved_qty})
        for target_ref, kw in actions:
            if target_ref == "__convert__":
                self._convert_to_trail(order, v, kw["trail"], approval.approval_id, info)
            else:
                self.broker.modify(target_ref, **kw)
                self.ledger.record_order_event(self.account, target_ref, "accepted", self._now(),
                                               json.dumps({"modified": {k: str(x) for k, x in kw.items()},
                                                           "approval_id": approval.approval_id}))
        self._last_activity = time.monotonic()
        self._publish(force=True)
        return {"ok": True, "decision": decision.to_dict(), "summary": f"{ref} changed"}

    def _convert_to_trail(self, order: dict[str, Any], v: dict[str, Any], trail: Decimal,
                          approval_id: str, info: ContractInfo) -> None:
        """Replace a stop with a trailing stop, never leaving a moment with no stop.

        Measured against the paper gateway on 2026-09-14, three facts decide
        the shape: IBKR will not change an order's type in place (329); a
        bracket child cannot join an OCA group (10326); and cancelling one
        member of an OCA group cancels the whole group. So the whole
        protection set is replaced:

        1. A new trailing stop, and a new target if there was one, go out
           together in a fresh OCA group. Each sits one tick *beyond* the order
           it replaces, so on a fast move the old order fills first -- and the
           fill handler then cancels the new set, because the position is gone.
        2. Only once the new trailing stop is working are the old stop and
           target cancelled.
        """
        if int(v["remaining"]) < 1:
            raise Refused(f"{order['client_order_id']} has nothing left to protect")
        selling = v["side"] == "sell"
        tick = info.min_tick
        away = -tick if selling else tick
        mid = self.broker.quote(info)["mid"]
        initial = None
        if mid is not None:
            initial = round_to_tick(mid - trail if selling else mid + trail, tick)
            if v["stop"] is not None:
                initial = min(initial, v["stop"] + away) if selling else max(initial, v["stop"] + away)
        old_target = next(
            (o for o in self._ours(v["con_id"])
             if o["type"] == "limit" and o["side"] == v["side"]
             and (self.ledger.order(self.account, o["ref"]) or {}).get("role") == "target"
             and (self.ledger.order(self.account, o["ref"]) or {}).get("bracket_group") == order["bracket_group"]),
            None)
        n = 2
        base = order["client_order_id"]
        while self.ledger.order(self.account, f"{base}_tr{n}") is not None:
            n += 1
        group = new_id("oca")
        qty = int(v["remaining"])
        specs = [{"ref": f"{base}_tr{n}", "role": "stop", "side": v["side"], "qty": qty, "type": "trail",
                  "trail": trail, "stop": initial, "oca": group, "tif": "GTC"}]
        if old_target is not None and old_target["limit"] is not None:
            specs.append({"ref": f"{base}_tp{n}", "role": "target", "side": v["side"], "qty": qty, "type": "limit",
                          "limit": old_target["limit"] - away, "oca": group, "tif": "GTC"})
        proposal = self._proposals.get(order["proposal_id"]) or _stub_proposal(order, info)
        for spec in specs:
            self._record_spec(spec, proposal, approval_id, order["bracket_group"], info, None)
        self.broker.place(info, specs)
        ref = specs[0]["ref"]
        deadline = time.monotonic() + 3
        new = None
        while time.monotonic() < deadline:
            new = next((o for o in self.broker.open_orders() if o["ref"] == ref), None)
            if new is not None and (new["working"] or new.get("error")):
                break
            self.pump(0.1)
        if new is None or not new["working"]:
            for spec in specs:
                try:
                    self.broker.cancel(spec["ref"])
                except Exception:  # noqa: BLE001 — may never have been accepted
                    pass
            raise Refused(f"IBKR did not accept the trailing stop ({(new or {}).get('error') or 'no answer'}); "
                          f"the original stop is still working")
        for old in (old_target, v):
            if old is None:
                continue
            try:
                self.broker.cancel(old["ref"])
            except Exception:  # noqa: BLE001 — already gone with its group is fine
                pass

    def _cancel(self, ref: str) -> dict[str, Any]:
        order = self.ledger.order(self.account, ref)
        v = self._working(ref)
        if order is None:
            raise Refused(f"{ref} was not placed by Genesis")
        parent_working = any(o["order_id"] == v["parent_id"] and o["working"] for o in self.broker.open_orders())
        if order["role"] == "stop" and not parent_working and self.broker.position_qty(v["con_id"]) != 0:
            raise Refused("a protective stop cannot be cancelled while the position is open — move it or flatten")
        self.broker.cancel(ref)
        self._audit("cancel", {"ref": ref})
        self._last_activity = time.monotonic()
        return {"ok": True, "summary": f"cancel sent for {ref}"}

    def _flatten(self, symbol_id: str, qty: int | None, origin: str) -> dict[str, Any]:
        info = self.broker.qualify(symbol_id)
        con = info.con_id
        # Unfilled entries first -- a flatten that leaves a working buy is not flat.
        for v in self._ours(con):
            order = self.ledger.order(self.account, v["ref"])
            if order and order["role"] == "entry" and v["filled"] == 0:
                self.broker.cancel(v["ref"])
        pos = self.broker.position_qty(con)
        if pos == 0:
            self._publish(force=True)
            return {"ok": True, "summary": f"{info.local_symbol}: no position; working entries cancelled"}
        size = abs(pos) if qty is None else min(int(qty), abs(pos))
        ticket = {"symbol_id": symbol_id, "side": "sell" if pos > 0 else "buy", "qty": size,
                  "order_type": "market", "intent": "close", "origin": origin}
        proposed = self._propose(self._ticket_proposal(ticket, info, self.broker.quote(info)), info)
        if not proposed["ok"]:
            raise Refused(proposed["reason"])
        if size == abs(pos):
            # Cancel protection before closing, so a stop and the close cannot
            # both fill and reverse the position.
            for v in self._ours(con):
                order = self.ledger.order(self.account, v["ref"])
                if order and order["role"] in ("stop", "target"):
                    self.broker.cancel(v["ref"])
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and any(
                    (self.ledger.order(self.account, v["ref"]) or {}).get("role") in ("stop", "target")
                    for v in self._ours(con)):
                self.pump(0.1)
        placed = self._place(proposed["approval"]["approval_id"], None, "auto" if origin != "human" else "dashboard")
        return {**proposed, **placed}

    def _auto_flatten(self, con_id: int, reason: str) -> None:
        last = self._flattening.get(con_id)
        if last is not None and time.monotonic() - last < 60:
            return
        self._flattening[con_id] = time.monotonic()
        symbol = self._symbol_for_con(con_id)
        self._audit("auto_flatten", {"con_id": con_id, "symbol_id": symbol, "reason": reason})
        try:
            result = self._flatten(symbol, None, "order-manager")
            self.emit("execution.protection", {"symbol_id": symbol, "action": "flattened", "reason": reason,
                                               "summary": result.get("summary")})
        except Exception as exc:  # noqa: BLE001
            self.emit("execution.fatal", {"reason": f"{symbol} is unprotected and could not be flattened",
                                          "detail": f"{reason}; {exc}"})

    def _ours(self, con_id: int) -> list[dict[str, Any]]:
        cid = getattr(self.broker, "client_id", None)
        return [v for v in self.broker.open_orders()
                if v["con_id"] == con_id and v["working"] and (cid is None or v["client_id"] == cid)]

    def _entry_filled(self, order: dict[str, Any]) -> bool:
        """Has the entry this stop or target belongs to filled? From the ledger,
        not the broker's open-order list, which may not hold the entry yet."""
        if not order.get("bracket_group"):
            return True
        row = self.ledger.connection.execute(
            "SELECT client_order_id FROM orders WHERE account_id = ? AND bracket_group = ? AND role = 'entry'",
            (self.account, order["bracket_group"])).fetchone()
        if row is None:
            return True
        return self.ledger.order_state(self.account, row["client_order_id"]) in ("filled", "partially_filled")

    def _shrink_protection(self, con_id: int, cover: int) -> None:
        """Keep stop and target sizes within the position they protect.

        Without this, a stop sized for two contracts on a one-contract position
        opens a new position the other way when it fires. Children of an entry
        that has not filled are left alone: they are not protecting anything
        yet, and IBKR sizes them when the entry fills.
        """
        for role in ("stop", "target"):
            left = max(cover, 0)
            for v in self._ours(con_id):
                order = self.ledger.order(self.account, v["ref"])
                if not order or order["role"] != role or not self._entry_filled(order):
                    continue
                remaining = int(v["remaining"])
                if left <= 0:
                    self.broker.cancel(v["ref"])
                elif remaining > left:
                    self.broker.modify(v["ref"], qty=left)
                    left = 0
                else:
                    left -= remaining

    # ------------------------------------------------------------------
    # broker events
    # ------------------------------------------------------------------

    def _on_status(self, v: dict[str, Any]) -> None:
        if self.ledger is None:
            return
        self._last_activity = time.monotonic()
        if self.ledger.order(self.account, v["ref"]) is None:
            return
        self.ledger.record_order_event(self.account, v["ref"], v["state"], self._now(), v.get("error"))
        if v["state"] == "filled" and v["ref"] in self._pending and v["avg_fill_price"] is not None:
            ref, price, qty = v["ref"], v["avg_fill_price"], int(v["filled"])
            self._defer_or_run(lambda: self._place_pending(ref, price, qty))

    def _on_fill(self, f: dict[str, Any]) -> None:
        if self.ledger is None:
            return
        self._last_activity = time.monotonic()
        if not self._record_fill(f):
            return  # already in the ledger: IBKR replays today's fills on connect
        con = f["con_id"]
        self._defer_or_run(lambda: self._shrink_protection(con, abs(self.broker.position_qty(con))))

    def _record_fill(self, f: dict[str, Any], *, reconciling: bool = False) -> bool:
        if self.ledger.has_broker_fill(self.account, f["exec_id"]):
            return False
        ref = f["ref"] or ""
        order = self.ledger.order(self.account, ref) if ref else None
        if order is None and ref.startswith("kill_"):
            order = self._record_kill_order(f)
        if order is None:
            if not reconciling:
                self._breach([f"fill {f['exec_id']} ({f['side']} {f['qty']} con {f['con_id']}) "
                              f"was not placed by Genesis"])
            return False
        stored = self.ledger.record_fill(Fill(
            account_id=self.account, client_order_id=order["client_order_id"], broker_fill_id=f["exec_id"],
            approval_id=order["approval_id"], symbol=order["symbol"], side=f["side"], qty=f["qty"],
            price=f["price"], fee=f["fee"], trace_id=order["trace_id"], ts=f["ts"], order_id=order["id"],
            venue=f.get("venue"),
        ))
        if stored is None:
            return False
        self.emit("order.filled", {"fill_id": stored.id, "order_id": order["client_order_id"],
                                   "symbol": order["symbol"], "price": str(f["price"]), "qty": str(f["qty"])})
        self._measure(stored, order, f)
        return True

    def _record_kill_order(self, f: dict[str, Any]) -> dict[str, Any]:
        info = self.broker.info_for_con(f["con_id"])
        symbol = self._symbol_for_con(f["con_id"])
        return self.ledger.record_order({
            "account_id": self.account, "client_order_id": f["ref"], "approval_id": f["ref"].rsplit("_", 1)[0],
            "symbol": symbol, "side": f["side"], "qty": f["qty"], "order_type": "market", "state": "filled",
            "trace_id": f["ref"], "ts": f["ts"], "con_id": f["con_id"], "role": "close",
        }, json.dumps({"placed_by": "kill-switch", "local_symbol": info.local_symbol if info else None}))

    def _measure(self, stored: Fill, order: dict[str, Any], f: dict[str, Any]) -> None:
        from genesis.agents.execution.execution_quality import measure_fill

        detail = self.ledger.first_event_detail(self.account, order["client_order_id"])
        arrival = json.loads(detail).get("proposal", {}) if detail else {}
        info = self.broker.info_for_con(f["con_id"])
        mult = info.multiplier if info else Decimal(1)
        if order["role"] == "stop" and order["stop_price"]:
            mid, bid, ask, source = Decimal(order["stop_price"]), None, None, "trigger"
        else:
            mid, bid, ask, source = (_money(arrival.get("arrival_mid"), "mid"), _money(arrival.get("arrival_bid"), "bid"),
                                     _money(arrival.get("arrival_ask"), "ask"), arrival.get("arrival_source"))
        try:
            started = datetime.fromisoformat(order["ts"])
            ttf = int((datetime.fromisoformat(f["ts"]) - started).total_seconds() * 1000)
        except ValueError:
            ttf = None
        fq = measure_fill(fill_id=stored.id, order=order["client_order_id"], symbol=order["symbol"], side=f["side"],
                          qty=f["qty"], fill_price=f["price"], multiplier=mult, fees=f["fee"],
                          order_type=order["order_type"], ts=f["ts"], arrival_mid=mid, arrival_bid=bid,
                          arrival_ask=ask, arrival_source=source, time_to_fill_ms=ttf)
        self.quality.put(fq)
        self._adverse.append((time.monotonic() + 30, stored.id, f["con_id"]))
        self.emit("execution.quality", asdict(fq))

    def _sample_adverse(self) -> None:
        from genesis.agents.execution.execution_quality import measure_fill

        now = time.monotonic()
        due = [a for a in self._adverse if a[0] <= now]
        self._adverse = [a for a in self._adverse if a[0] > now]
        for _, fill_id, con_id in due:
            fq = self.quality.get(fill_id)
            info = self.broker.info_for_con(con_id)
            if fq is None or info is None:
                continue
            mid = self.broker.quote(info)["mid"]
            updated = measure_fill(
                fill_id=fq.fill_id, order=fq.order, symbol=fq.symbol, side=fq.side, qty=fq.qty,
                fill_price=Decimal(fq.fill_price), multiplier=info.multiplier, fees=Decimal(fq.fees),
                order_type=fq.order_type, ts=fq.ts, arrival_mid=_money(fq.arrival_mid, "mid"),
                arrival_bid=None, arrival_ask=None, arrival_source=fq.arrival_source,
                time_to_fill_ms=fq.time_to_fill_ms, mid_30s_after=mid,
            )
            self.quality.put(replace(updated, spread_at_arrival_bps=fq.spread_at_arrival_bps))

    # ------------------------------------------------------------------
    # homeostasis: halt, protection, reconciliation
    # ------------------------------------------------------------------

    def _watch_halt(self) -> None:
        try:
            doc = halt.read(self.halt_path)
        except halt.HaltUnreadable as exc:
            doc = {"engaged": True, "id": "unreadable", "level": "halt", "trigger": f"halt flag unreadable: {exc}"}
        if not doc["engaged"]:
            if self._halt_seen is not None:
                self._halt_seen = self._halt_level = None
                self.emit("halt.cleared", {})
            return
        if doc.get("id") == self._halt_seen and doc.get("level") == self._halt_level:
            return
        first = doc.get("id") != self._halt_seen
        self._halt_seen, self._halt_level = doc.get("id"), doc.get("level", "halt")
        cancelled = self._cancel_for_halt(self._halt_level)
        self._audit("halt_seen", {"halt": doc, "cancelled": cancelled})
        if first:
            self.emit("halt.engaged", {"trigger": doc.get("trigger", "unknown"), "level": self._halt_level})
        self._publish(force=True)

    def _cancel_for_halt(self, level: str) -> list[str]:
        """``halt``: cancel entries, keep every exit order on an open position.
        ``flatten``: cancel everything; the kill switch closes the positions.

        Exits means stops *and* targets. IBKR cancels a whole OCA group when
        one member is cancelled, so cancelling a target took its stop down
        with it and left the position bare (seen 2026-09-14). An exit order
        can only reduce risk; keeping it is the safe side of the rule.
        """
        cancelled = []
        cid = getattr(self.broker, "client_id", None)
        held = {p["con_id"]: p["qty"] for p in self.broker.positions()}
        for v in self.broker.open_orders():
            if not v["working"] or (cid is not None and v["client_id"] != cid):
                continue
            order = self.ledger.order(self.account, v["ref"]) or {}
            pos = held.get(v["con_id"], 0)
            exit_order = (pos > 0 and v["side"] == "sell" or pos < 0 and v["side"] == "buy") \
                and order.get("role") in ("stop", "target", "close") and self._entry_filled(order)
            if level == "halt" and exit_order:
                continue
            try:
                self.broker.cancel(v["ref"])
                cancelled.append(v["ref"])
            except Exception as exc:  # noqa: BLE001 — keep cancelling the rest
                log.error("halt: cancelling %s failed: %s", v["ref"], exc)
        return cancelled

    def _protect(self) -> None:
        if self._halt_level == "flatten":
            return
        grace = self.config.execution.protective_grace_sec
        held = {s for s, q in self._ledger_positions().items() if q}
        open_orders = self.broker.open_orders()
        for pos in self.broker.positions():
            con, qty = pos["con_id"], pos["qty"]
            if self._symbol_for_con(con) not in held:
                continue  # not ours yet: reconciliation's problem, not a thing to close
            exit_side = "sell" if qty > 0 else "buy"
            cover = sum(int(v["remaining"]) for v in open_orders if v["con_id"] == con and v["working"]
                        and v["type"] in ("stop", "trail") and v["side"] == exit_side)
            if cover >= abs(qty):
                self._unprotected.pop(con, None)
                continue
            since = self._unprotected.setdefault(con, time.monotonic())
            waiting = [c for c, pend in self._pending.items() if self.broker.qualify(pend["symbol_id"]).con_id == con]
            for c in waiting:
                self._place_pending(c, pos["avg_price"], abs(qty))
            if time.monotonic() - since > grace and not waiting:
                self._auto_flatten(con, f"{pos['local_symbol']} had no working stop for {grace}s")

    def _mark(self, key: Any) -> dict[str, Any] | None:
        """One quote for the accountant, keyed by con id or symbol id.

        The accountant must not hold a broker handle of its own -- every broker
        call in this process goes through the order thread, and a second caller
        poking `ib_async` from elsewhere is how a quote request deadlocks a
        fill callback.
        """
        try:
            info = (
                self.broker.info_for_con(int(key))
                if isinstance(key, int) or str(key).isdigit()
                else self.broker.qualify(str(key))
            )
        except Exception:  # noqa: BLE001 - an unknown contract has no mark
            return None
        return self.broker.quote(info) if info is not None else None

    def _ledger_positions(self) -> dict[str, int]:
        return {sym: p.qty for (acct, sym), p in self.ledger.rebuild(account_id=self.account).items()}

    def _symbol_for_con(self, con_id: int) -> str:
        known = self.ledger.symbol_for_con_id(con_id) if self.ledger else None
        if known:
            return known
        info = self.broker.info_for_con(con_id)
        if info:
            return info.symbol_id
        for p in self.broker.positions():
            if p["con_id"] == con_id and p["sec_type"] == "FUT" and p["contract_month"]:
                from genesis.marketdata.normalize import instrument_id

                m = p["contract_month"]
                return instrument_id("FUT", p["exchange"] or "CME", p["root"], contract_month=f"{m[:4]}-{m[4:6]}")
        return f"CON:{con_id}"

    def _reconcile(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._last_activity < QUIET_SEC:
            return
        problems: list[str] = []
        for f in self.broker.executions():
            if self.ledger.has_broker_fill(self.account, f["exec_id"]):
                continue
            if not self._record_fill(f, reconciling=True):
                problems.append(f"execution {f['exec_id']} ({f['side']} {f['qty']} of con {f['con_id']}) "
                                f"is not in the ledger")
        for v in self.broker.open_orders():
            if not v["working"]:
                continue
            key = v["ref"] or f"ext_{v['perm_id']}"
            order = self.ledger.order(self.account, key)
            if order is None and key.startswith("kill_"):
                continue  # the kill switch's re-placed stops: known, not ours to manage
            if order is None:
                problems.append(f"working order {v['side']} {v['qty']} {v['local_symbol']} {v['type']} "
                                f"(client {v['client_id']}) was not placed by Genesis")
            else:
                self.ledger.record_order_event(self.account, key, v["state"], self._now())
        # The position comparison is the accountant's, not a second copy of it
        # here. Zero tolerance either way -- this is the component that halts.
        if self.accountant is not None:
            problems += self.accountant.reconcile(account=self.account)["problems"]
        matched = not problems
        detail = "broker and ledger agree" if matched else "; ".join(problems)
        was = self._recon["matched"]
        self._recon = {"matched": matched, "detail": detail, "at": self._now(), "problems": problems}
        if force or matched != was:
            self.ledger.record_reconciliation(self.account, matched, detail, self._now())
        if not matched and was is not False:
            self._breach(problems)

    def _breach(self, problems: list[str]) -> None:
        detail = "; ".join(problems)
        self._recon = {"matched": False, "detail": detail, "at": self._now(), "problems": problems}
        doc = halt.engage(self.halt_path, level="halt", trigger="reconciliation", detail=detail)
        self._audit("reconciliation_failed", {"problems": problems, "halt": doc.get("id")})
        self.emit("reconciliation.failed", {"detail": detail, "problems": problems})

    def _adopt(self, by: str) -> dict[str, Any]:
        """Take the broker's word for what Genesis did not place. Dashboard only.

        Records what the reconciliation found as adopted orders and fills, under
        an approval id that says so. It does not clear the halt; resuming is
        its own deliberate act.
        """
        if by != "dashboard":
            raise Refused("adopting broker state is a dashboard action")
        rec = new_id("adopt")
        adopted: list[str] = []
        base = {"account_id": self.account, "approval_id": rec, "state": "accepted", "trace_id": rec,
                "ts": self._now(), "role": "external"}
        for f in self.broker.executions():
            if self.ledger.has_broker_fill(self.account, f["exec_id"]) or self.ledger.order(self.account, f["ref"] or ""):
                continue
            key = f"ext_{f['perm_id']}"
            if self.ledger.order(self.account, key) is None:
                self.ledger.record_order({**base, "client_order_id": key, "symbol": self._symbol_for_con(f["con_id"]),
                                          "side": f["side"], "qty": f["qty"], "order_type": "external",
                                          "con_id": f["con_id"], "state": "filled"})
            self._record_fill({**f, "ref": key}, reconciling=True)
            adopted.append(f"fill {f['exec_id']}")
        for v in self.broker.open_orders():
            key = v["ref"] or f"ext_{v['perm_id']}"
            if v["working"] and not key.startswith("kill_") and self.ledger.order(self.account, key) is None:
                self.ledger.record_order({**base, "client_order_id": key, "symbol": self._symbol_for_con(v["con_id"]),
                                          "side": v["side"], "qty": v["qty"], "order_type": v["type"],
                                          "con_id": v["con_id"]})
                adopted.append(f"order {key}")
        ledger_q = self._ledger_positions()
        for p in self.broker.positions():
            sym = self._symbol_for_con(p["con_id"])
            diff = p["qty"] - ledger_q.get(sym, 0)
            if diff == 0:
                continue
            key = f"{rec}_{p['con_id']}"
            self.ledger.record_order({**base, "client_order_id": key, "symbol": sym, "side": "buy" if diff > 0 else "sell",
                                      "qty": abs(diff), "order_type": "external", "con_id": p["con_id"],
                                      "state": "filled"})
            self.ledger.record_fill(Fill(
                account_id=self.account, client_order_id=key, broker_fill_id=key, approval_id=rec, symbol=sym,
                side="buy" if diff > 0 else "sell", qty=abs(diff), price=p["avg_price"], fee=Decimal(0),
                trace_id=rec, ts=self._now(),
            ))
            adopted.append(f"position {sym} {diff:+d} @ {p['avg_price']}")
        self._audit("adopt", {"by": by, "id": rec, "adopted": adopted})
        self._reconcile(force=True)
        return {"ok": True, "adopted": adopted, "reconciliation": self._recon,
                "summary": f"adopted {len(adopted)} item(s); positions without a working stop will be "
                           f"closed {self.config.execution.protective_grace_sec}s after trading resumes"}

    def _resume(self, by: str, resolution: str) -> dict[str, Any]:
        if by != "dashboard":
            raise Refused("leaving halt is a dashboard action — never voice, never an agent")
        self._reconcile(force=True)
        if not self._recon["matched"]:
            raise Refused(f"reconciliation must pass first: {self._recon['detail']}")
        doc = halt.clear(self.halt_path, by=by, resolution=resolution or "resumed from the trade panel")
        if self.mode == "auto-within-limits":
            self._set_mode("confirm", "kill-switch-recovery")  # resume into confirm, never auto
        self._audit("resume", {"by": by, "resolution": resolution})
        self._watch_halt()
        return {"ok": True, "mode": self.mode, "halt": doc}

    # ------------------------------------------------------------------
    # mode
    # ------------------------------------------------------------------

    def _set_mode(self, mode: str, by: str) -> dict[str, Any]:
        from genesis.config import DEFAULT_CONFIG_PATH, load_config

        if mode not in AUTONOMY:
            raise Refused(f"mode is advisory, confirm or auto-within-limits (halt is the kill switch), not {mode!r}")
        loosening = AUTONOMY[mode] > AUTONOMY.get(self.mode, 0)
        if loosening and by != "dashboard":
            raise Refused("loosening the approval mode needs the dashboard — not voice, not an agent")
        path = DEFAULT_CONFIG_PATH.expanduser()
        before = path.read_text() if path.is_file() else ""
        doc = yaml.safe_load(before) or {}
        doc.setdefault("approval", {})["mode"] = mode
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, sort_keys=False))
        try:
            load_config()
        except Exception:
            path.write_text(before)
            raise
        previous, self.mode = self.mode, mode
        self._audit("mode", {"from": previous, "to": mode, "by": by})
        self.emit("approval.mode_changed", {"from": previous, "to": mode, "by": by})
        self._published = None
        return {"ok": True, "mode": mode, "previous": previous}

    # ------------------------------------------------------------------
    # state for the UI
    # ------------------------------------------------------------------

    def _halt_state(self) -> dict[str, Any]:
        try:
            doc = halt.read(self.halt_path)
            return {k: doc.get(k) for k in ("engaged", "level", "trigger", "detail", "at", "id")}
        except halt.HaltUnreadable as exc:
            return {"engaged": True, "level": "halt", "trigger": "unreadable", "detail": str(exc)}

    def _state(self) -> dict[str, Any]:
        orders = []
        roles = {}
        for v in self.broker.open_orders():
            key = v["ref"] or f"ext_{v['perm_id']}"
            order = self.ledger.order(self.account, key)
            roles[key] = order["role"] if order else "unknown"
            orders.append({**_jsonable(v), "client_order_id": key, "role": roles[key],
                           "symbol_id": order["symbol"] if order else self._symbol_for_con(v["con_id"]),
                           "bracket_group": order["bracket_group"] if order else None,
                           "ours": v["client_id"] == getattr(self.broker, "client_id", None)})
        positions = []
        for p in self.broker.positions():
            exit_side = "sell" if p["qty"] > 0 else "buy"
            cover = sum(int(o["remaining"]) for o in orders if o["con_id"] == p["con_id"] and o["working"]
                        and o["type"] in ("stop", "trail") and o["side"] == exit_side)
            positions.append({**_jsonable(p), "symbol_id": self._symbol_for_con(p["con_id"]),
                              "protected": cover >= abs(p["qty"]), "stop_cover": cover})
        return {
            "available": True, "connection": self._status, "account": self.account, "mode": self.mode,
            "one_click": self.mode == "auto-within-limits", "halt": self._halt_state(),
            "reconciliation": self._recon, "killswitch": {"healthy": self._killswitch_ok,
                                                          "port": self.config.execution.killswitch_port},
            "daily_pnl": _s(self.broker.daily_pnl()), "available_funds": _s(self.broker.available_funds()),
            "positions": positions, "orders": orders,
            "limits": {"max_contracts_per_symbol": self.config.risk.max_contracts_per_symbol,
                       "max_daily_loss_usd": str(self.config.risk.max_daily_loss_usd),
                       "symbol_allowlist": list(self.config.risk.symbol_allowlist)},
            "as_of": self._now(),
        }

    def _state_offline(self) -> dict[str, Any]:
        return {"available": True, "connection": self._status, "account": self.broker.account, "mode": self.mode,
                "one_click": self.mode == "auto-within-limits", "halt": self._halt_state(),
                "reconciliation": self._recon, "killswitch": {"healthy": self._killswitch_ok,
                                                              "port": self.config.execution.killswitch_port},
                "daily_pnl": None, "available_funds": None, "positions": [], "orders": [],
                "limits": None, "as_of": self._now()}

    def _publish(self, force: bool = False) -> None:
        try:
            state = self._state() if self.broker.connected() and self.ledger is not None else self._state_offline()
        except Exception as exc:  # noqa: BLE001
            log.debug("state snapshot failed: %s", exc)
            return
        key = json.dumps({k: v for k, v in state.items() if k != "as_of"}, sort_keys=True, default=str)
        if force or key != self._published:
            self._published = key
            self.emit("execution.state", state)

    def _quality_report(self, date: str | None) -> dict[str, Any]:
        from genesis.agents.execution.execution_quality import daily_aggregate

        day = date or self.clock().date().isoformat()
        placed = filled = 0
        for o in self.ledger.orders(account_id=self.account, since=day):
            if o["order_type"] == "limit" and o["role"] == "entry" and o["ts"].startswith(day):
                placed += 1
                filled += self.ledger.order_state(self.account, o["client_order_id"]) == "filled"
        fills = self.quality.on(day)
        return {"aggregate": daily_aggregate(day, fills, limit_orders_placed=placed, limit_orders_filled=filled),
                "fills": [asdict(f) for f in self.quality.recent(50)]}

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------

    def _set_status(self, state: str, detail: str) -> None:
        if state != self._status["state"]:
            self.emit("broker.connection", {"broker": "ibkr-orders", "state": state, "detail": detail})
        self._status = {"state": state, "detail": detail, "since": self._now()}

    def _now(self) -> str:
        return self.clock().isoformat()

    def _audit(self, kind: str, data: dict[str, Any]) -> None:
        line = json.dumps({"at": self._now(), "kind": kind, **data}, default=str)
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with open(self.state_dir / "audit.jsonl", "a") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            log.error("audit write failed: %s — %s", exc, line)


def _jsonable(obj: Any) -> dict[str, Any]:
    d = asdict(obj) if hasattr(obj, "__dataclass_fields__") else dict(obj)
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in d.items()
            if k != "contract"}


def _ui_checks(decision: Decision) -> list[dict[str, str]]:
    """`RiskCheck` as the UI's event types spell it."""
    return [{"rule": c.id, "verdict": "pass" if c.result in ("pass", "not_built") else "fail",
             "value": c.detail, "limit": c.result} for c in decision.checks]


def _stub_proposal(order: dict[str, Any], info: ContractInfo) -> Proposal:
    """For orders placed after a restart, when the original proposal is gone."""
    return Proposal(id=order.get("proposal_id") or "", created=order["ts"], trace_id=order["trace_id"],
                    symbol_id=info.symbol_id, root=info.root, local_symbol=info.local_symbol, con_id=info.con_id,
                    multiplier=info.multiplier, min_tick=info.min_tick, side=order["side"], qty=int(order["qty"]),
                    order_type="market")


# --------------------------------------------------------------------------
# the process's one order manager
# --------------------------------------------------------------------------

_MANAGER: OrderManager | None = None


def current() -> OrderManager | None:
    return _MANAGER


def start(config: Config, emit: Emit, *, live_config: Any | None = None) -> OrderManager | None:
    global _MANAGER
    if _MANAGER is not None or not config.execution.enabled:
        return _MANAGER
    _MANAGER = OrderManager(config, emit, live_config=live_config)
    _MANAGER.start()
    return _MANAGER


def stop() -> None:
    global _MANAGER
    if _MANAGER is not None:
        _MANAGER.stop()
        _MANAGER = None
