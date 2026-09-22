# Spec: Genesis Markdown/20-Agents/Journal/Agent — Backtest Vs Live Drift.md
"""Live versus backtest: is this variance, or is something actually wrong?

The note's discipline in one line: *"47 live trades against a 400-trade backtest
is a small sample. This agent must not cry wolf on normal variance."*

Two rules make that real, and both are here rather than in a prompt:

**Compare against the distribution, not the point estimate.** A z-score, using
the backtest's own dispersion. A strategy running 20% below its backtest
expectancy over 40 trades is probably fine; one whose losses are systematically
larger over the same 40 is not, and only the distribution can tell them apart.

**Thirty live trades minimum.** Below that :func:`compare` returns
``significant: False`` regardless of how bad the numbers look, because below
that the numbers cannot mean anything.

The diagnosis is the actual product. *"It's not working"* is not an output. The
signature table -- what matches and what does not -- is what separates a regime
change from an implementation bug, and those have opposite responses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from genesis.metrics import Sample

__all__ = ["MIN_LIVE_TRADES", "DriftReport", "Expectation", "compare"]

#: Below this, no divergence claim. The note's number.
MIN_LIVE_TRADES = 30

#: |z| beyond which a gap is distributionally different rather than unlucky.
#: Two standard deviations, which on a one-sided read is roughly a 1-in-40
#: coincidence -- loose enough to catch a real problem, tight enough that a
#: nightly check over a handful of strategies is not constantly firing.
SIGNIFICANT_Z = 2.0

Cause = Literal["variance", "regime", "implementation", "costs", "overfit", "unknown"]


@dataclass(frozen=True)
class Expectation:
    """What the backtest said, as a distribution rather than a number."""

    expectancy_r: float
    #: Per-trade standard deviation of R in the backtest. Without it there is no
    #: distribution to compare against and the whole method collapses to
    #: subtracting two numbers.
    sigma_r: float
    trades: int
    win_rate: float | None = None
    avg_win_r: float | None = None
    avg_loss_r: float | None = None
    trades_per_week: float | None = None
    assumed_slippage_bps: float | None = None
    regime: str | None = None
    #: How many optimiser trials produced this. The overfit tell.
    optimizer_trials: int = 0


@dataclass(frozen=True)
class DriftReport:
    strategy: str
    live: Sample
    expected: Expectation
    z: float | None
    significant: bool
    primary_gap: str | None
    likely_cause: Cause
    reasoning: str
    severity: Literal["none", "low", "medium", "high", "critical"]
    recommendation: str
    measures: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "live": self.live.to_dict(),
            "backtest_oos": {
                "expectancy_r": self.expected.expectancy_r,
                "sigma_r": self.expected.sigma_r,
                "trades": self.expected.trades,
                "win_rate": self.expected.win_rate,
                "avg_win_r": self.expected.avg_win_r,
                "avg_loss_r": self.expected.avg_loss_r,
            },
            "divergence": {
                "expectancy_z": None if self.z is None else round(self.z, 2),
                "significant": self.significant,
                "primary_gap": self.primary_gap,
            },
            "diagnosis": {
                "likely_cause": self.likely_cause,
                "reasoning": self.reasoning,
            },
            "severity": self.severity,
            "recommendation": self.recommendation,
            "measures": self.measures,
        }

    def spoken(self) -> str:
        if self.z is None:
            # Below the minimum there is no comparison, and saying "within its
            # backtest distribution" would be a claim the sample cannot support
            # -- the most respectable-looking way for this agent to mislead.
            return (
                f"{self.strategy} has {self.live.n} live trades — not enough to "
                f"compare against the backtest yet."
            )
        if not self.significant:
            return (
                f"{self.strategy} is within its backtest distribution "
                f"({self.live.qualifier()})."
            )
        return (
            f"{self.strategy} has diverged from its backtest — "
            f"{self.reasoning} {self.recommendation}"
        )


def compare(
    strategy: str,
    live: Sample,
    expected: Expectation,
    *,
    live_regime: str | None = None,
    live_slippage_bps: float | None = None,
    live_trades_per_week: float | None = None,
) -> DriftReport:
    """Score a live strategy against its backtest distribution and diagnose the gap."""
    if live.n < MIN_LIVE_TRADES or live.expectancy_r is None:
        return DriftReport(
            strategy=strategy, live=live, expected=expected, z=None,
            significant=False, primary_gap=None, likely_cause="unknown",
            reasoning=(
                f"{live.n} live trades is below the {MIN_LIVE_TRADES}-trade "
                f"minimum; nothing can be concluded yet."
            ),
            severity="none",
            recommendation="Keep watching.",
            measures={"live_trades": live.n},
        )

    # The standard error of the live mean under the backtest's dispersion. This
    # is what makes a small sample *expected* to wander: with 30 trades and a
    # sigma of 1.2R the mean moves +/- 0.22R for free.
    standard_error = expected.sigma_r / math.sqrt(live.n) if expected.sigma_r > 0 else 0.0
    z = (live.expectancy_r - expected.expectancy_r) / standard_error if standard_error else 0.0
    significant = abs(z) >= SIGNIFICANT_Z and z < 0

    gap, cause, reasoning = _diagnose(
        live, expected, live_regime, live_slippage_bps, live_trades_per_week
    )
    if not significant:
        return DriftReport(
            strategy=strategy, live=live, expected=expected, z=z, significant=False,
            primary_gap=gap, likely_cause="variance",
            reasoning=(
                f"Live expectancy {live.expectancy_r:+.2f}R against a backtest "
                f"{expected.expectancy_r:+.2f}R is {abs(z):.1f} standard errors — "
                f"inside normal variance over {live.n} trades."
            ),
            severity="low" if z < -1.0 else "none",
            recommendation="No action. Most underperformance is noise.",
            measures={"z": round(z, 2), "standard_error": round(standard_error, 3)},
        )

    severity, recommendation = _escalate(cause, z)
    return DriftReport(
        strategy=strategy, live=live, expected=expected, z=z, significant=True,
        primary_gap=gap, likely_cause=cause, reasoning=reasoning,
        severity=severity, recommendation=recommendation,
        measures={
            "z": round(z, 2),
            "standard_error": round(standard_error, 3),
            "live_expectancy_r": live.expectancy_r,
            "backtest_expectancy_r": expected.expectancy_r,
        },
    )


def _diagnose(
    live: Sample,
    expected: Expectation,
    live_regime: str | None,
    live_slippage_bps: float | None,
    live_trades_per_week: float | None,
) -> tuple[str | None, Cause, str]:
    """The signature table from the note, in order of how telling each signal is.

    Order matters. Frequency is checked first because a signal that is not
    firing explains everything downstream and nothing else needs explaining;
    costs are checked before regime because a cost gap is measurable and a
    regime gap is inferred.
    """
    # Never matched from day one, on a heavily optimised strategy. The note calls
    # this the most common cause and the hardest to admit, so it is checked
    # explicitly rather than left to fall through to "unknown".
    if expected.optimizer_trials >= 200 and live.n >= MIN_LIVE_TRADES:
        if live.expectancy_r is not None and live.expectancy_r < expected.expectancy_r * 0.3:
            return (
                "expectancy",
                "overfit",
                f"The backtest came from {expected.optimizer_trials} optimiser trials "
                f"and live results never approached it. That is the signature of a "
                f"curve fit, not of a market that changed.",
            )

    if expected.trades_per_week and live_trades_per_week:
        ratio = live_trades_per_week / expected.trades_per_week
        if ratio < 0.6:
            return (
                "trades_per_week",
                "implementation",
                f"Live trade frequency is {ratio:.0%} of the backtest's. The signal "
                f"is not firing as designed — check the entry condition and the data "
                f"feeding it.",
            )
        if ratio > 1.6:
            return (
                "trades_per_week",
                "implementation",
                f"Live trade frequency is {ratio:.0%} of the backtest's. The signal "
                f"is firing on bars it should not — a lookahead removed in live may "
                f"still be present in the backtest.",
            )

    if (
        live_slippage_bps is not None
        and expected.assumed_slippage_bps is not None
        and live_slippage_bps > expected.assumed_slippage_bps * 2.5
    ):
        return (
            "costs",
            "costs",
            f"Live slippage is {live_slippage_bps:.1f} bps against an assumed "
            f"{expected.assumed_slippage_bps:.1f}. The strategy is paying more to "
            f"trade than the backtest allowed for.",
        )

    if expected.avg_loss_r and live.avg_loss_r and live.avg_loss_r < expected.avg_loss_r * 1.25:
        return (
            "avg_loss_r",
            "implementation",
            f"Losses average {live.avg_loss_r:.2f}R against an expected "
            f"{expected.avg_loss_r:.2f}R. Stops are slipping, gapping, or not being "
            f"placed — check the exit path before anything else.",
        )

    if expected.avg_win_r and live.avg_win_r and live.avg_win_r < expected.avg_win_r * 0.8:
        matching_losses = (
            expected.avg_loss_r is not None
            and live.avg_loss_r is not None
            and abs(live.avg_loss_r - expected.avg_loss_r) < abs(expected.avg_loss_r) * 0.2
        )
        return (
            "avg_win_r",
            "implementation",
            (
                f"Winners are {1 - live.avg_win_r / expected.avg_win_r:.0%} smaller "
                f"than the backtest while losses match it. That points at the exit "
                f"path — trailing stop or early exits — not at the market."
                if matching_losses
                else f"Winners are smaller than the backtest expected."
            ),
        )

    if (
        expected.regime
        and live_regime
        and expected.regime != live_regime
        and expected.win_rate
        and live.win_rate
        and live.win_rate < expected.win_rate * 0.85
    ):
        return (
            "win_rate",
            "regime",
            f"Win rate is down while trade sizes match, and the regime moved from "
            f"{expected.regime} to {live_regime}. The strategy is being asked to "
            f"work in tape it was not tested in.",
        )

    return (
        "expectancy",
        "unknown",
        f"Live expectancy is {abs(z_gap(live, expected)):.2f}R below the backtest and "
        f"no single component explains it. Frequency, win rate and trade sizes all "
        f"look close — which is itself informative, and worth a manual look.",
    )


def z_gap(live: Sample, expected: Expectation) -> float:
    return (live.expectancy_r or 0.0) - expected.expectancy_r


def _escalate(cause: Cause, z: float) -> tuple[str, str]:
    """Severity and response. An implementation bug withdraws autonomy.

    Deliberate, and stated in the note: *"if the code might be wrong, autonomy
    is withdrawn until it's proven right."* A regime change is a reason to size
    down; a suspected bug is a reason to stop.
    """
    if cause in ("implementation", "overfit"):
        return (
            "critical",
            "Pause the strategy and demote it to confirm mode until the cause is "
            "found. A suspected implementation fault does not trade unattended.",
        )
    if cause == "costs":
        return ("high", "Reduce size until execution costs are back within assumptions.")
    if cause == "regime":
        return ("high", "Halve size until the regime the strategy was tested in returns.")
    return ("medium", "Note it, keep watching, and review again at 30 more trades.")
