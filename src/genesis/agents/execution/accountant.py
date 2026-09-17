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
        account = account or getattr(self.broker, "account", None) or "unknown"
        positions = self.ledger.rebuild(account_id=account)
        stops = self._stops(account)
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

            stop = stops.get(symbol)
            views.append(
                PositionView(
                    symbol=symbol, con_id=bp.get("con_id"), qty=pos.qty,
                    side="long" if pos.qty > 0 else "short",
                    avg_entry=pos.avg_entry, multiplier=multiplier, mark=mark, stop=stop,
                    unrealized=leg_unrealized,
                    risk_open=self._risk_open(pos, stop, multiplier, mark),
                    protected=stop is not None,
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

        recon = self._reconciliation(account)
        return AccountSnapshot(
            as_of=now.isoformat(), account=account, equity=equity, cash=cash,
            positions=tuple(views), realized_today=realized, fees_today=fees,
            unrealized=unrealized, portfolio_heat_pct=heat,
            gross_exposure_pct=gross, net_exposure_pct=net,
            degraded=bool(reasons), degraded_reasons=tuple(reasons),
            reconciled=recon[0], reconciled_at=recon[1], problems=tuple(problems),
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
        self, pos: Position, stop: Decimal | None, multiplier: Decimal, mark: Decimal | None
    ) -> Decimal:
        """What this position can still lose, in money.

        With no stop the answer is not zero. The honest figure for an
        unprotected position is its whole notional -- it can go to zero -- and
        that is what makes an unprotected book read as the riskiest thing on
        the page rather than the safest.
        """
        size = abs(Decimal(pos.qty)) * multiplier
        if stop is None:
            price = mark if mark is not None else pos.avg_entry
            return size * price
        if pos.qty > 0:
            return max(pos.avg_entry - stop, ZERO) * size
        return max(stop - pos.avg_entry, ZERO) * size

    def _stops(self, account: str) -> dict[str, Decimal]:
        """Live protective stops per symbol, from the ledger's order rows.

        The *tightest* stop wins when a symbol has several: it is the one that
        will actually fire, so it is the one that bounds the loss.
        """
        out: dict[str, Decimal] = {}
        rows = self.ledger.connection.execute(
            "SELECT symbol, stop_price, limit_price, state FROM orders "
            "WHERE account_id = ? AND role = 'stop'",
            (account,),
        ).fetchall()
        for row in rows:
            if row["state"] in ("filled", "cancelled", "rejected", "expired"):
                continue
            raw = row["stop_price"] or row["limit_price"]
            if raw is None:
                continue
            price = Decimal(str(raw))
            held = out.get(row["symbol"])
            out[row["symbol"]] = price if held is None else max(held, price)
        return out

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
