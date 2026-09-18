# Spec: Genesis Markdown/20-Agents/Execution/Agent — Position And PnL Accountant.md
"""Agent — Position And PnL Accountant. What you own, what it cost, what it's worth.

**The sense that verifies the muscle acted.** Biological Design §3: an agent
that can act but cannot accurately perceive its own state is the dangerous
configuration, and its failure mode -- the broker's real position diverging
from what the system believes -- is the one that loses money *quietly*. The
order manager could already place, protect and reconcile before this existed,
which is the wrong order; this is the correction.

No model, ever. Every number here is arithmetic over fills, and
:class:`~genesis.agents.base.AgentDeclaration` refuses a model tier for the
execution family at load time.

Three decisions worth stating, because each one is a place this could be
plausibly wrong:

**Position truth is the fills, not the position table.** :func:`rebuild_positions`
folds the append-only fill log; the ``positions`` table is a cache of that fold
and this agent never trusts it. A cache disagreeing with its source is a bug to
report, not a value to use, so the disagreement is an integrity finding.

**Portfolio heat is what can still happen.** Unrealised P&L says what already
happened. Heat is Σ (entry − stop) × size × multiplier over open positions as a
percentage of equity, and it is the number [[Pre-Trade Risk Engine]] check #8
reads. A position with **no protective stop** contributes its *whole notional*
to heat rather than zero -- the naive reading of "entry minus stop" for a
missing stop is zero risk, which is exactly backwards, and getting this wrong
would make an unprotected book look safest.

**Protection is read from the broker's working orders, not the ledger.** The
ledger's ``orders`` table is append-only, so its ``state`` column is the state
an order was *born* in and its ``stop_price`` is the price it was *placed* at.
A cancelled stop still reads ``accepted`` there, and a trailed stop still reads
its first price. Both errors understate risk, which is the wrong direction for
the number the risk engine sizes against. The broker's live order book is the
truth; the ledger is the offline fallback, read through its event log, and a
snapshot built from it says so.

**Each stop protects only its own quantity.** One stop for 1 contract on a
2-contract position leaves 1 contract unprotected, and that contract
contributes its whole notional. Coverage is summed per stop, loosest first, so
an over-covered position is still measured at its worst.

**A stale quote makes the whole snapshot degraded.** Unrealised P&L is only as
good as its marks. Past the staleness threshold the snapshot says so, spoken
P&L is prefixed "on delayed data", and ``auto-within-limits`` is suspended --
because sizing against a fifteen-minute-old mark is sizing against fiction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable

from genesis.agents.base import AgentDeclaration
from genesis.memory.ledger import Position, rebuild_positions

__all__ = [
    "DECLARATION",
    "Accountant",
    "AccountSnapshot",
    "PositionView",
    "STALE_QUOTE_MS",
]

DECLARATION = AgentDeclaration(
    id="position-accountant",
    name="Position And PnL Accountant",
    family="execution",
    cadence=[
        {"type": "event", "on": ["order.filled", "position.changed"]},
        {"type": "market-open", "interval_sec": 30},
        {"type": "cron", "at": "16:15"},
    ],
    tools=["memory.read", "market-data.quote", "genesis-execution.positions",
           "genesis-execution.account"],
    memory={"read": ["ledger", "shared", "order-manager"], "write": ["position-accountant"]},
    model_tier="none",
    timeout_sec=15,
)

ZERO = Decimal(0)

#: Past this, marks are not a basis for sizing. IBKR's free feed is delayed by
#: ten to fifteen minutes, so on that feed the snapshot is *always* degraded
#: and says so -- which is the honest reading, not a threshold to relax until
#: it stops complaining.
STALE_QUOTE_MS = 5_000


@dataclass(frozen=True)
class PositionView:
    """One open position, marked. Money is ``Decimal`` all the way through."""

    symbol: str
    con_id: int | None
    qty: int
    side: str
    avg_entry: Decimal
    multiplier: Decimal
    mark: Decimal | None
    stop: Decimal | None
    unrealized: Decimal | None
    risk_open: Decimal
    protected: bool
    quote_age_ms: int | None
    quote_source: str | None
    strategy: str | None
    #: Contracts covered by a working exit stop. ``protected`` is this ≥ |qty|.
    covered: int = 0

    @property
    def notional(self) -> Decimal:
        price = self.mark if self.mark is not None else self.avg_entry
        return abs(Decimal(self.qty)) * price * self.multiplier

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "con_id": self.con_id, "qty": self.qty, "side": self.side,
            "avg_entry": str(self.avg_entry), "multiplier": str(self.multiplier),
            "mark": None if self.mark is None else str(self.mark),
            "stop": None if self.stop is None else str(self.stop),
            "unrealized": None if self.unrealized is None else str(self.unrealized),
            "risk_open": str(self.risk_open), "protected": self.protected,
            "covered": self.covered,
            "quote_age_ms": self.quote_age_ms, "quote_source": self.quote_source,
            "strategy": self.strategy,
        }


@dataclass(frozen=True)
class AccountSnapshot:
    """The answer every other component asks for instead of computing its own."""

    as_of: str
    account: str
    equity: Decimal | None
    cash: Decimal | None
    positions: tuple[PositionView, ...] = ()
    realized_today: Decimal = ZERO
    fees_today: Decimal = ZERO
    unrealized: Decimal | None = None
    portfolio_heat_pct: Decimal | None = None
    gross_exposure_pct: Decimal | None = None
    net_exposure_pct: Decimal | None = None
    degraded: bool = False
    degraded_reasons: tuple[str, ...] = ()
    reconciled: bool | None = None
    reconciled_at: str | None = None
    problems: tuple[str, ...] = ()
    #: Worst case of entries not yet filled. ``None`` when it cannot be known.
    pending_risk: Decimal | None = ZERO

    @property
    def open_risk(self) -> Decimal | None:
        """Everything that can still be lost: filled positions plus working entries.

        ``None`` when the pending half is unknown -- the risk engine then
        refuses to open, because a heat check against half the book is the
        check that passes the order it should have stopped.
        """
        if self.pending_risk is None:
            return None
        return sum((v.risk_open for v in self.positions), ZERO) + self.pending_risk

    @property
    def net_today(self) -> Decimal | None:
        if self.unrealized is None:
            return None
        return self.realized_today + self.unrealized

    @property
    def auto_mode_permitted(self) -> bool:
        """Approval Modes: ``auto-within-limits`` is suspended while degraded.

        Also suspended by an unresolved reconciliation, because auto mode on a
        book the system cannot verify is the configuration this whole note
        exists to prevent.
        """
        return not self.degraded and self.reconciled is not False and not self.problems

    def to_dict(self) -> dict[str, Any]:
        def money(v: Decimal | None) -> str | None:
            return None if v is None else str(v)

        return {
            "as_of": self.as_of, "account": self.account,
            "equity": money(self.equity), "cash": money(self.cash),
            "positions": [p.to_dict() for p in self.positions],
            "pnl": {
                "realized_today": money(self.realized_today),
                "unrealized": money(self.unrealized),
                "net_today": money(self.net_today),
                "fees_today": money(self.fees_today),
            },
            "exposure": {
                "gross_pct": money(self.gross_exposure_pct),
                "net_pct": money(self.net_exposure_pct),
            },
            "portfolio_heat_pct": money(self.portfolio_heat_pct),
            "pending_risk": money(self.pending_risk),
            "open_risk": money(self.open_risk),
            "degraded": self.degraded,
            "degraded_reasons": list(self.degraded_reasons),
            "reconciled": self.reconciled,
            "reconciled_at": self.reconciled_at,
            "problems": list(self.problems),
            "auto_mode_permitted": self.auto_mode_permitted,
        }


@dataclass
class Accountant:
    """Reads the ledger and the broker; computes; writes nothing to the ledger.

    The note called this the ledger's only writer. It is not, and the note now
    says so: the order manager writes fills because it is the component holding
    the broker callback, and a second writer to an append-only ledger is two
    components racing to record the same fill. What matters is the *single*
    writer, not which one -- so this agent is pure derivation, which also makes
    it safe to run anywhere, including read-only in the UI.
    """

    ledger: Any
    broker: Any = None
    #: ``(symbol_or_con_id) -> {"mid": Decimal, "ts": iso, "source": str}``.
    quote: Callable[[Any], dict[str, Any] | None] | None = None
    #: ``con_id -> symbol_id``. **Not optional in practice.** The ledger's
    #: symbol space is the instrument id (``FUT:CME:NQ:2026-12``); the broker
    #: reports ``NQZ6``. Comparing the two spellings directly makes every real
    #: position look like a reconciliation mismatch, which is a *halt*. Where
    #: no resolver is given, the ledger's own con-id map is used and an
    #: unresolvable broker position is reported as one the ledger does not know
    #: -- which it is.
    symbol_for_con: Callable[[int], str | None] | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    stale_quote_ms: int = STALE_QUOTE_MS

    # ------------------------------------------------------------------

    def snapshot(self, *, account: str | None = None) -> AccountSnapshot:
        now = self.clock()
        account = account or getattr(self.broker, "account", None) or self._ledger_account()
        positions = self.ledger.rebuild(account_id=account)
        stops, stop_source = self._stops(account)
        broker_positions = self._broker_positions()

        views: list[PositionView] = []
        reasons: list[str] = []
        problems = list(self._cache_drift(account, positions))
        unrealized: Decimal | None = ZERO

        for (_, symbol), pos in sorted(positions.items()):
            if pos.is_flat:
                continue
            bp = broker_positions.get(symbol, {})
            multiplier = Decimal(str(bp.get("multiplier") or 1))
            mark, age_ms, source = self._mark(symbol, bp)
            if mark is None:
                reasons.append(f"no mark for {symbol}")
                unrealized = None
            elif age_ms is not None and age_ms > self.stale_quote_ms:
                reasons.append(f"{symbol} mark is {age_ms} ms old ({source or 'unknown feed'})")

            leg_unrealized = (
                None if mark is None
                else (mark - pos.avg_entry) * Decimal(pos.qty) * multiplier
            )
            if leg_unrealized is not None and unrealized is not None:
                unrealized += leg_unrealized

            exits = [
                (price, qty) for price, qty, side in stops.get(symbol, [])
                if side == ("sell" if pos.qty > 0 else "buy")
            ]
            risk, covered = self._risk_open(pos, exits, multiplier, mark)
            views.append(
                PositionView(
                    symbol=symbol, con_id=bp.get("con_id"), qty=pos.qty,
                    side="long" if pos.qty > 0 else "short",
                    avg_entry=pos.avg_entry, multiplier=multiplier, mark=mark,
                    stop=self._tightest(exits, long=pos.qty > 0),
                    unrealized=leg_unrealized, risk_open=risk,
                    protected=covered >= abs(pos.qty), covered=covered,
                    quote_age_ms=age_ms, quote_source=source, strategy=None,
                )
            )

        equity = self._equity(views)
        cash = self._decimal(getattr(self.broker, "available_funds", None))
        realized, fees = self._today(account, now)

        heat = None
        if equity and equity > ZERO:
            heat = (sum((v.risk_open for v in views), ZERO) / equity) * Decimal(100)
        gross = net = None
        if equity and equity > ZERO:
            gross = (sum((v.notional for v in views), ZERO) / equity) * Decimal(100)
            net = (
                sum(((v.notional if v.qty > 0 else -v.notional) for v in views), ZERO) / equity
            ) * Decimal(100)

        unprotected = [v.symbol for v in views if not v.protected]
        if unprotected:
            problems.append(f"no protective stop on {', '.join(unprotected)}")
        if stop_source == "ledger" and views:
            reasons.append("stops read from the ledger, not the broker's live orders")

        pending = self.pending_risk()
        if pending is None:
            # Unknown, not zero: a heat figure over half the book is the one
            # that passes the order it should have stopped.
            heat = None
            problems.append("a working entry has no measurable stop — heat is unknown")
        elif heat is not None and equity:
            heat += (pending / equity) * Decimal(100)

        recon = self._reconciliation(account)
        return AccountSnapshot(
            as_of=now.isoformat(), account=account, equity=equity, cash=cash,
            positions=tuple(views), realized_today=realized, fees_today=fees,
            unrealized=unrealized, portfolio_heat_pct=heat,
            gross_exposure_pct=gross, net_exposure_pct=net,
            degraded=bool(reasons), degraded_reasons=tuple(reasons),
            reconciled=recon[0], reconciled_at=recon[1], problems=tuple(problems),
            pending_risk=pending,
        )

    # ------------------------------------------------------------------
    # 16:15, and every reconnect
    # ------------------------------------------------------------------

    def reconcile(self, *, account: str | None = None) -> dict[str, Any]:
        """Ledger against the broker's own report. **Zero tolerance.**

        There is no "small" mismatch: a one-share discrepancy means the ledger
        and reality have diverged and every risk calculation downstream is now
        unreliable. The caller halts on ``matched is False``; this returns the
        finding rather than halting itself, so that the component holding the
        halt flag stays the only one that engages it.
        """
        account = account or getattr(self.broker, "account", None) or "unknown"
        if self.broker is None or not getattr(self.broker, "connected", lambda: False)():
            return {
                "matched": None,
                "detail": "the broker is unreachable — position truth is unknown",
                "problems": ["broker unreachable"],
                "at": self.clock().isoformat(),
            }

        ours = {
            symbol: pos.qty
            for (_, symbol), pos in self.ledger.rebuild(account_id=account).items()
            if not pos.is_flat
        }
        theirs: dict[str, int] = {}
        for p in self.broker.positions():
            qty = int(p.get("qty") or 0)
            if qty:
                key = self._resolve(p)
                theirs[key] = theirs.get(key, 0) + qty
        problems = [
            f"{symbol}: ledger {ours.get(symbol, 0)} vs broker {theirs.get(symbol, 0)}"
            for symbol in sorted(set(ours) | set(theirs))
            if ours.get(symbol, 0) != theirs.get(symbol, 0)
        ]
        matched = not problems
        detail = "ledger and broker agree" if matched else "; ".join(problems)
        at = self.clock().isoformat()
        try:
            self.ledger.record_reconciliation(account, matched, detail, at)
        except Exception:  # noqa: BLE001 - the finding matters more than the record
            pass
        return {"matched": matched, "detail": detail, "problems": problems, "at": at}

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _risk_open(
        self,
        pos: Position,
        exits: list[tuple[Decimal, int]],
        multiplier: Decimal,
        mark: Decimal | None,
    ) -> tuple[Decimal, int]:
        """What this position can still lose, in money, and how much is covered.

        Each exit stop covers its own quantity at its own price. Loosest first,
        so an over-covered position is measured at its worst rather than its
        best. Whatever no stop covers contributes its whole notional: it can go
        to zero, and that is what makes an unprotected book read as the
        riskiest thing on the page rather than the safest.
        """
        long = pos.qty > 0
        left = abs(pos.qty)
        risk = ZERO
        covered = 0
        # Loosest first: lowest stop for a long, highest for a short.
        for price, qty in sorted(exits, key=lambda e: e[0], reverse=not long):
            take = min(left, max(qty, 0))
            if take <= 0:
                continue
            distance = (pos.avg_entry - price) if long else (price - pos.avg_entry)
            risk += max(distance, ZERO) * Decimal(take) * multiplier
            covered += take
            left -= take
            if left == 0:
                break
        if left:
            price = mark if mark is not None else pos.avg_entry
            risk += Decimal(left) * price * multiplier
        return risk, covered

    @staticmethod
    def _tightest(exits: list[tuple[Decimal, int]], *, long: bool) -> Decimal | None:
        """The stop that fires first -- highest for a long, lowest for a short."""
        if not exits:
            return None
        prices = [price for price, _ in exits]
        return max(prices) if long else min(prices)

    def _stops(self, account: str) -> tuple[dict[str, list[tuple[Decimal, int, str]]], str]:
        """Working stop orders per symbol: ``(price, remaining qty, side)``.

        From the broker's live order book whenever there is a broker, because
        the ledger holds only what an order was born as. Offline, from the
        ledger through its event log -- and only orders whose *latest* event is
        a live state count. An order whose state is unknown is not counted: not
        counting a live stop overstates risk, counting a dead one understates
        it, and only one of those is safe.
        """
        out: dict[str, list[tuple[Decimal, int, str]]] = {}
        if self.broker is not None:
            try:
                book = self.broker.open_orders()
            except Exception:  # noqa: BLE001
                book = None
            if book is not None:
                for v in book:
                    if not v.get("working") or v.get("type") not in ("stop", "trail"):
                        continue
                    if v.get("stop") is None:
                        continue  # a trail with no stop price yet protects nothing measurable
                    remaining = int(float(v.get("remaining") or v.get("qty") or 0))
                    out.setdefault(self._resolve(v), []).append(
                        (Decimal(str(v["stop"])), remaining, str(v.get("side")))
                    )
                return out, "broker"

        live = ("submitted", "accepted", "partially_filled")
        rows = self.ledger.connection.execute(
            "SELECT client_order_id, symbol, side, qty, stop_price FROM orders "
            "WHERE account_id = ? AND role = 'stop'",
            (account,),
        ).fetchall()
        for row in rows:
            if row["stop_price"] is None:
                continue
            if self.ledger.order_state(account, row["client_order_id"]) not in live:
                continue
            out.setdefault(row["symbol"], []).append(
                (Decimal(str(row["stop_price"])), int(row["qty"]), str(row["side"]))
            )
        return out, "ledger"

    def pending_risk(self) -> Decimal | None:
        """Worst case of entry orders that are working and not yet filled.

        Heat over filled positions alone lets two quick entries both pass
        before either fills -- "worst case, always" says they count now. Each
        working entry is measured against the bracket stop the broker holds for
        it: ``|entry − stop| × remaining × multiplier``.

        ``None`` -- which makes the risk engine refuse to open -- when an entry
        has no measurable stop. The spec makes a stop mandatory on every order
        that opens risk, so a working entry without one is an anomaly, and the
        heat it adds is unknown rather than zero.
        """
        if self.broker is None:
            return ZERO
        try:
            book = self.broker.open_orders()
        except Exception:  # noqa: BLE001
            return None
        account = getattr(self.broker, "account", None) or "unknown"
        total = ZERO
        for v in book:
            if not v.get("working") or v.get("type") in ("stop", "trail"):
                continue
            order = self.ledger.order(account, v["ref"]) if v.get("ref") else None
            if not order or order.get("role") != "entry":
                continue
            child = next(
                (c for c in book
                 if c.get("working") and c.get("parent_id") == v.get("order_id")
                 and c.get("type") in ("stop", "trail")),
                None,
            )
            if child is None:
                return None
            remaining = Decimal(str(v.get("remaining") or v.get("qty") or 0))
            if child.get("type") == "trail" and child.get("trail") is not None:
                distance = Decimal(str(child["trail"]))
            else:
                ref = v.get("limit")
                if ref is None:
                    ref, _, _ = self._mark(str(v.get("con_id")), {"con_id": v.get("con_id")})
                if ref is None or child.get("stop") is None:
                    return None
                distance = abs(Decimal(str(ref)) - Decimal(str(child["stop"])))
            multiplier = self._multiplier(v.get("con_id"))
            if multiplier is None:
                return None
            total += distance * remaining * multiplier
        return total

    def _multiplier(self, con_id: Any) -> Decimal | None:
        """The contract's multiplier, from the broker. Never assumed to be 1.

        An NQ contract is $20 a point; guessing 1 would understate its risk
        twenty-fold.
        """
        info_for = getattr(self.broker, "info_for_con", None)
        if info_for is not None and con_id is not None:
            try:
                info = info_for(int(con_id))
            except Exception:  # noqa: BLE001
                info = None
            if info is not None and getattr(info, "multiplier", None) is not None:
                return Decimal(str(info.multiplier))
        for p in self._broker_positions().values():
            if p.get("con_id") == con_id and p.get("multiplier") is not None:
                return Decimal(str(p["multiplier"]))
        return None

    def _ledger_account(self) -> str:
        """The account to read when no broker names one.

        Offline, the only witness is the ledger. Falling back to the literal
        ``"unknown"`` asked it for an account that does not exist and reported
        the book as flat whatever it held -- the quiet kind of wrong. One
        account in the fills is unambiguous; several is surfaced, never picked.
        """
        rows = self.ledger.connection.execute(
            "SELECT DISTINCT account_id FROM fills"
        ).fetchall()
        accounts = sorted(r["account_id"] for r in rows)
        if len(accounts) == 1:
            return accounts[0]
        if accounts:
            raise ValueError(
                f"the ledger holds {len(accounts)} accounts ({', '.join(accounts)}) — name one"
            )
        return "unknown"

    def _resolve(self, p: dict[str, Any]) -> str:
        """The broker's position, named the way the ledger names it."""
        con_id = p.get("con_id")
        if con_id is not None:
            resolver = self.symbol_for_con
            if resolver is None and self.ledger is not None:
                resolver = getattr(self.ledger, "symbol_for_con_id", None)
            if resolver is not None:
                try:
                    known = resolver(int(con_id))
                except Exception:  # noqa: BLE001
                    known = None
                if known:
                    return str(known)
        return str(p.get("local_symbol") or p.get("root") or f"con:{con_id}")

    def _broker_positions(self) -> dict[str, dict[str, Any]]:
        if self.broker is None:
            return {}
        try:
            return {self._resolve(p): p for p in self.broker.positions()}
        except Exception:  # noqa: BLE001 - a dead gateway degrades the snapshot
            return {}

    def _mark(
        self, symbol: str, bp: dict[str, Any]
    ) -> tuple[Decimal | None, int | None, str | None]:
        if self.quote is None:
            return None, None, None
        try:
            q = self.quote(bp.get("con_id") or symbol)
        except Exception:  # noqa: BLE001
            return None, None, None
        if not q or q.get("mid") is None:
            return None, None, q.get("source") if q else None
        age = None
        ts = q.get("ts")
        if ts:
            try:
                age = int((self.clock() - datetime.fromisoformat(str(ts))).total_seconds() * 1000)
            except ValueError:
                age = None
        return Decimal(str(q["mid"])), age, q.get("source")

    def _cache_drift(self, account: str, rebuilt: dict[Any, Position]) -> list[str]:
        """The positions table against the fold it caches."""
        try:
            stored = self.ledger.stored_positions()
        except Exception:  # noqa: BLE001
            return []
        if not stored:
            return []
        out = []
        for key, pos in rebuilt.items():
            held = stored.get(key)
            if held is not None and held.qty != pos.qty:
                out.append(
                    f"position cache drift {key[1]}: fills say {pos.qty}, table says {held.qty}"
                )
        return out

    def _today(self, account: str, now: datetime) -> tuple[Decimal, Decimal]:
        """Realised P&L and fees since the session start, from the fills.

        The broker's own ``dailyPnL`` is what the risk engine's daily-loss
        check uses, deliberately -- it is the number the broker will enforce.
        This is the ledger's view of the same day, and the two disagreeing is
        worth seeing rather than smoothing over.
        """
        start = self._session_start(now)
        fills = [f for f in self.ledger.fills(account_id=account) if f.ts >= start]
        if not fills:
            return ZERO, ZERO
        positions = rebuild_positions(fills)
        realized = sum((p.realized_pnl for p in positions.values()), ZERO)
        fees = sum((f.fee for f in fills), ZERO)
        return realized, fees

    @staticmethod
    def _session_start(now: datetime) -> str:
        """18:00 New York the evening before -- the CME trading day."""
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        ny = now.astimezone(ZoneInfo("America/New_York"))
        start = ny.replace(hour=18, minute=0, second=0, microsecond=0)
        if ny < start:
            start -= timedelta(days=1)
        return start.astimezone(UTC).isoformat()

    def _equity(self, views: list[PositionView]) -> Decimal | None:
        """Net liquidation from the broker. Never the ledger's guess at it.

        Equity is the denominator of heat and both exposure figures, so a
        guessed equity would make three numbers wrong at once. With no broker
        there is no equity, and the percentages are ``None`` rather than
        computed against something invented.
        """
        return self._decimal(getattr(self.broker, "net_liquidation", None))

    @staticmethod
    def _decimal(getter: Any) -> Decimal | None:
        if getter is None:
            return None
        try:
            value = getter()
        except Exception:  # noqa: BLE001
            return None
        return None if value is None else Decimal(str(value))

    def _reconciliation(self, account: str) -> tuple[bool | None, str | None]:
        try:
            row = self.ledger.connection.execute(
                "SELECT matched, ts FROM reconciliations WHERE account_id = ? "
                "ORDER BY ts DESC LIMIT 1",
                (account,),
            ).fetchone()
        except Exception:  # noqa: BLE001
            return None, None
        if row is None:
            return None, None
        return bool(row["matched"]), row["ts"]
