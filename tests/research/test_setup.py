# Spec: Genesis Markdown/70-Schemas/Idea Schema.md · 10-Architecture/Charting Engine.md
"""Turning a worded idea into prices — the rules that keep it honest.

Every number here is arithmetic over bars, so every test is exact. What is
worth pinning is not the arithmetic but the *judgement encoded in it*: a stop
inside the noise is not an invalidation, a price off the tick grid is refused
by the gate for the wrong reason, and a chart that cannot be read means an
unsized idea rather than a guessed one.
"""

from __future__ import annotations

import numpy as np
import pytest

from genesis.research import setup as mod


def bars_for(trend: float = 0.5, n: int = 200, base: float = 100.0, flat: bool = False):
    """Real `Bars`, synthetic prices. The class does the validating."""
    import datetime as dt

    from genesis.charting.bars import Bars

    if flat:
        close = np.full(n, base)
    else:
        rng = np.random.default_rng(7)
        close = base + np.cumsum(rng.normal(trend, 1.0, n))
    start = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    return Bars(
        symbol="EQ:XNAS:TEST", timeframe="1D",
        times=tuple(start + dt.timedelta(days=i) for i in range(n)),
        open=close, high=close * (1.0 if flat else 1.01), low=close * (1.0 if flat else 0.99),
        close=close, volume=np.full(n, 1_000_000.0), source="test", tier=3,
    )


def compute(monkeypatch, bars, direction: str = "long", symbol_id: str = "EQ:XNAS:TEST"):
    import genesis.marketdata.build as build
    import genesis.marketdata.source as source

    class Built:
        def __init__(self) -> None:
            self.source = type("S", (), {"fetch": staticmethod(lambda *_a, **_k: bars)})()
            self.store = type("X", (), {"close": staticmethod(lambda: None)})()
            self.budget = type("X", (), {"close": staticmethod(lambda: None)})()

    monkeypatch.setattr(build, "build_source", lambda *a, **k: Built())
    monkeypatch.setattr(source, "resolve_symbol", lambda s, **k: symbol_id)
    return mod.compute_setup("TEST", direction, config=object())


# ----------------------------------------------------------------------
# The stop
# ----------------------------------------------------------------------


def test_the_stop_is_never_inside_the_noise(monkeypatch) -> None:  # noqa: ANN001
    """The nearest level is usually yesterday's high or low, a few tenths of an
    ATR away. A stop there gets hit on an ordinary Tuesday — and worse, makes
    the risk distance so small that the gate sizes the maximum against it."""
    s = compute(monkeypatch, bars_for())
    assert abs(s.entry_high - s.stop) >= mod.MIN_STOP_ATR * s.atr * 0.9


def test_the_stop_is_on_the_losing_side(monkeypatch) -> None:  # noqa: ANN001
    long = compute(monkeypatch, bars_for(), "long")
    short = compute(monkeypatch, bars_for(), "short")
    assert long.stop < long.entry_low
    assert short.stop > short.entry_high


def test_the_stop_says_which_rule_produced_it(monkeypatch) -> None:  # noqa: ANN001
    """"Below the 50-day" and "1.5 ATR away" are different claims, and a trader
    should never have to guess which one they are looking at."""
    s = compute(monkeypatch, bars_for())
    assert s.stop_basis in ("level", "atr")
    assert s.stop_why
    if s.stop_basis == "atr":
        assert any("volatility-based" in w for w in s.warnings)


# ----------------------------------------------------------------------
# The tick grid
# ----------------------------------------------------------------------


def test_every_price_lands_on_the_tick_grid(monkeypatch) -> None:  # noqa: ANN001
    """Off-grid prices are refused by the gate for being off-grid — which is a
    terrible way to find out about rounding."""
    s = compute(monkeypatch, bars_for())
    for price in (s.entry_low, s.entry_high, s.stop, *s.targets):
        assert round(price, 2) == pytest.approx(price), price


def test_a_futures_symbol_uses_its_own_tick(monkeypatch) -> None:  # noqa: ANN001
    s = compute(monkeypatch, bars_for(base=20000.0), symbol_id="FUT:CME:NQ:2026-12")
    for price in (s.stop, *s.targets):
        assert (price * 4) == pytest.approx(round(price * 4)), f"{price} is not on the 0.25 grid"


# ----------------------------------------------------------------------
# Refusing rather than guessing
# ----------------------------------------------------------------------


def test_too_few_bars_is_degraded_not_a_guessed_stop(monkeypatch) -> None:  # noqa: ANN001
    from genesis.errors import DegradedError

    with pytest.raises(DegradedError, match="not enough"):
        compute(monkeypatch, bars_for(n=10))


def test_a_flat_chart_has_no_atr_and_refuses(monkeypatch) -> None:  # noqa: ANN001
    """Zero range means no distance to risk. Any stop here would be invented."""
    from genesis.errors import DegradedError

    with pytest.raises(DegradedError):
        compute(monkeypatch, bars_for(flat=True))


def test_targets_are_multiples_of_the_risk_taken(monkeypatch) -> None:  # noqa: ANN001
    s = compute(monkeypatch, bars_for())
    risk = abs(s.entry_high - s.stop)
    assert s.targets[0] == pytest.approx(s.entry_high + mod.TARGET_R[0] * risk, abs=0.01)
    assert s.targets[-1] == pytest.approx(s.entry_high + mod.TARGET_R[-1] * risk, abs=0.01)


def test_a_long_against_a_downtrend_is_warned_about(monkeypatch) -> None:  # noqa: ANN001
    """The setup prices the idea; it does not vet it. But it says what it saw."""
    s = compute(monkeypatch, bars_for(trend=-0.8), "long")
    if s.trend == "down":
        assert any("trend is down" in w for w in s.warnings)
