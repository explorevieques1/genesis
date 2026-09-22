# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The cache: right answers only, and never a stale one presented as fresh."""

from __future__ import annotations

import datetime as dt

import pytest

from genesis.daemon.calendar import MarketCalendar
from genesis.mcp.cache import ResultCache, bar_seconds, cache_key
from genesis.mcp.runtime import ToolResult
from genesis.mcp.spec import CachePolicy, ToolSpec, Trust


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def spec(capability: str = "market-data.quote", **cache: object) -> ToolSpec:
    return ToolSpec(
        id="alpaca.get_stock_quote",
        server="alpaca",
        name="get_stock_quote",
        capability=capability,
        trust=Trust.TRUSTED,
        mutating=False,
        cache=CachePolicy(**cache),  # type: ignore[arg-type]
    )


def result(payload: str = "ok") -> ToolResult:
    return ToolResult(tool="get_stock_quote", server="alpaca", content=payload)


# --------------------------------------------------------------------------
# The default
# --------------------------------------------------------------------------


def test_nothing_is_cached_unless_the_catalogue_says_so() -> None:
    """NO_CACHE is the default, and the default is the safe direction.

    A wrong cache on market data is a stale price presented as a live one —
    the failure mode that loses money quietly.
    """
    cache = ResultCache()
    tool = spec()
    cache.put(tool, {"symbol": "NQ"}, result())
    assert len(cache) == 0
    assert cache.get(tool, {"symbol": "NQ"}) is None


# --------------------------------------------------------------------------
# Keying
# --------------------------------------------------------------------------


def test_argument_order_does_not_change_the_key() -> None:
    assert cache_key("a.b", {"x": 1, "y": 2}) == cache_key("a.b", {"y": 2, "x": 1})


def test_different_arguments_are_different_entries() -> None:
    clock = Clock()
    cache = ResultCache(clock=clock)
    tool = spec(ttl_sec=10)
    cache.put(tool, {"symbol": "NQ"}, result("nq"))
    cache.put(tool, {"symbol": "ES"}, result("es"))
    assert cache.get(tool, {"symbol": "NQ"}).result.content == "nq"
    assert cache.get(tool, {"symbol": "ES"}).result.content == "es"


def test_an_unserialisable_argument_does_not_break_the_call() -> None:
    """A cache is never permitted to be the thing that breaks a call."""
    assert cache_key("a.b", {"when": dt.date(2026, 9, 3)})


# --------------------------------------------------------------------------
# TTL
# --------------------------------------------------------------------------


def test_a_ttl_hit_carries_its_age() -> None:
    clock = Clock()
    cache = ResultCache(clock=clock)
    tool = spec(ttl_sec=5)
    cache.put(tool, {"symbol": "NQ"}, result())
    clock.advance(2)
    hit = cache.get(tool, {"symbol": "NQ"})
    assert hit is not None and hit.age_sec == pytest.approx(2.0)
    assert not hit.stale


def test_an_expired_entry_is_a_miss_not_a_stale_hit() -> None:
    clock = Clock()
    cache = ResultCache(clock=clock)
    tool = spec(ttl_sec=5)
    cache.put(tool, {"symbol": "NQ"}, result())
    clock.advance(6)
    assert cache.get(tool, {"symbol": "NQ"}) is None


# --------------------------------------------------------------------------
# Bar boundary — "invalidated on bar close, never on a timer alone"
# --------------------------------------------------------------------------


def test_bar_seconds_reads_every_common_spelling() -> None:
    assert bar_seconds({"timeframe": "5m"}) == 300
    assert bar_seconds({"interval": "1 hour"}) == 3600
    assert bar_seconds({"granularity": "1D"}) == 86400
    assert bar_seconds({"symbol": "NQ"}) is None


def test_a_bar_hit_survives_inside_the_bar() -> None:
    clock = Clock(now=0.0)
    cache = ResultCache(clock=clock)
    tool = spec("market-data.ohlcv", bar_boundary=True)
    args = {"symbol": "NQ", "timeframe": "5m"}
    cache.put(tool, args, result())
    clock.advance(299)
    assert cache.get(tool, args) is not None


def test_a_bar_close_invalidates_regardless_of_ttl() -> None:
    """The rule that makes this a bar cache and not a timer.

    A generous TTL must not survive the close: at the boundary the bar changed,
    and no TTL knows that.
    """
    clock = Clock(now=0.0)
    cache = ResultCache(clock=clock)
    tool = spec("market-data.ohlcv", bar_boundary=True, ttl_sec=3600)
    args = {"symbol": "NQ", "timeframe": "5m"}
    cache.put(tool, args, result())
    clock.advance(301)  # into the next 5-minute bar, well inside the TTL
    assert cache.get(tool, args) is None


def test_a_ttl_still_bounds_an_open_bar() -> None:
    clock = Clock(now=0.0)
    cache = ResultCache(clock=clock)
    tool = spec("market-data.ohlcv", bar_boundary=True, ttl_sec=10)
    args = {"symbol": "NQ", "timeframe": "1d"}
    cache.put(tool, args, result())
    clock.advance(11)
    assert cache.get(tool, args) is None


def test_a_bar_tool_called_without_a_timeframe_stores_nothing() -> None:
    """No bar to key on, and an entry keyed on nothing would be immortal."""
    cache = ResultCache()
    tool = spec("market-data.ohlcv", bar_boundary=True)
    cache.put(tool, {"symbol": "NQ"}, result())
    assert len(cache) == 0


def test_the_daily_bar_rolls_at_the_session_close_not_at_midnight() -> None:
    """A session close is 16:00 New York, which is not midnight anywhere.

    Without the calendar, a daily bar cached at 15:00 New York would be served
    until 00:00 UTC — eight hours after the data stopped changing — and then
    miss for the rest of the night for no reason.
    """
    calendar = MarketCalendar()
    day = dt.date(2026, 9, 3)  # a Thursday
    close = calendar.session_close(day)
    assert close is not None

    before = (close - dt.timedelta(minutes=30)).timestamp()
    after = (close + dt.timedelta(minutes=30)).timestamp()

    clock = Clock(now=before)
    cache = ResultCache(clock=clock, calendar=calendar)
    tool = spec("market-data.ohlcv", bar_boundary=True)
    args = {"symbol": "SPY", "timeframe": "1d"}

    cache.put(tool, args, result())
    clock.now = before + 60
    assert cache.get(tool, args) is not None, "still inside the session's bar"

    clock.now = after
    assert cache.get(tool, args) is None, "the session closed; the bar is done"


# --------------------------------------------------------------------------
# Stale, and when it may be served
# --------------------------------------------------------------------------


def test_stale_is_never_served_on_the_ordinary_path() -> None:
    clock = Clock()
    cache = ResultCache(clock=clock)
    tool = spec(ttl_sec=5)
    cache.put(tool, {}, result())
    clock.advance(600)
    assert cache.get(tool, {}) is None


def test_stale_is_served_when_explicitly_asked_and_is_labelled() -> None:
    clock = Clock()
    cache = ResultCache(clock=clock)
    tool = spec(ttl_sec=5)
    cache.put(tool, {}, result("old"))
    clock.advance(600)
    hit = cache.get(tool, {}, allow_stale=True)
    assert hit is not None
    assert hit.stale and hit.age_sec == pytest.approx(600.0)
    assert hit.result.content == "old"


def test_an_ordinary_miss_keeps_the_entry_for_the_degrade_path() -> None:
    """The moment the degrade path exists for is right after expiry.

    Dropping an expired entry eagerly would mean a call that fails just after
    its TTL lapses has nothing to fall back to — which is exactly when a
    labelled old answer is most useful.
    """
    clock = Clock()
    cache = ResultCache(clock=clock)
    tool = spec(ttl_sec=5)
    cache.put(tool, {}, result("old"))
    clock.advance(10)
    assert cache.get(tool, {}) is None
    assert cache.get(tool, {}, allow_stale=True) is not None


def test_stale_is_bounded_and_past_the_bound_nothing_is_served() -> None:
    """`degraded` labels an imperfect answer; it does not license any answer.

    An hour-old quote handed back with a degraded flag is the stale-price-as-
    live failure wearing a label.
    """
    clock = Clock()
    cache = ResultCache(clock=clock, max_stale_sec=60)
    tool = spec(ttl_sec=5)
    cache.put(tool, {}, result("ancient"))
    clock.advance(61)
    assert cache.get(tool, {}, allow_stale=True) is None


# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------


def test_the_cache_is_bounded_and_evicts_oldest_first() -> None:
    cache = ResultCache(max_entries=3)
    tool = spec(ttl_sec=1000)
    for i in range(5):
        cache.put(tool, {"n": i}, result(str(i)))
    assert len(cache) == 3
    assert cache.get(tool, {"n": 0}) is None
    assert cache.get(tool, {"n": 4}) is not None
    assert cache.stats.evictions == 2


def test_invalidate_by_tool() -> None:
    cache = ResultCache()
    tool = spec(ttl_sec=100)
    cache.put(tool, {"a": 1}, result())
    cache.put(tool, {"a": 2}, result())
    assert cache.invalidate(tool.id) == 2
    assert len(cache) == 0
