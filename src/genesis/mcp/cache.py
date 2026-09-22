# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Serving the same answer twice without asking twice.

MCP Gateway.md §caching: *"Cache by tool + arguments + bar boundary: a quote
for the same symbol within the same second, or bars for the same symbol within
the same bar, is one call. Cache is invalidated on bar close, never on a timer
alone. Cached results carry their age; a stale-but-cached result is marked
degraded."*

Two rules do all the work here, and both are about the same failure.

**A wrong cache on market data is a stale price presented as a live one.**
That is the failure mode Biological Design warns about by name: drift between
believed and actual state, losing money *quietly*. So nothing is cached unless
its catalogue entry says so (:data:`~genesis.mcp.spec.NO_CACHE` is the default),
and a served entry always carries its age.

**A bar is not a timer.** A five-second TTL on a daily bar is wasteful for
23 hours and *wrong* for the one second that matters, because at the close the
bar changed and no TTL knew. So ``bar_boundary`` keys on which bar we are in,
and a bar rolling over invalidates regardless of remaining TTL. Daily bars ask
the :class:`~genesis.daemon.calendar.MarketCalendar` rather than dividing by
86400 — a session close is 16:00 New York, which is not midnight anywhere and
moves on half days.

**Stale is served only when the alternative is nothing.** A live call that
fails, with a stale entry in hand, returns the stale entry labelled
``degraded`` — Error Handling And Degradation's "proceed with less, label the
output". It is never served in preference to a call that would have worked,
because a cache that quietly prefers old data is indistinguishable from a
broken feed.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from genesis.mcp.runtime import ToolResult
from genesis.mcp.spec import CachePolicy, ToolSpec

if TYPE_CHECKING:  # pragma: no cover - typing only
    from genesis.daemon.calendar import MarketCalendar

__all__ = [
    "DEFAULT_MAX_STALE_SEC",
    "CacheStats",
    "Hit",
    "ResultCache",
    "bar_seconds",
    "cache_key",
]

#: How many entries before the oldest is evicted. Small on purpose: this is a
#: hot-path cache for repeated calls inside one task, not a data store. Bars
#: that need keeping belong in the market data plane, which owns them, has a
#: schema for them, and can answer questions about them offline.
DEFAULT_MAX_ENTRIES = 512

#: How old a cached answer may be and still be served on the failure path.
#: Fifteen minutes: long enough to cover a server restart or a flaky minute,
#: short enough that nothing here can hand back a price from a previous
#: session. Beyond it the honest answer is the error.
DEFAULT_MAX_STALE_SEC = 900.0

#: ``1m``, ``5min``, ``1h``, ``4hour``, ``1d``, ``1D``, ``1w``. Deliberately
#: permissive about spelling, because every vendor spells it differently and
#: the cost of not recognising one is a cache that silently never hits.
_TIMEFRAME = re.compile(r"^\s*(\d+)\s*(m|min|minute|h|hr|hour|d|day|w|week)s?\s*$", re.I)

_UNIT_SECONDS = {
    "m": 60, "min": 60, "minute": 60,
    "h": 3600, "hr": 3600, "hour": 3600,
    "d": 86400, "day": 86400,
    "w": 604800, "week": 604800,
}

#: Argument names that mean "how big is a bar". The first one present wins.
_TIMEFRAME_KEYS = ("timeframe", "interval", "granularity", "resolution", "period", "bar")


def bar_seconds(arguments: dict[str, Any] | None) -> int | None:
    """How long the bar in these arguments lasts, if it says.

    ``None`` means the call did not name a timeframe. That is treated as *not
    bar-cacheable* rather than as a default of one minute: guessing the bar
    size is guessing when the data goes stale, and guessing short merely wastes
    calls while guessing long serves a closed bar as a live one.
    """
    for key in _TIMEFRAME_KEYS:
        value = (arguments or {}).get(key)
        if isinstance(value, str):
            match = _TIMEFRAME.match(value)
            if match:
                return int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
    return None


def cache_key(tool_id: str, arguments: dict[str, Any] | None) -> str:
    """Tool plus arguments, canonicalised so key order cannot cause a miss.

    ``sort_keys`` because ``{"symbol": "NQ", "tf": "1d"}`` and its reverse are
    the same call, and a cache that thought otherwise would halve its hit rate
    for a reason nobody would ever find. ``default=str`` because an argument we
    cannot serialise must produce a stable-ish key rather than an exception —
    a cache is not permitted to be the thing that breaks a call.
    """
    payload = json.dumps(arguments or {}, sort_keys=True, default=str)
    return f"{tool_id}\x00{payload}"


@dataclass(frozen=True)
class Hit:
    """A cached result and how old it is.

    ``age_sec`` travels with the value because MCP Gateway.md requires it, and
    because a caller deciding whether 40-second-old volume is good enough needs
    the number, not a boolean somebody else computed from it.
    """

    result: ToolResult
    age_sec: float
    stale: bool = False


@dataclass
class CacheStats:
    """Enough to answer the acceptance criterion, and nothing more.

    *"Cache hit rate on market data above 60% during an active session"* is a
    measurement, so the counters exist. They are not persisted: a hit rate
    across restarts averages two different market sessions together and means
    nothing.
    """

    hits: int = 0
    misses: int = 0
    stale_hits: int = 0
    stores: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return 0.0 if total == 0 else self.hits / total


@dataclass
class _Entry:
    result: ToolResult
    stored_at: float
    policy: CachePolicy
    #: Which bar this answer belongs to. ``None`` when the policy is TTL-only.
    bar: int | None


class ResultCache:
    """Tool results, keyed by call, bounded, and thread-safe.

    Thread-safe because the gateway is read from every agent thread and the
    Task Bus runs lanes concurrently — a cache is exactly the shared mutable
    state that a threaded fleet trips over, and the lock costs nothing next to
    the socket round-trip it is avoiding.
    """

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_stale_sec: float = DEFAULT_MAX_STALE_SEC,
        clock: Callable[[], float] = time.time,
        calendar: MarketCalendar | None = None,
    ) -> None:
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._max = max_entries
        self.max_stale_sec = max_stale_sec
        self._clock = clock
        self._calendar = calendar
        self._lock = threading.Lock()
        self.stats = CacheStats()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any] | None,
        *,
        allow_stale: bool = False,
    ) -> Hit | None:
        """A fresh answer, or — only when asked — a stale one.

        ``allow_stale`` is for the failure path and nothing else: the live call
        raised, and an old answer labelled ``degraded`` beats no answer. On the
        ordinary path a stale entry is a miss, because serving it would make
        the cache the reason a caller saw old data when fresh data was
        available.
        """
        if not spec.cache.cacheable:
            return None

        key = cache_key(spec.id, arguments)
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats.misses += 1
                return None

            age = now - entry.stored_at
            fresh = self._fresh(entry, arguments, now)
            if fresh:
                self._entries.move_to_end(key)
                self.stats.hits += 1
                return Hit(result=entry.result, age_sec=age)

            if not allow_stale:
                # Kept, not dropped. An expired entry is precisely what the
                # failure path will want in a moment, and deleting it here
                # would mean a call that fails right after its cache expires
                # has nothing to degrade to — the one moment the degrade path
                # exists for. Nothing leaks: the cache is LRU-bounded, so an
                # entry nobody asks for again is evicted by the next 512.
                self.stats.misses += 1
                return None

            if age > self.max_stale_sec:
                # Old enough that serving it would be a different kind of lie.
                # `degraded` labels an answer as imperfect; it does not license
                # any answer at all, and an hour-old quote presented as
                # "degraded" is the stale-price-as-live failure wearing a
                # label. Past the bound, no answer is the honest answer.
                self.stats.misses += 1
                return None

            self.stats.stale_hits += 1
            return Hit(result=entry.result, age_sec=age, stale=True)

    def _fresh(
        self, entry: _Entry, arguments: dict[str, Any] | None, now: float
    ) -> bool:
        """TTL and bar boundary are both necessary; neither alone is enough.

        A bar-boundary entry with a TTL must satisfy *both* — the TTL bounds
        how wrong a still-open bar may be, and the boundary catches the close
        that the TTL would sleep through.
        """
        policy = entry.policy
        if policy.bar_boundary:
            if self._bar_index(arguments, now) != entry.bar:
                return False
        if policy.ttl_sec is not None:
            return (now - entry.stored_at) < policy.ttl_sec
        return policy.bar_boundary

    def _bar_index(self, arguments: dict[str, Any] | None, now: float) -> int | None:
        """Which bar ``now`` falls in, for the timeframe in these arguments.

        Daily and longer defer to the market calendar when one was supplied,
        because "the current daily bar" ends at the session close, not at
        00:00 UTC. Without a calendar this falls back to fixed-width division
        and says so by simply being arithmetic — the cache still works, it is
        just wrong about the eight hours between a US close and UTC midnight,
        which is why ``build_gateway`` passes a calendar.
        """
        seconds = bar_seconds(arguments)
        if seconds is None:
            return None
        if seconds >= 86400 and self._calendar is not None:
            return self._session_index(now)
        return int(now // seconds)

    def _session_index(self, now: float) -> int:
        """The ordinal of the trading session ``now`` belongs to.

        A timestamp before today's close belongs to today's bar; after it, to
        the next session's. Using the date alone would roll the daily bar over
        at midnight — eight hours after the data actually stopped changing,
        during which every call would miss for no reason.
        """
        import datetime as dt

        assert self._calendar is not None
        moment = dt.datetime.fromtimestamp(now, dt.UTC)
        day = moment.date()
        close = self._calendar.session_close(day)
        ordinal = day.toordinal()
        if close is not None and moment >= close.astimezone(dt.UTC):
            ordinal += 1
        return ordinal

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def put(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any] | None,
        result: ToolResult,
    ) -> None:
        """Store a result, if its catalogue entry permits caching at all.

        A bar-boundary tool called without a timeframe stores nothing: there is
        no bar to key on, and storing it under "no bar" would make the entry
        immortal — the one outcome worse than never caching it.
        """
        policy = spec.cache
        if not policy.cacheable:
            return
        now = self._clock()
        bar = self._bar_index(arguments, now) if policy.bar_boundary else None
        if policy.bar_boundary and bar is None and policy.ttl_sec is None:
            return

        key = cache_key(spec.id, arguments)
        with self._lock:
            self._entries[key] = _Entry(
                result=result, stored_at=now, policy=policy, bar=bar
            )
            self._entries.move_to_end(key)
            self.stats.stores += 1
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)
                self.stats.evictions += 1

    def invalidate(self, tool_id: str | None = None) -> int:
        """Drop everything, or everything for one tool. Returns how many."""
        with self._lock:
            if tool_id is None:
                count = len(self._entries)
                self._entries.clear()
                return count
            prefix = f"{tool_id}\x00"
            keys = [k for k in self._entries if k.startswith(prefix)]
            for key in keys:
                del self._entries[key]
            return len(keys)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
