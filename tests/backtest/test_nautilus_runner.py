# Spec: Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md
"""The Nautilus boundary: what goes in, what comes back, and what it refuses.

These do not test Nautilus. Nautilus has its own suite and re-testing a
matching engine here would be both redundant and much worse. What is tested is
the boundary Genesis owns:

- the conversions (symbol ids, timeframes, price precision) that would silently
  produce a *plausible* wrong answer if they were wrong;
- the refusals, which are the only thing standing between a short window and a
  confident-looking statistic;
- the honesty machinery — that a strategy which raised is reported as having
  raised, rather than as having found no signals.

That last one is the important one. Nautilus catches exceptions inside
``on_bar`` and logs them, so a broken strategy produces a clean zero-trade
report. Without the diagnostics path there is no way to tell that apart from a
strategy that simply never triggered.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from genesis.backtest.runner import (
    InsufficientData, _price_precision, _split_symbol, _timeframe_spec, run_spec,
)
from genesis.backtest.strategy import (
    Indicator, Rule, Sizing, Stop, StrategySpec, ma_crossover,
)
from genesis.marketdata.normalize import Bar

pytest.importorskip("nautilus_trader", reason="the backtest engine is nautilus_trader")


def make_bars(closes, *, symbol="EQ:XNAS:TEST", source="test", tier=1):
    start = datetime(2026, 1, 5, tzinfo=UTC)
    out = []
    for i, close in enumerate(closes):
        previous = closes[i - 1] if i else close
        # Decimals built from strings, then arithmetic in Decimal -- the same
        # path the real normalizer takes. Doing the arithmetic in float first
        # would inject representation noise the store never produces.
        open_ = Decimal(str(previous))
        close_ = Decimal(str(close))
        pad = Decimal("1")
        out.append(Bar(
            symbol_id=symbol, timeframe="1D", ts=start + timedelta(days=i),
            open=open_, high=max(open_, close_) + pad,
            low=min(open_, close_) - pad, close=close_,
            volume=Decimal("1000000"), source=source, tier=tier,
        ))
    return out


def trending(n=160):
    """A sawtooth that actually crosses, so a crossover strategy trades."""
    return [100 + 18 * ((i // 20) % 2) + (i % 20) * 0.4 for i in range(n)]


# ---------------------------------------------------------------------------
# conversions — quietly wrong is the failure mode here
# ---------------------------------------------------------------------------

def test_symbol_id_splits_into_venue_and_ticker():
    assert _split_symbol("EQ:XNAS:AAPL") == ("XNAS", "AAPL")
    # A future's last segment is its contract month, not its instrument.
    assert _split_symbol("FUT:CME:ES:2026-12") == ("CME", "ES")
    # No venue in the id: simulated, and named so the report says so.
    assert _split_symbol("AAPL") == ("SIM", "AAPL")


def test_timeframe_maps_to_the_nautilus_bar_grammar():
    assert _timeframe_spec("1D") == "1-DAY"
    assert _timeframe_spec("5m") == "5-MINUTE"
    assert _timeframe_spec("1h") == "1-HOUR"


def test_price_precision_comes_from_the_data():
    """Rounding to fewer places than the venue quotes moves every fill."""
    assert _price_precision(make_bars(["100.12", "101.34"])) == 2
    assert _price_precision(make_bars(["1.23456", "1.23457"])) == 5
    # Whole numbers still get two places -- an equity priced at 100 is not a
    # zero-precision instrument.
    assert _price_precision(make_bars([100, 101])) == 2
    # Float noise must not dictate an instrument's tick size.
    assert _price_precision(make_bars([str(0.1 + 0.2), "100.50"])) <= 9


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------

def test_refuses_an_empty_window():
    with pytest.raises(InsufficientData):
        run_spec(ma_crossover("EQ:XNAS:TEST"), [])


def test_refuses_a_window_shorter_than_the_warmup():
    """A 200-bar SMA over 30 bars produces numbers. They mean nothing."""
    with pytest.raises(InsufficientData):
        run_spec(ma_crossover("EQ:XNAS:TEST", fast=50, slow=200), make_bars(trending(30)))


# ---------------------------------------------------------------------------
# a real run
# ---------------------------------------------------------------------------

def test_a_crossover_run_produces_positions_and_a_curve():
    run = run_spec(
        ma_crossover("EQ:XNAS:TEST", fast=5, slow=20), make_bars(trending())
    )
    body = run.to_dict()

    assert body["meta"]["engine"] == "nautilus_trader"
    assert body["meta"]["bars"] == 160
    # The strategy ran without raising. If this fails, read `diagnostics`.
    assert body["diagnostics"]["errors"] == []
    assert body["diagnostics"]["bars_seen"] == 160
    assert body["meta"]["total_positions"] > 0
    assert body["positions"], "a run with positions must report them"
    # The equity curve comes from the engine's account bookkeeping.
    assert len(body["equity"]) >= 2
    assert all("total" in point and "time" in point for point in body["equity"])


def test_money_crosses_the_wire_as_strings():
    """`UI Stack §8` — money never becomes an IEEE double."""
    run = run_spec(ma_crossover("EQ:XNAS:TEST", fast=5, slow=20), make_bars(trending()))
    body = run.to_dict()
    for point in body["equity"]:
        assert isinstance(point["total"], str)
    for position in body["positions"]:
        assert isinstance(position["realized_pnl"], str)
        assert isinstance(position["quantity"], str)


def test_statistics_keep_nautilus_three_way_split():
    """Flattening loses the difference between a currency figure and a ratio."""
    run = run_spec(ma_crossover("EQ:XNAS:TEST", fast=5, slow=20), make_bars(trending()))
    stats = run.to_dict()["stats"]
    assert set(stats) == {"pnls", "returns", "general"}
    # PnL statistics are keyed by currency, because a multi-currency run has
    # one block per currency and a flat dict would collide.
    assert all(isinstance(block, dict) for block in stats["pnls"].values())


def test_nan_statistics_become_null_not_the_string_nan():
    """A metric tile must render an em dash, never "NaN"."""
    # Two bars of data after warm-up: several ratios are undefined.
    run = run_spec(
        StrategySpec(
            name="never fires", symbol_id="EQ:XNAS:TEST",
            entry=(Rule(left=Indicator(kind="close"), op="gt",
                        right=Indicator(kind="constant", value=1e9)),),
            exit=(), stop=Stop(kind="percent", mult=5.0),
            sizing=Sizing(kind="fixed_units", units=1.0),
        ),
        make_bars(trending(60)),
    )
    for value in run.stats_returns.values():
        assert value is None or isinstance(value, float)
        assert value == value or value is None  # no NaN survived


# ---------------------------------------------------------------------------
# the honesty machinery
# ---------------------------------------------------------------------------

def test_a_strategy_that_never_fires_says_so_rather_than_reporting_zeroes():
    run = run_spec(
        StrategySpec(
            name="impossible", symbol_id="EQ:XNAS:TEST",
            entry=(Rule(left=Indicator(kind="close"), op="gt",
                        right=Indicator(kind="constant", value=1e9)),),
            exit=(), stop=Stop(kind="percent", mult=5.0),
            sizing=Sizing(kind="fixed_units", units=1.0),
        ),
        make_bars(trending(60)),
    )
    assert run.to_dict()["meta"]["total_positions"] == 0
    assert any("no positions were opened" in w for w in run.warnings)
    assert any("empty rather than zero" in w for w in run.warnings)


def test_a_thin_sample_is_labelled_as_inconclusive():
    run = run_spec(ma_crossover("EQ:XNAS:TEST", fast=5, slow=20), make_bars(trending()))
    positions = len(run.positions)
    if 0 < positions < 30:
        assert any("conclusive" in w for w in run.warnings)


def test_untrusted_bars_are_flagged():
    """A tier-3 fill is indicative, and the report has to say so."""
    run = run_spec(
        ma_crossover("EQ:XNAS:TEST", fast=5, slow=20),
        make_bars(trending(), tier=3, source="yfinance"),
    )
    assert any("tier 3" in w for w in run.warnings)


def test_engine_version_is_recorded_with_every_run():
    """A report is only reproducible against the engine that produced it."""
    run = run_spec(ma_crossover("EQ:XNAS:TEST", fast=5, slow=20), make_bars(trending()))
    meta = run.to_dict()["meta"]
    assert meta["engine"] == "nautilus_trader"
    assert meta["engine_version"] and meta["engine_version"] != "unknown"
