# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""The budget, and specifically: can it express IBKR's three rules at once?

That question is the reason this module was written before any IBKR adapter
exists. If the answer were no, the Adapter Protocol would have been wrong and
the session brief said to stop and say so. These tests are the evidence that
the answer is yes -- IBKR's published limits are declared here as data and
enforced by code that has never heard of IBKR.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from genesis.marketdata.budget import Budget, BudgetExceeded
from genesis.marketdata.interface import BarRequest, PacingRule

T0 = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def req(symbol: str = "FUT:CME:ES:2025-12", tf: str = "1D", day: int = 1) -> BarRequest:
    return BarRequest(
        symbol_id=symbol,
        timeframe=tf,
        start=datetime(2026, 3, day, tzinfo=UTC),
        end=datetime(2026, 4, day, tzinfo=UTC),
    )


# IBKR's three published historical-data pacing rules, verbatim from the TWS
# API documentation, expressed in this module's vocabulary. Nothing in
# budget.py knows what IBKR is; these are just data.
IBKR_RULES = (
    PacingRule(
        name="sixty-per-ten-minutes",
        limit=60,
        window=timedelta(minutes=10),
        key=lambda r: "*",
    ),
    PacingRule(
        name="no-identical-within-15s",
        min_interval=timedelta(seconds=15),
        key=lambda r: r.fingerprint(),
    ),
    PacingRule(
        name="six-per-contract-per-2s",
        limit=6,
        window=timedelta(seconds=2),
        key=lambda r: r.symbol_id,
    ),
)


@pytest.fixture
def budget(tmp_path):
    b = Budget(tmp_path / "budget.db")
    yield b
    b.close()


def test_ibkr_sixty_per_ten_minutes(budget):
    budget.register("ibkr", IBKR_RULES)
    now = T0
    # Sixty distinct contracts, so only the global rule can bite.
    for i in range(60):
        r = req(symbol=f"FUT:CME:ES:2025-{(i % 12) + 1:02d}", day=(i % 27) + 1)
        assert budget.check("ibkr", r, now=now).allowed
        budget.consume("ibkr", r, now=now)
        now += timedelta(seconds=3)

    decision = budget.check("ibkr", req(day=28), now=now)
    assert not decision.allowed
    assert decision.rule == "sixty-per-ten-minutes"


def test_ibkr_identical_request_cooldown(budget):
    budget.register("ibkr", IBKR_RULES)
    budget.consume("ibkr", req(), now=T0)

    denied = budget.check("ibkr", req(), now=T0 + timedelta(seconds=10))
    assert not denied.allowed
    assert denied.rule == "no-identical-within-15s"
    assert 4 <= denied.retry_after.total_seconds() <= 5

    # A *different* window on the same contract is not identical.
    assert budget.check("ibkr", req(day=2), now=T0 + timedelta(seconds=10)).allowed
    # And the identical one is fine once the cooldown passes.
    assert budget.check("ibkr", req(), now=T0 + timedelta(seconds=16)).allowed


def test_ibkr_six_per_contract_per_two_seconds(budget):
    budget.register("ibkr", IBKR_RULES)
    now = T0
    for day in range(1, 7):
        r = req(day=day)
        assert budget.check("ibkr", r, now=now).allowed
        budget.consume("ibkr", r, now=now)

    denied = budget.check("ibkr", req(day=7), now=now)
    assert not denied.allowed
    assert denied.rule == "six-per-contract-per-2s"

    # A different contract is a different bucket, and is unaffected.
    other = req(symbol="FUT:CME:NQ:2025-12", day=7)
    assert budget.check("ibkr", other, now=now).allowed


def test_the_most_restrictive_denial_wins(budget):
    """A caller told 2s by one rule and 600s by another must hear 600.

    Otherwise it retries into a second denial and concludes the vendor is
    flaky rather than that it is rate limited.
    """
    budget.register(
        "v",
        (
            PacingRule(name="short", limit=1, window=timedelta(seconds=2)),
            PacingRule(name="long", limit=1, window=timedelta(seconds=600)),
        ),
    )
    budget.consume("v", req(), now=T0)
    denied = budget.check("v", req(), now=T0 + timedelta(seconds=1))
    assert denied.rule == "long"
    assert denied.retry_after.total_seconds() > 500


def test_daily_quota_survives_a_restart(tmp_path):
    """Market Data Plane: "quota state persisted, survives restart".

    A quota that resets on restart is not a quota -- a crash loop becomes a way
    to spend a vendor's whole day in a minute.
    """
    path = tmp_path / "budget.db"
    rules = (PacingRule(name="daily", daily_quota=3),)

    first = Budget(path)
    first.register("av", rules)
    for _ in range(3):
        first.consume("av", req(), now=T0)
    assert not first.check("av", req(), now=T0).allowed
    first.close()

    second = Budget(path)
    second.register("av", rules)
    assert second.used_today("av", "daily", now=T0) == 3
    assert not second.check("av", req(), now=T0).allowed
    second.close()


def test_denial_raises_a_transient_with_a_retry_time(budget):
    """Transient, not degraded: the data exists, only the timing is wrong."""
    budget.register("v", (PacingRule(name="r", limit=1, window=timedelta(seconds=30)),))
    budget.consume("v", req(), now=T0)

    with pytest.raises(BudgetExceeded) as caught:
        budget.check("v", req(), now=T0 + timedelta(seconds=5)).raise_if_denied()
    assert caught.value.failure_class == "transient"
    assert caught.value.retryable is True
    assert caught.value.retry_after.total_seconds() == pytest.approx(25, abs=1)


def test_an_unregistered_vendor_is_unlimited(budget):
    """A vendor with no declared rules is not silently blocked."""
    assert budget.check("nobody", req()).allowed


def test_try_consume_is_atomic_under_concurrency(tmp_path):
    """check-then-consume is two operations with a gap, and the gap is a real
    race: several supervised ingest workers share one budget file, so two can
    both pass `check` on the last slot and both spend it. For IBKR a sustained
    pacing violation is a disconnected session, not a retryable error."""
    import threading

    budget = Budget(tmp_path / "b.db")
    budget.register("v", (PacingRule(name="one", limit=1, window=timedelta(minutes=5)),))

    allowed: list[bool] = []
    barrier = threading.Barrier(8)

    def race() -> None:
        barrier.wait()  # maximise the overlap
        allowed.append(budget.try_consume("v", req(), now=T0).allowed)

    threads = [threading.Thread(target=race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(allowed) == 1, f"{sum(allowed)} callers spent a 1-slot budget"
    budget.close()


def test_try_consume_does_not_spend_when_denied(tmp_path):
    """A refusal must cost nothing, or a rate-limited caller digs deeper."""
    budget = Budget(tmp_path / "b.db")
    budget.register("v", (PacingRule(name="daily", daily_quota=1),))

    assert budget.try_consume("v", req(), now=T0).allowed is True
    assert budget.used_today("v", "daily", now=T0) == 1
    assert budget.try_consume("v", req(day=2), now=T0).allowed is False
    assert budget.used_today("v", "daily", now=T0) == 1, "a denial spent quota"
    budget.close()
