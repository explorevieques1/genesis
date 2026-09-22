# Spec: Genesis Markdown/20-Agents/Charting/Charting Family.md
"""Synthetic bars with known shapes.

Every fixture here is *constructed*, not sampled. A test that asserts "a range
is detected" against a random walk asserts something about that seed, and it
will pass or fail for reasons nobody can read six months later. So the range
oscillates, the trend trends, and the gap is a gap that is genuinely there.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from genesis.charting.bars import Bars


def _frame(
    close: np.ndarray,
    *,
    symbol: str = "TEST",
    timeframe: str = "1D",
    step: timedelta = timedelta(days=1),
    start: datetime = datetime(2025, 1, 1, tzinfo=UTC),
    wick: float = 0.6,
    volume: np.ndarray | None = None,
) -> Bars:
    n = len(close)
    times = tuple(start + step * i for i in range(n))
    rng = np.random.default_rng(0)
    # A zero wick is a legitimate fixture (a flat, zero-ATR window), and
    # `uniform(0.1, 0.0)` raises rather than returning zeros.
    span = max(wick, 0.0)
    floor = min(0.1, span)
    high = close + (rng.uniform(floor, span, n) if span > 0 else np.zeros(n))
    low = close - (rng.uniform(floor, span, n) if span > 0 else np.zeros(n))
    opens = np.concatenate(([close[0]], close[:-1]))
    return Bars(
        symbol=symbol,
        timeframe=timeframe,
        times=times,
        open=opens,
        high=np.maximum(high, np.maximum(opens, close)),
        low=np.minimum(low, np.minimum(opens, close)),
        close=close,
        volume=volume if volume is not None else np.full(n, 1_000_000.0),
        source="test",
        tier=3,
    )


@pytest.fixture
def trending() -> Bars:
    """A clean uptrend: higher highs and higher lows, no ambiguity."""
    base = np.linspace(100, 160, 240)
    wobble = 3.0 * np.sin(np.arange(240) / 9.0)
    return _frame(base + wobble)


@pytest.fixture
def ranging() -> Bars:
    """A clean range between roughly 97 and 103, visited repeatedly."""
    return _frame(100 + 3.0 * np.sin(np.arange(240) / 7.0))


@pytest.fixture
def falling() -> Bars:
    """The `trending` series, reversed. A downtrend by construction.

    Reversal rather than a fresh decline, and the reason is a real trap: a
    *monotone* line has no fractal pivots at all — no bar is a local high with
    lower highs on both sides — so a steep, clean decline reads as ``range``
    with zero swing points, which is correct behaviour and a useless fixture.
    The wobble has to be large enough relative to the slope to turn, and
    reversing a series already known to trend guarantees exactly that at the
    mirrored scale.
    """
    base = np.linspace(100, 160, 240) + 3.0 * np.sin(np.arange(240) / 9.0)
    return _frame(base[::-1].copy())


@pytest.fixture
def intraday() -> Bars:
    """Three sessions of 5-minute bars, so session VWAP and the ORB exist."""
    per_session = 78  # 6.5 hours
    closes = []
    for day in range(3):
        drift = np.linspace(0, 4 * (1 if day % 2 == 0 else -1), per_session)
        closes.append(100 + day * 2 + drift + 0.4 * np.sin(np.arange(per_session) / 4))
    close = np.concatenate(closes)
    times: list[datetime] = []
    for day in range(3):
        open_at = datetime(2025, 3, 3 + day, 14, 30, tzinfo=UTC)
        times.extend(open_at + timedelta(minutes=5 * i) for i in range(per_session))
    frame = _frame(close, timeframe="5m", wick=0.2)
    return Bars(
        symbol=frame.symbol, timeframe="5m", times=tuple(times),
        open=frame.open, high=frame.high, low=frame.low, close=frame.close,
        volume=frame.volume, source="test", tier=3,
    )


@pytest.fixture
def make_frame():
    """Escape hatch for a test that needs a shape of its own."""
    return _frame
