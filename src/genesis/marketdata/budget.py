# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""The only code that knows a vendor's quota.

Market Data Plane.md makes this a structural claim rather than a tidiness one:
*"``budget.py`` is the only code that knows a vendor's quota. Agents never see
a 429; they see a store that either has the answer or honestly does not."*

That sentence has two halves and the second is the harder one. Centralising the
limit is easy. What is hard is that the budget must **refuse before the call**,
not translate the vendor's refusal afterwards -- because by the time a 429
arrives the damage is done: IBKR responds to sustained pacing violations by
disconnecting the session, and a disconnected session at 16:15 ET is a missed
ingest window, not a retryable error.

So the API is :meth:`Budget.check` (free, honest, no side effect) and
:meth:`Budget.consume` (records the spend). A caller asks permission and is
told no with a reason and a time to retry.

**State is persisted**, in SQLite via the house connection policy, because the
note requires it: *"quota state persisted, survives restart."* A daily quota
that resets when the daemon restarts is not a quota -- and the failure mode is
that a crash loop becomes a way to spend a vendor's entire day's allowance in
a minute.

Three rule shapes, and they exist because IBKR needs all three at once (see
:mod:`genesis.marketdata.interface`):

``window``       N events per rolling window, per key -- 60 per 10 minutes.
``min_interval`` a cooldown between two events on one key -- no identical
                 request within 15 seconds.
``daily_quota``  a calendar-day ceiling -- Alpha Vantage's 25 per *day*, which
                 Market Data Plane names as the thing that breaks the naive
                 tool-plane design.

This is a **reflex**. Deterministic, sub-millisecond, no model. A budget that
could be reasoned with is a budget that can be talked out of firing, and the
entire reason limits live here rather than in a prompt is that they cannot be.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from genesis.errors import TransientError
from genesis.marketdata.interface import BarRequest, PacingRule
from genesis.memory.db import connect, transaction

__all__ = ["SCHEMA", "Budget", "BudgetExceeded", "Decision"]


class BudgetExceeded(TransientError):
    """The vendor's limit would be breached. Retry after :attr:`retry_after`.

    ``transient`` is the correct class and it is worth being explicit about
    why: this is not a degradation and it is certainly not fatal. The data
    exists, the vendor will serve it, and the only problem is *when*. Marking
    it degraded would let a caller proceed with less when it should simply wait
    -- and the overnight pass has hours of slack, so waiting is nearly free.
    """

    def __init__(self, reason: str, *, retry_after: timedelta, rule: str) -> None:
        super().__init__(
            reason,
            spoken_summary="I'm at the data provider's rate limit; I'll get it shortly.",
        )
        self.retry_after = retry_after
        self.rule = rule


@dataclass(frozen=True)
class Decision:
    """The answer to "may I make this call?" -- always with a reason."""

    allowed: bool
    rule: str | None = None
    retry_after: timedelta = timedelta()
    reason: str = ""

    def raise_if_denied(self) -> None:
        if not self.allowed:
            raise BudgetExceeded(
                self.reason, retry_after=self.retry_after, rule=self.rule or "?"
            )


SCHEMA = """
CREATE TABLE IF NOT EXISTS spend (
    vendor      TEXT    NOT NULL,
    rule        TEXT    NOT NULL,
    bucket      TEXT    NOT NULL,
    at          TEXT    NOT NULL,      -- ISO-8601 UTC
    at_epoch    REAL    NOT NULL       -- for range scans without parsing
);
CREATE INDEX IF NOT EXISTS spend_lookup ON spend (vendor, rule, bucket, at_epoch);

CREATE TABLE IF NOT EXISTS daily (
    vendor      TEXT    NOT NULL,
    rule        TEXT    NOT NULL,
    day         TEXT    NOT NULL,      -- UTC calendar date
    used        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (vendor, rule, day)
);
"""

#: Spend rows older than this are pruned on write. The longest window any
#: vendor uses is IBKR's 10 minutes; an hour is generous and keeps the table
#: from growing without bound over a year of ingest.
_RETENTION = timedelta(hours=1)


class Budget:
    """Quota state for every vendor, persisted and shared.

    One instance per process. The rules come from each adapter's
    :class:`~genesis.marketdata.interface.AdapterCapabilities`, so a vendor's
    limits are declared next to the vendor and enforced here -- which is what
    lets IBKR's three simultaneous rules be expressed today, with no IBKR
    adapter needed to prove the mechanism works.
    """

    def __init__(self, path: Path | str = "~/.genesis/market/budget.db") -> None:
        self.conn: sqlite3.Connection = connect(path)
        self.conn.executescript(SCHEMA)
        self._rules: dict[str, tuple[PacingRule, ...]] = {}
        # Serialises check-then-consume. See `try_consume`.
        self._lock = threading.Lock()

    def register(self, vendor: str, rules: Iterable[PacingRule]) -> None:
        """Declare a vendor's limits. Idempotent; last call wins."""
        self._rules[vendor] = tuple(rules)

    def close(self) -> None:
        self.conn.close()

    # -- the two questions -------------------------------------------------

    def check(self, vendor: str, request: BarRequest, *, now: datetime | None = None) -> Decision:
        """May this call be made? Free, and has no side effect.

        Every rule is evaluated and the *most restrictive* denial is returned,
        rather than the first. A caller told to wait 2 seconds by one rule and
        600 by another must hear 600, or it will retry into a second denial and
        treat the vendor as flaky rather than as rate limited.
        """
        now = now or datetime.now(UTC)
        worst = Decision(allowed=True)
        for rule in self._rules.get(vendor, ()):
            decision = self._check_rule(vendor, rule, request, now)
            if not decision.allowed and decision.retry_after >= worst.retry_after:
                worst = decision
        return worst

    def consume(self, vendor: str, request: BarRequest, *, now: datetime | None = None) -> None:
        """Record that the call was made.

        Spent **before** the request goes out, not after a successful one.
        That is deliberate: a vendor counts a request against your quota
        whether or not it succeeds, so charging only for successes
        under-counts exactly when things are going wrong -- a run of failures
        would spend the real quota while this ledger showed room, and the
        pacing violation would arrive right after.

        Recorded per rule rather than once per request, because the buckets
        differ: one request is one event against the global 60-per-10-minutes
        and one event against that contract's 6-per-2-seconds.
        """
        now = now or datetime.now(UTC)
        rules = self._rules.get(vendor, ())
        if not rules:
            return
        with transaction(self.conn) as conn:
            for rule in rules:
                bucket = rule.key(request)
                conn.execute(
                    "INSERT INTO spend (vendor, rule, bucket, at, at_epoch) VALUES (?,?,?,?,?)",
                    (vendor, rule.name, bucket, now.isoformat(), now.timestamp()),
                )
                if rule.daily_quota is not None:
                    conn.execute(
                        "INSERT INTO daily (vendor, rule, day, used) VALUES (?,?,?,1) "
                        "ON CONFLICT (vendor, rule, day) "
                        "DO UPDATE SET used = used + 1",
                        (vendor, rule.name, now.date().isoformat()),
                    )
            conn.execute(
                "DELETE FROM spend WHERE at_epoch < ?",
                ((now - _RETENTION).timestamp(),),
            )

    def try_consume(
        self, vendor: str, request: BarRequest, *, now: datetime | None = None
    ) -> Decision:
        """Check and spend as one atomic step. Prefer this over check+consume.

        ``check`` then ``consume`` is two operations with a gap between them,
        and the gap is a real race rather than a theoretical one: ingest runs
        as several supervised daemon workers against one budget file, so two
        of them can both pass ``check`` on the last remaining slot and both
        spend it. The result is a pacing violation that the budget was
        supposed to make impossible -- and for IBKR, a sustained violation is
        a disconnected session at 16:15 ET, not a retryable error.

        Holding the lock across both closes it. The separate ``check`` and
        ``consume`` remain for the caller that genuinely needs them apart --
        asking "would this be allowed" without spending is useful for
        scheduling -- but the default path should be this one.
        """
        with self._lock:
            decision = self.check(vendor, request, now=now)
            if decision.allowed:
                self.consume(vendor, request, now=now)
            return decision

    # -- reporting ---------------------------------------------------------

    def used_today(self, vendor: str, rule: str, *, now: datetime | None = None) -> int:
        day = (now or datetime.now(UTC)).date().isoformat()
        row = self.conn.execute(
            "SELECT used FROM daily WHERE vendor=? AND rule=? AND day=?",
            (vendor, rule, day),
        ).fetchone()
        return int(row["used"]) if row else 0

    # -- internals ---------------------------------------------------------

    def _check_rule(
        self, vendor: str, rule: PacingRule, request: BarRequest, now: datetime
    ) -> Decision:
        bucket = rule.key(request)

        if rule.daily_quota is not None:
            used = self.used_today(vendor, rule.name, now=now)
            if used >= rule.daily_quota:
                midnight = datetime.combine(
                    now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
                )
                return Decision(
                    False,
                    rule.name,
                    midnight - now,
                    f"{vendor}: daily quota {rule.daily_quota} exhausted "
                    f"({used} used). Resets at UTC midnight.",
                )

        if rule.min_interval is not None:
            row = self.conn.execute(
                "SELECT MAX(at_epoch) AS last FROM spend "
                "WHERE vendor=? AND rule=? AND bucket=?",
                (vendor, rule.name, bucket),
            ).fetchone()
            last = row["last"] if row else None
            if last is not None:
                elapsed = timedelta(seconds=now.timestamp() - float(last))
                if elapsed < rule.min_interval:
                    return Decision(
                        False,
                        rule.name,
                        rule.min_interval - elapsed,
                        f"{vendor}: {rule.name} needs "
                        f"{rule.min_interval.total_seconds():.0f}s between identical "
                        f"requests; {elapsed.total_seconds():.1f}s elapsed.",
                    )

        if rule.limit is not None:
            since = (now - rule.window).timestamp()
            row = self.conn.execute(
                "SELECT COUNT(*) AS n, MIN(at_epoch) AS oldest FROM spend "
                "WHERE vendor=? AND rule=? AND bucket=? AND at_epoch >= ?",
                (vendor, rule.name, bucket, since),
            ).fetchone()
            count = int(row["n"]) if row else 0
            if count >= rule.limit:
                # Retry when the oldest event in the window ages out -- that is
                # the exact moment a slot frees. A fixed backoff would either
                # wake early (and be denied again) or waste the difference.
                oldest = float(row["oldest"])
                free_at = oldest + rule.window.total_seconds()
                return Decision(
                    False,
                    rule.name,
                    timedelta(seconds=max(0.0, free_at - now.timestamp())),
                    f"{vendor}: {rule.name} allows {rule.limit} per "
                    f"{rule.window.total_seconds():.0f}s on '{bucket}'; "
                    f"{count} already spent.",
                )

        return Decision(allowed=True)
