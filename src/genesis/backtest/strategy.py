# Spec: Genesis Markdown/70-Schemas/Strategy Schema.md
"""A strategy as data, not as code.

The hard rule this file exists to satisfy is `CLAUDE.md` #3: *"Nothing
safety-critical or arithmetic runs on an LLM. The whole execution family, plus
backtest, metrics, allocation and level-watch, are ``tier: none``. A language
model never sizes a position or computes a stop."*

That rule is easy to state and easy to violate by accident, because the natural
way to build "Genesis, write me a MACD crossover strategy" is to have a model
emit Python and run it. Then the model *is* the backtest engine, its arithmetic
is unauditable, and a hallucinated ``>`` for a ``>=`` silently becomes a
result somebody trades on.

So the boundary is drawn here instead:

- **The model authors a** :class:`StrategySpec` — a declarative object drawn
  from a closed vocabulary of rules. That is language work: mapping "MACD
  crossover" onto ``cross_above(macd, macd_signal)``. It is exactly what a
  language model is good at, and it is verifiable by inspection.
- **The engine computes.** Every number — indicator values, entry price, stop
  distance, position size, R multiple — is produced by deterministic NumPy in
  ``engine.py``. The model never sees a float it is expected to be right
  about.

The vocabulary is closed on purpose. There is no ``expression: str`` field and
no ``eval``. A spec that cannot be expressed in these rules is a spec this
engine refuses to run, which is the correct failure: an unsupported strategy
should be a clear rejection, not a quietly wrong backtest.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "StrategySpec", "Rule", "Indicator", "Stop", "Sizing", "Costs",
    "INDICATOR_KINDS", "RULE_OPS",
]

#: Every indicator the engine can compute. A spec naming anything else is
#: rejected at parse time rather than at bar 400 of a run.
INDICATOR_KINDS = (
    "close", "open", "high", "low", "volume",
    "sma", "ema", "rsi", "macd", "macd_signal", "macd_hist",
    "atr", "rolling_high", "rolling_low", "vwap", "constant",
)

#: Comparison operators. ``cross_above``/``cross_below`` are stateful across
#: two bars and are the reason this is not just a set of comparisons: a
#: crossover is an *event*, and testing ``a > b`` fires on every bar of a trend
#: rather than on the bar the trend began.
RULE_OPS = ("gt", "lt", "gte", "lte", "cross_above", "cross_below")

#: Indicators that read a single bar and therefore need no warm-up window.
_WINDOWLESS = frozenset({"close", "open", "high", "low", "volume", "constant"})


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Indicator(_Frozen):
    """One computed series, named so rules can refer to it."""

    kind: Literal[INDICATOR_KINDS]  # type: ignore[valid-type]
    #: Primary lookback. Meaning depends on ``kind``: the period of an SMA,
    #: the fast leg of a MACD, the window of a rolling high.
    period: int = Field(default=14, ge=1, le=2000)
    #: MACD only: slow period and signal period. Named rather than positional
    #: because "macd(12, 26, 9)" is three magic numbers at every call site.
    slow: int = Field(default=26, ge=1, le=2000)
    signal: int = Field(default=9, ge=1, le=2000)
    #: ``constant`` only — lets a rule say "RSI crosses above 70".
    value: float = 0.0
    #: Which price series to compute over, where that is a choice.
    on: Literal["open", "high", "low", "close", "volume"] = "close"

    @model_validator(mode="after")
    def _coherent(self) -> "Indicator":
        if self.kind == "macd" or self.kind in ("macd_signal", "macd_hist"):
            if self.slow <= self.period:
                raise ValueError(
                    f"macd slow ({self.slow}) must exceed fast ({self.period}); "
                    "a slow leg shorter than the fast one inverts the histogram"
                )
        return self

    @property
    def key(self) -> str:
        """Stable identity, so two rules naming the same series share one
        computation and one cache entry."""
        return f"{self.kind}:{self.on}:{self.period}:{self.slow}:{self.signal}:{self.value}"


class Rule(_Frozen):
    """``left <op> right`` over two indicator series."""

    left: Indicator
    op: Literal[RULE_OPS]  # type: ignore[valid-type]
    right: Indicator


class Stop(_Frozen):
    """Where the trade is wrong. Required — see the validator.

    ``kind: none`` is deliberately absent. Without a stop there is no risk
    unit, so there is no R multiple, so ``genesis.metrics`` has nothing to
    summarise and the whole report degrades to raw P&L with no way to compare
    one strategy to another. `Agent — Performance Analyst` is built on R;
    a strategy that cannot express its risk cannot be evaluated by it.
    """

    kind: Literal["atr", "percent", "fixed"] = "atr"
    #: ATR multiple, or percent of entry, or absolute price distance.
    mult: float = Field(default=2.0, gt=0, le=100)
    period: int = Field(default=14, ge=1, le=500)


class Target(_Frozen):
    """Optional profit target, expressed in R so it is scale-free."""

    r_multiple: float | None = Field(default=None, gt=0, le=100)


class Sizing(_Frozen):
    """How large. Risk-based by default, because that is what makes R mean
    anything: one R lost is the same fraction of the account every time."""

    kind: Literal["risk_pct", "fixed_units", "fixed_notional"] = "risk_pct"
    #: ``risk_pct``: the fraction of equity put at risk between entry and stop.
    pct: float = Field(default=1.0, gt=0, le=100)
    units: float = Field(default=1.0, gt=0)
    notional: float = Field(default=10_000.0, gt=0)


class Costs(_Frozen):
    """Frictions. Defaulted to non-zero on purpose.

    A backtest with zero costs is not a neutral baseline — it is an optimistic
    one, and the optimism is largest exactly where it is most dangerous, in
    high-frequency strategies that look best before fees. `Agent — Backtest
    Vs Live Drift` exists because the gap between simulated and real fills is
    the normal way a strategy dies; starting the simulation at zero guarantees
    the gap is discovered late.
    """

    #: Fraction of the fill price lost to spread and market impact, per side.
    slippage_bps: float = Field(default=2.0, ge=0, le=1000)
    #: Currency per unit traded, per side.
    commission_per_unit: float = Field(default=0.005, ge=0)


class StrategySpec(_Frozen):
    """A complete, runnable strategy description."""

    name: str = Field(min_length=1, max_length=120)
    symbol_id: str
    timeframe: str = "1D"
    #: Long-only unless stated. Short support is real but opt-in, because a
    #: short backtest that ignores borrow cost and locate risk is a different
    #: kind of wrong from a long one and should be chosen deliberately.
    direction: Literal["long", "short", "both"] = "long"

    entry: tuple[Rule, ...] = Field(min_length=1)
    #: Rules that close a position. May be empty when a stop and a target
    #: fully define the exit.
    exit: tuple[Rule, ...] = ()

    stop: Stop = Stop()
    target: Target = Target()
    sizing: Sizing = Sizing()
    costs: Costs = Costs()

    starting_equity: float = Field(default=100_000.0, gt=0)
    #: Bars to skip before trading is allowed, so an indicator's warm-up
    #: period cannot produce a signal from a half-filled window.
    warmup: int = Field(default=0, ge=0, le=5000)

    #: Free-text provenance: who asked for this, and in what words. Kept so a
    #: report can show the sentence that produced the strategy next to the
    #: numbers it produced.
    prompt: str | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "StrategySpec":
        if not self.exit and self.target.r_multiple is None:
            # A stop alone is a valid strategy (stop-and-reverse aside), but
            # it is unusual enough that saying so beats silently running it.
            pass
        return self

    @property
    def required_warmup(self) -> int:
        """The longest lookback any rule needs, so the engine can refuse to
        trade before every series it reads is fully formed."""
        longest = 0
        for rule in (*self.entry, *self.exit):
            for ind in (rule.left, rule.right):
                # `close`, `open`, `constant` and friends carry a `period`
                # field they never read. Counting it would charge a raw-price
                # rule fourteen bars of warm-up it does not need, silently
                # truncating the front of every backtest that uses one.
                if ind.kind in _WINDOWLESS:
                    continue
                longest = max(longest, ind.period)
                if ind.kind.startswith("macd"):
                    longest = max(longest, ind.slow + ind.signal)
        # Only an ATR stop needs a warm-up window. A percent or fixed stop is
        # computed from the entry price alone, and charging it fourteen bars
        # of warm-up would silently shorten every such backtest.
        if self.stop.kind == "atr":
            longest = max(longest, self.stop.period)
        return max(longest, self.warmup)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# convenience constructors — the shapes people actually ask for out loud
# ---------------------------------------------------------------------------

def macd_crossover(
    symbol_id: str, *, timeframe: str = "1D", fast: int = 12, slow: int = 26,
    signal: int = 9, **kwargs: Any,
) -> StrategySpec:
    """"Create a MACD crossover strategy" — resolved without a model.

    This is the shape the user asks for by name, so it is a named function
    rather than something the planner has to assemble from primitives every
    time. The model's job shrinks to *recognising* the request and filling in
    the symbol; it never has to get 12/26/9 right, and it cannot get the
    crossover direction backwards.
    """
    macd = Indicator(kind="macd", period=fast, slow=slow, signal=signal)
    sig = Indicator(kind="macd_signal", period=fast, slow=slow, signal=signal)
    return StrategySpec(
        name=f"MACD {fast}/{slow}/{signal} crossover",
        symbol_id=symbol_id,
        timeframe=timeframe,
        entry=(Rule(left=macd, op="cross_above", right=sig),),
        exit=(Rule(left=macd, op="cross_below", right=sig),),
        **kwargs,
    )


def ma_crossover(
    symbol_id: str, *, fast: int = 50, slow: int = 200, timeframe: str = "1D",
    **kwargs: Any,
) -> StrategySpec:
    """The golden cross, and its inverse as the exit."""
    f = Indicator(kind="sma", period=fast)
    s = Indicator(kind="sma", period=slow)
    return StrategySpec(
        name=f"SMA {fast}/{slow} crossover",
        symbol_id=symbol_id,
        timeframe=timeframe,
        entry=(Rule(left=f, op="cross_above", right=s),),
        exit=(Rule(left=f, op="cross_below", right=s),),
        **kwargs,
    )


def rsi_reversion(
    symbol_id: str, *, period: int = 14, oversold: float = 30.0,
    overbought: float = 70.0, timeframe: str = "1D", **kwargs: Any,
) -> StrategySpec:
    rsi = Indicator(kind="rsi", period=period)
    return StrategySpec(
        name=f"RSI({period}) mean reversion {oversold:g}/{overbought:g}",
        symbol_id=symbol_id,
        timeframe=timeframe,
        entry=(Rule(left=rsi, op="cross_above",
                    right=Indicator(kind="constant", value=oversold)),),
        exit=(Rule(left=rsi, op="cross_above",
                   right=Indicator(kind="constant", value=overbought)),),
        **kwargs,
    )


def breakout(
    symbol_id: str, *, period: int = 20, exit_period: int = 10,
    timeframe: str = "1D", **kwargs: Any,
) -> StrategySpec:
    """Donchian-style: buy the n-bar high, leave on the m-bar low."""
    return StrategySpec(
        name=f"{period}-bar breakout / {exit_period}-bar exit",
        symbol_id=symbol_id,
        timeframe=timeframe,
        entry=(Rule(left=Indicator(kind="close"), op="cross_above",
                    right=Indicator(kind="rolling_high", period=period)),),
        exit=(Rule(left=Indicator(kind="close"), op="cross_below",
                   right=Indicator(kind="rolling_low", period=exit_period)),),
        **kwargs,
    )


#: Named templates the command layer and the planner can resolve by keyword.
TEMPLATES = {
    "macd": macd_crossover,
    "ma": ma_crossover,
    "sma": ma_crossover,
    "golden-cross": ma_crossover,
    "rsi": rsi_reversion,
    "breakout": breakout,
}
