# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Rate limiting: a quota spent locally is a quota not spent by a ban."""

from __future__ import annotations

import pytest

from genesis.errors import TransientError
from genesis.mcp.limits import RateLimitedError, RateLimiter, TokenBucket


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_a_server_with_no_configured_limit_is_not_limited() -> None:
    """Correct for the local ones: throttling the clock protects nobody."""
    limiter = RateLimiter()
    for _ in range(1000):
        limiter.check("time")


def test_the_burst_is_spendable_immediately_then_refills() -> None:
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    limiter.configure("fred", per_minute=60, burst=3)

    for _ in range(3):
        limiter.check("fred")
    with pytest.raises(RateLimitedError):
        limiter.check("fred")

    clock.advance(1.0)  # 60/min = one token a second
    limiter.check("fred")


def test_refusal_is_transient_and_says_how_long_to_wait() -> None:
    """The Task Bus already knows what to do with 'try again shortly'.

    Inventing a second retry policy here would be a second implementation of
    machinery that exists — and the two would drift.
    """
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    limiter.configure("alpha-vantage", per_minute=5, burst=1)
    limiter.check("alpha-vantage")

    with pytest.raises(RateLimitedError) as caught:
        limiter.check("alpha-vantage")
    error = caught.value
    assert isinstance(error, TransientError)
    assert error.retryable
    assert error.server == "alpha-vantage"
    assert error.retry_after_sec == pytest.approx(12.0)  # 5/min -> one per 12s


def test_the_bucket_never_banks_more_than_its_burst() -> None:
    """An idle hour must not become an hour's worth of stampede."""
    clock = Clock()
    bucket = TokenBucket(rate=1.0, burst=5.0)
    bucket.take(clock())
    clock.advance(3600)
    taken = 0
    while bucket.take(clock()) == 0.0:
        taken += 1
        if taken > 100:  # pragma: no cover - guard against a runaway
            break
    assert taken == 5


def test_burst_defaults_to_a_quarter_of_the_minute() -> None:
    limiter = RateLimiter()
    limiter.configure("sec-edgar", per_minute=60)
    for _ in range(15):
        limiter.check("sec-edgar")
    with pytest.raises(RateLimitedError):
        limiter.check("sec-edgar")


def test_a_nonsense_limit_is_refused_at_configuration_time() -> None:
    limiter = RateLimiter()
    with pytest.raises(ValueError):
        limiter.configure("x", per_minute=0)


def test_limits_are_per_server_not_shared() -> None:
    """The quota belongs to the API key, and one key is one server."""
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    limiter.configure("fred", per_minute=60, burst=1)
    limiter.configure("arxiv", per_minute=60, burst=1)
    limiter.check("fred")
    limiter.check("arxiv")  # unaffected by fred's spend
    with pytest.raises(RateLimitedError):
        limiter.check("fred")
