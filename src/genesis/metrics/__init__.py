# Spec: Genesis Markdown/50-Risk/Safety Invariants.md
"""Performance arithmetic. One implementation, and no model anywhere near it.

Safety Invariants §3: *"Nothing safety-critical or arithmetic runs on an LLM.
The whole execution family, plus backtest, metrics, allocation and level-watch,
are `tier: none`."* This package is the metrics half of that sentence.

It lives outside `journal/` on purpose. Agent — Performance Analyst is explicit
that every slice goes *"via Agent — Risk Metrics — one implementation,
consistent numbers"*, and Agent — Backtest Vs Live Drift compares live results
against backtest results using the same statistics. Three consumers, one
implementation: two would eventually disagree about what a win rate is, and the
disagreement would surface as a strategy that looks profitable in one report and
not in another.

Agent — Risk Metrics (Phase 5) will wrap this rather than reimplement it.
"""

from genesis.metrics.core import (
    CONCLUSIVE_N,
    RECOMMEND_N,
    Sample,
    Slice,
    calibration,
    drawdown_r,
    equity_curve_r,
    slice_by,
    streaks,
    summarize,
)

__all__ = [
    "CONCLUSIVE_N",
    "RECOMMEND_N",
    "Sample",
    "Slice",
    "calibration",
    "drawdown_r",
    "equity_curve_r",
    "slice_by",
    "streaks",
    "summarize",
]
