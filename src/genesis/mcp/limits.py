# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""How often Genesis is willing to hammer somebody else's server.

The first stage of the call path after the allow-list. It exists for three
reasons, in ascending order of how expensive the mistake is:

1. **Free tiers are small.** Alpha Vantage's free key is 25 calls a day. FRED
   and SEC EDGAR ask for politeness rather than enforcing it, and answer a
   burst with a temporary ban that looks exactly like the server being down.
2. **A loop is the normal way to exhaust one.** An agent that retries a
   malformed argument does not slow down on its own, and the Task Bus retries
   transient failures by design. Without a bucket, one bad task spends a day's
   quota in nine seconds.
3. **A ban is invisible in the worst way.** The server stops answering, the
   runtime reads that as session loss, reconnects, and the health probe says
   the server is fine — so the system concludes the *network* is flaky and
   keeps trying. A local limit fails with the truth instead.

**Token bucket, per server, not per tool.** The quota belongs to the API key,
and an API key is a server. Limiting per tool would let ten tools on one server
each spend the whole allowance.

**Refusal is transient, and it waits.** :class:`RateLimitedError` is a
``TransientError`` so the Task Bus's existing backoff handles it — the retry
machinery already knows what to do with "try again shortly", and inventing a
second one here would be a second implementation of the same thing. The error
carries ``retry_after_sec`` so backoff can be informed rather than exponential
guesswork.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from genesis.errors import TransientError

__all__ = ["RateLimitedError", "RateLimiter", "TokenBucket"]


class RateLimitedError(TransientError):
    """This server's local quota is spent. Not the server's opinion — ours.

    Distinct from a 429 arriving over the wire, and deliberately so: a 429 has
    already cost the call, and on several of these APIs has already cost the
    next hour too. This one fires *before* dispatch, which is the only place a
    quota can actually be protected.
    """

    def __init__(self, server: str, retry_after_sec: float) -> None:
        super().__init__(
            f"rate limit for {server!r} is spent; retry in "
            f"{retry_after_sec:.1f}s",
            spoken_summary=f"I'm calling {server} too fast, so I'm holding off.",
        )
        self.server = server
        self.retry_after_sec = retry_after_sec


@dataclass
class TokenBucket:
    """Classic leaky bucket: ``rate`` tokens a second, ``burst`` in hand.

    Chosen over a fixed window because a window's boundary is a stampede — with
    a 60-per-minute window, sixty calls at 11:59:59 and sixty more at 12:00:00
    is inside the limit and outside anything a vendor considers acceptable. A
    bucket has no boundary to align to.

    Refills continuously from a monotonic clock rather than on a timer thread:
    no thread to supervise, no drift, and a bucket that has been idle for an
    hour is correct the instant it is next read.
    """

    rate: float
    burst: float
    _tokens: float = 0.0
    #: ``None`` until the first take, and deliberately not ``0.0``. A monotonic
    #: clock legitimately reads 0.0 — a fake one in a test always does — and a
    #: sentinel that collides with a real value means the bucket never refills
    #: at all. It would still refuse correctly, forever, which is the shape of
    #: bug that looks like a working rate limiter.
    _updated: float | None = None

    def __post_init__(self) -> None:
        if self.rate <= 0 or self.burst <= 0:
            raise ValueError("rate and burst must both be positive")
        self._tokens = self.burst

    def _refill(self, now: float) -> None:
        if self._updated is None:
            self._updated = now
            return
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._updated = now

    def take(self, now: float) -> float:
        """Spend one token. Returns ``0.0`` on success, else seconds to wait.

        Returning a wait rather than raising keeps this class free of the
        gateway's error types, which is what lets it be tested against a fake
        clock without importing half the system.
        """
        self._refill(now)
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        return (1.0 - self._tokens) / self.rate


class RateLimiter:
    """One bucket per server, created on first sight.

    Servers with no configured limit are not rate limited at all, and that is
    the right default for the local ones: ``time``, ``git`` and ``filesystem``
    have no quota to protect and throttling them would only add latency to a
    clock read.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._buckets: dict[str, TokenBucket] = {}
        self._clock = clock
        self._lock = threading.Lock()

    def configure(self, server: str, *, per_minute: float, burst: float | None = None) -> None:
        """Set a server's allowance. Idempotent; last call wins.

        ``burst`` defaults to a quarter of the minute's allowance, floored at
        one. A burst equal to the full minute would permit exactly the
        stampede the bucket was chosen to prevent, and a burst of one would
        serialise three parallel reads of a server that can happily take them.
        """
        if per_minute <= 0:
            raise ValueError(f"server {server!r}: per_minute must be positive")
        rate = per_minute / 60.0
        with self._lock:
            self._buckets[server] = TokenBucket(
                rate=rate, burst=burst if burst is not None else max(1.0, per_minute / 4)
            )

    def check(self, server: str) -> None:
        """Spend a token for this server, or raise. Called before dispatch."""
        with self._lock:
            bucket = self._buckets.get(server)
            if bucket is None:
                return
            wait = bucket.take(self._clock())
        if wait > 0:
            raise RateLimitedError(server, wait)

    def limited(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._buckets))
