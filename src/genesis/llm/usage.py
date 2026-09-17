# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""What the brain actually cost, recorded per call.

``daily_token_budget`` has been in the config since the tier table was written
and was read by nothing, which is the shape of problem Biological Design calls
proprioceptive drift: a limit the system believes it has and cannot perceive.
The sense came first, deliberately -- an actuator with no feedback is the wrong
order (Biological Design §proprioception). It exists now, so :class:`Budget` is
the regulator that was waiting on it: the day's spend is read once, tracked in
memory as calls land, and a hosted call past the ceiling raises
:class:`~genesis.errors.DegradedError` instead of spending money that is not
there.

**A spent budget degrades; it never halts.** Every deterministic path -- the
risk engine, the accountant, the level watcher, the kill switch -- has no model
in it and keeps working, which is the whole point of putting them at
``tier: none``. So the failure class is `degraded`, "proceed with less and
label it", and the ladder's existing degraded modes carry it.

Two decisions worth stating.

**Token counts come from the provider, never from a local estimate.** A budget
enforced against our own tokeniser is a budget that disagrees with the invoice.
Where a provider does not report usage the row stores zero, which reads as
"not counted" rather than "free".

**Recording never fails a call.** :class:`MeteredBackend` swallows storage
errors, because a locked database must not turn a good answer into an
exception. The meter is instrumentation, and instrumentation that can take down
the thing it measures is a worse bug than the gap in the data.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genesis.errors import DegradedError
from genesis.llm.backend import Completion
from genesis.memory.db import connect, transaction

__all__ = ["Budget", "MeteredBackend", "PRICES", "TierUsage", "UsageLog", "estimate_cost"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT    NOT NULL,
    day           TEXT    NOT NULL,
    tier          TEXT    NOT NULL,
    backend       TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    latency_ms    REAL    NOT NULL,
    ok            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_usage_day ON llm_usage(day, tier);
"""

#: USD per million tokens, (input, output). Priced 2026-09-07 -- a stale number
#: here shows a wrong dollar figure, never a wrong token count, which is why
#: the panel leads with tokens and treats cost as an estimate. A model absent
#: from this table costs nothing to run (local) or is simply unpriced.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Dollars, or ``None`` when the model is not in :data:`PRICES`.

    ``None`` rather than ``0.0``: a free local model and an unpriced hosted one
    are different facts, and showing "$0.00" for the second is a lie the
    operator would act on.
    """
    for name, (sent, received) in PRICES.items():
        if model.startswith(name):
            return (input_tokens * sent + output_tokens * received) / 1_000_000
    return None


@dataclass(frozen=True)
class TierUsage:
    tier: str
    backend: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    p50_latency_ms: float
    failures: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float | None:
        return estimate_cost(self.model, self.input_tokens, self.output_tokens)


class UsageLog:
    """Append-only record of every model call."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connect(self.path)
            self._conn.executescript(SCHEMA)
        return self._conn

    def record(
        self,
        *,
        tier: str,
        backend: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        ok: bool = True,
        now: datetime | None = None,
    ) -> None:
        at = now or datetime.now(UTC)
        with self._lock, transaction(self.conn) as conn:
            conn.execute(
                "INSERT INTO llm_usage (at, day, tier, backend, model, input_tokens,"
                " output_tokens, latency_ms, ok) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    at.isoformat(),
                    at.date().isoformat(),
                    tier,
                    backend,
                    model,
                    int(input_tokens),
                    int(output_tokens),
                    float(latency_ms),
                    int(ok),
                ),
            )

    def by_tier(self, *, day: str | None = None) -> list[TierUsage]:
        """One row per tier for ``day`` (default: today, UTC)."""
        day = day or datetime.now(UTC).date().isoformat()
        rows = self.conn.execute(
            "SELECT tier, backend, model, COUNT(*) AS calls,"
            " SUM(input_tokens) AS sent, SUM(output_tokens) AS received,"
            " SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failures"
            " FROM llm_usage WHERE day = ?"
            " GROUP BY tier, backend, model ORDER BY sent + received DESC",
            (day,),
        ).fetchall()
        out = []
        for row in rows:
            latencies = [
                r[0]
                for r in self.conn.execute(
                    "SELECT latency_ms FROM llm_usage WHERE day = ? AND tier = ?"
                    " AND model = ? ORDER BY latency_ms",
                    (day, row["tier"], row["model"]),
                ).fetchall()
            ]
            out.append(
                TierUsage(
                    tier=row["tier"],
                    backend=row["backend"],
                    model=row["model"],
                    calls=row["calls"],
                    input_tokens=row["sent"] or 0,
                    output_tokens=row["received"] or 0,
                    p50_latency_ms=latencies[len(latencies) // 2] if latencies else 0.0,
                    failures=row["failures"] or 0,
                )
            )
        return out

    def daily_totals(self, *, days: int = 14) -> list[tuple[str, int, int]]:
        """``(day, input_tokens, output_tokens)`` newest last, for the sparkline."""
        rows = self.conn.execute(
            "SELECT day, SUM(input_tokens), SUM(output_tokens) FROM llm_usage"
            " GROUP BY day ORDER BY day DESC LIMIT ?",
            (days,),
        ).fetchall()
        return [(r[0], r[1] or 0, r[2] or 0) for r in reversed(rows)]

    def tokens_today(self) -> int:
        row = self.conn.execute(
            "SELECT SUM(input_tokens + output_tokens) FROM llm_usage WHERE day = ?",
            (datetime.now(UTC).date().isoformat(),),
        ).fetchone()
        return int(row[0] or 0)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class Budget:
    """The day's token ceiling, and the refusal when it is spent.

    One per process, shared by every tier, because the budget is a property of
    the day and not of a model.

    **The count is read from the meter once and then kept in memory.** A
    ``SELECT SUM(...)`` before every call would put a disk read on the hot path
    to enforce a limit that moves by a few thousand tokens at a time. The
    in-memory count can only drift *low* -- another process spending against
    the same budget is invisible until the day rolls over -- and drifting low
    means the ceiling is a little generous rather than a little arbitrary.

    ``daily_tokens <= 0`` disables the ceiling, which is how an install with no
    budget opinion behaves: the meter still records everything.
    """

    def __init__(self, log: UsageLog, *, daily_tokens: int, clock: Any = None) -> None:
        self._log = log
        self.daily_tokens = int(daily_tokens)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._day: str | None = None
        self._spent = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        """Re-read from the meter on the first call of a new day."""
        day = self._clock().date().isoformat()
        if day != self._day:
            self._day = day
            try:
                self._spent = self._log.tokens_today()
            except Exception:  # noqa: BLE001
                # The meter is instrumentation and may be unreadable. Starting
                # the day at zero is the generous direction; refusing every
                # call because the *counter* is broken would take the system
                # down to protect a cost limit, which is the wrong trade.
                self._spent = 0

    @property
    def spent(self) -> int:
        with self._lock:
            self._roll()
            return self._spent

    @property
    def exhausted(self) -> bool:
        return self.daily_tokens > 0 and self.spent >= self.daily_tokens

    def add(self, tokens: int) -> None:
        with self._lock:
            self._roll()
            self._spent += int(tokens)

    def check(self, tier: str) -> None:
        """Raise if this call would spend past the ceiling."""
        if self.exhausted:
            raise DegradedError(
                f"the day's token budget is spent — {self.spent:,} of "
                f"{self.daily_tokens:,} tokens used, so the {tier} tier is "
                f"closed until midnight UTC",
                spoken_summary="I've spent today's model budget, so I'm working without a model.",
            )


class MeteredBackend:
    """Any backend, plus a usage row per call.

    A wrapper rather than a base class so it composes with every backend --
    including ones added later -- and so the recording concern stays out of the
    three provider implementations, which already have enough to get right.
    """

    def __init__(
        self,
        inner: Any,
        *,
        tier: str,
        backend: str,
        log: UsageLog,
        budget: Budget | None = None,
    ) -> None:
        self._inner = inner
        self._tier = tier
        self._backend = backend
        self._log = log
        self._budget = budget

    @property
    def model(self) -> str:
        return self._inner.model

    def __getattr__(self, name: str) -> Any:
        # `see`, `run_tools`, `close` and anything else provider-specific.
        return getattr(self._inner, name)

    def complete(self, prompt: str, **kwargs: Any) -> Completion:
        if self._budget is not None:
            self._budget.check(self._tier)
        try:
            reply = self._inner.complete(prompt, **kwargs)
        except Exception:
            self._write(0, 0, 0.0, ok=False)
            raise
        self._write(reply.input_tokens, reply.output_tokens, reply.latency_ms, ok=True)
        if self._budget is not None:
            self._budget.add(reply.input_tokens + reply.output_tokens)
        return reply

    def _write(self, sent: int, received: int, latency_ms: float, *, ok: bool) -> None:
        try:
            self._log.record(
                tier=self._tier,
                backend=self._backend,
                model=self.model,
                input_tokens=sent,
                output_tokens=received,
                latency_ms=latency_ms,
                ok=ok,
            )
        except Exception:  # noqa: BLE001 - the meter never breaks the call
            pass
