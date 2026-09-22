# Spec: Genesis Markdown/20-Agents/Journal/Agent — Performance Analyst.md
"""R-multiple statistics, and the sample-size discipline baked into the type.

Agent — Performance Analyst names the failure mode this module is built against:

> The most common way performance analysis misleads is by slicing a small sample
> into smaller ones until something looks significant.

Three design decisions follow, and all three are structural rather than advisory:

**Nothing here returns a bare number.** Every result is a :class:`Sample` or a
:class:`Slice`, and both carry ``n``. A caller *cannot* obtain an expectancy
without also holding the count it was computed from, which is the mechanical
form of *"always state the sample size in the same breath as the finding"*.

**Under-evidenced results say so about themselves.** ``Sample.conclusive`` and
``Sample.qualifier()`` are properties of the result, not of the report. A note
that forgets to mention its sample size has to work at it.

**Everything is in R, not dollars.** R is risk-normalised, so a $200 account and
a $200k account produce comparable statistics, a position sized down by the risk
engine does not distort the series, and expectancy means the same thing across
strategies. Dollar figures are reported alongside; they are never what a
comparison is made on.

Empty input returns empty results with ``n=0`` and ``None`` values -- never zero.
A zero expectancy and no data are different facts, and a report that renders them
identically is a report that will eventually say "your edge is zero" about a week
in which you did not trade.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

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

#: Below this, a result is *indicative, not conclusive*. Agent — Performance
#: Analyst's default threshold.
CONCLUSIVE_N = 20

#: Below this, no behavioural recommendation may be made. *"'Not enough data
#: yet' is a complete and valuable answer, and you should give it often."*
RECOMMEND_N = 30


@dataclass(frozen=True)
class Sample:
    """A set of R multiples, summarised. Never separable from its ``n``."""

    n: int
    net_r: float = 0.0
    expectancy_r: float | None = None
    win_rate: float | None = None
    avg_win_r: float | None = None
    avg_loss_r: float | None = None
    #: Gross wins over gross losses. ``None`` when there were no losses -- an
    #: infinite profit factor is not a number and printing one is a lie about a
    #: three-trade sample.
    profit_factor: float | None = None
    #: Expectancy over the standard deviation of R. The system-quality figure;
    #: not a Sharpe ratio and deliberately not called one, because it is
    #: per-trade rather than per-period and annualising it would be nonsense.
    expectancy_over_sigma: float | None = None
    max_drawdown_r: float = 0.0
    best_r: float | None = None
    worst_r: float | None = None
    pnl_net: float = 0.0

    @property
    def conclusive(self) -> bool:
        return self.n >= CONCLUSIVE_N

    @property
    def actionable(self) -> bool:
        """Whether a behavioural recommendation may rest on this.

        Separate from ``conclusive`` because the thresholds differ and the
        consequences differ: describing a slice is cheaper than telling someone
        to change how they trade.
        """
        return self.n >= RECOMMEND_N

    def qualifier(self) -> str:
        if self.n == 0:
            return "no trades"
        if not self.conclusive:
            return f"{self.n} trades — indicative, not conclusive"
        return f"{self.n} trades"

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "net_r": _round(self.net_r),
            "expectancy_r": _round(self.expectancy_r),
            "win_rate": _round(self.win_rate),
            "avg_win_r": _round(self.avg_win_r),
            "avg_loss_r": _round(self.avg_loss_r),
            "profit_factor": _round(self.profit_factor),
            "expectancy_over_sigma": _round(self.expectancy_over_sigma),
            "max_drawdown_r": _round(self.max_drawdown_r),
            "best_r": _round(self.best_r),
            "worst_r": _round(self.worst_r),
            "pnl_net": _round(self.pnl_net, 2),
            "conclusive": self.conclusive,
        }


@dataclass(frozen=True)
class Slice:
    """One cut of the data: a dimension, a value, and the sample inside it."""

    dimension: str
    value: str
    sample: Sample

    @property
    def n(self) -> int:
        return self.sample.n

    def sentence(self) -> str:
        """The finding with its sample size in the same breath. Not a footnote."""
        if self.sample.expectancy_r is None:
            return f"{self.value}: no completed trades"
        return (
            f"{self.value} has an expectancy of {self.sample.expectancy_r:+.2f}R "
            f"over {self.sample.qualifier()}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {"dim": self.dimension, "value": self.value, **self.sample.to_dict()}


def summarize(
    r_multiples: Sequence[float | None], *, pnl: Sequence[float] | None = None
) -> Sample:
    """The whole statistical surface of a set of trades.

    ``None`` R multiples are dropped rather than treated as zero. A trade whose
    R could not be computed -- no planned stop, so no risk unit -- is not a
    breakeven trade, and counting it as one would drag every expectancy toward
    zero in proportion to how sloppy the record-keeping was.
    """
    values = [float(r) for r in r_multiples if r is not None and math.isfinite(r)]
    money = float(sum(pnl)) if pnl else 0.0
    if not values:
        return Sample(n=0, pnl_net=money)

    wins = [r for r in values if r > 0]
    losses = [r for r in values if r <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)

    sigma = _stdev(values)
    expectancy = sum(values) / len(values)

    return Sample(
        n=len(values),
        net_r=sum(values),
        expectancy_r=expectancy,
        win_rate=len(wins) / len(values),
        avg_win_r=(gross_win / len(wins)) if wins else None,
        avg_loss_r=(sum(losses) / len(losses)) if losses else None,
        # None rather than inf: a sample with no losers has no profit factor,
        # and "inf" in a report reads as a result rather than as an absence.
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else None,
        expectancy_over_sigma=(expectancy / sigma) if sigma > 0 else None,
        max_drawdown_r=drawdown_r(values),
        best_r=max(values),
        worst_r=min(values),
        pnl_net=money,
    )


def equity_curve_r(r_multiples: Sequence[float]) -> list[float]:
    """Cumulative R, starting at zero. The series everything else reads."""
    total = 0.0
    out = [0.0]
    for value in r_multiples:
        total += value
        out.append(total)
    return out


def drawdown_r(r_multiples: Sequence[float]) -> float:
    """Worst peak-to-trough decline of the cumulative R curve, as a positive number.

    Computed on the R curve rather than on dollars deliberately: a drawdown in
    dollars conflates a bad run with a period of larger position sizes, and it
    is the bad run that anybody needs to know about.
    """
    peak = 0.0
    worst = 0.0
    total = 0.0
    for value in r_multiples:
        total += value
        peak = max(peak, total)
        worst = min(worst, total - peak)
    return abs(worst)


def streaks(outcomes: Sequence[bool]) -> dict[str, int]:
    """Longest and current runs. The input to every sequence-effect finding."""
    longest_win = longest_loss = current = 0
    current_kind: bool | None = None
    for won in outcomes:
        if won == current_kind:
            current += 1
        else:
            current_kind, current = won, 1
        if won:
            longest_win = max(longest_win, current)
        else:
            longest_loss = max(longest_loss, current)
    return {
        "longest_win": longest_win,
        "longest_loss": longest_loss,
        "current": current if current_kind is not None else 0,
        "current_is_win": bool(current_kind) if current_kind is not None else False,
    }


def slice_by(
    rows: Iterable[Any],
    dimension: str,
    key: Callable[[Any], Any],
    *,
    r_of: Callable[[Any], float | None] = lambda row: getattr(row, "r_multiple", None),
    pnl_of: Callable[[Any], float] = lambda row: float(getattr(row, "pnl_net", 0.0) or 0.0),
    min_n: int = 1,
) -> list[Slice]:
    """Group rows by one dimension and summarise each group.

    Sorted by expectancy descending so the best and worst slices are the first
    and last elements -- which is what the weekly review reads, and computing it
    here means no caller re-sorts and accidentally reports the wrong end.

    ``key`` returning ``None`` drops the row from that dimension rather than
    creating a "None" bucket. A trade with no recorded setup is not evidence
    about a setup called None.
    """
    buckets: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        value = key(row)
        if value is None or value == "":
            continue
        buckets[str(value)].append(row)

    out = [
        Slice(
            dimension=dimension,
            value=value,
            sample=summarize([r_of(r) for r in group], pnl=[pnl_of(r) for r in group]),
        )
        for value, group in buckets.items()
    ]
    out = [s for s in out if s.n >= min_n]
    return sorted(
        out,
        key=lambda s: (
            s.sample.expectancy_r if s.sample.expectancy_r is not None else -math.inf
        ),
        reverse=True,
    )


def calibration(
    rows: Iterable[Any],
    *,
    confidence_of: Callable[[Any], float | None],
    r_of: Callable[[Any], float | None] = lambda row: getattr(row, "r_multiple", None),
    buckets: Sequence[tuple[float, float]] = (
        (0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)
    ),
) -> dict[str, Any]:
    """Is stated confidence predictive? The feedback loop that keeps scoring honest.

    Agent — Performance Analyst calls this one of the two highest-value analyses
    in the system, and the reason is that it grades the *grader*: if
    0.7-confidence ideas do not outperform 0.4-confidence ideas, the scoring is
    broken and every downstream ranking is noise.

    ``monotonic`` is the whole verdict, and it is deliberately strict: a scoring
    system is calibrated when higher confidence means higher realised R, in
    order, with no inversions. Anything less is reported as not calibrated
    rather than as approximately calibrated.
    """
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        confidence = confidence_of(row)
        r = r_of(row)
        if confidence is None or r is None:
            continue
        for low, high in buckets:
            if low <= confidence < high:
                grouped[f"{low:.1f}-{high:.1f}"].append(float(r))
                break

    ordered = sorted(grouped.items())
    rows_out = [
        {"bucket": name, "n": len(values), "avg_r": _round(sum(values) / len(values))}
        for name, values in ordered
        if values
    ]
    total = sum(row["n"] for row in rows_out)
    averages = [row["avg_r"] for row in rows_out]
    monotonic = all(a <= b for a, b in zip(averages, averages[1:])) if len(averages) > 1 else None

    if total < CONCLUSIVE_N:
        verdict = f"too few graded trades ({total}) to judge calibration"
    elif monotonic is True:
        verdict = "directionally calibrated — higher confidence produced higher R"
    elif monotonic is False:
        verdict = "not calibrated — higher confidence did not produce higher R"
    else:
        verdict = "only one confidence bucket has trades; nothing to compare"

    return {"buckets": rows_out, "n": total, "monotonic": monotonic, "verdict": verdict}


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _round(value: float | None, places: int = 3) -> float | None:
    return None if value is None else round(float(value), places)
