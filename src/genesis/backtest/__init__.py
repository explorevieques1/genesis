# Spec: Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md
"""Backtesting, on `nautilus_trader`.

Genesis does not implement a simulator. `nautilus_trader` is the engine — its
venue fills the orders, its portfolio does the accounting, its analysis module
computes the statistics. This package is the boundary either side of it:

- :mod:`genesis.backtest.strategy` — a strategy as declarative data, so a model
  can author one without writing code that computes.
- :mod:`genesis.backtest.spec_strategy` — the single allow-listed Nautilus
  ``Strategy`` that interprets such a spec.
- :mod:`genesis.backtest.runner` — build the engine, run it, normalise the
  reports into a stable shape for the UI.
"""

from genesis.backtest.runner import (
    BacktestRun, BacktestUnavailable, InsufficientData, run_spec,
)
from genesis.backtest.strategy import StrategySpec, TEMPLATES

__all__ = [
    "run_spec", "BacktestRun", "BacktestUnavailable", "InsufficientData",
    "StrategySpec", "TEMPLATES",
]
