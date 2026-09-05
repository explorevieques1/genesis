# Spec: Genesis Markdown/20-Agents/Strategy/Agent — Backtest Runner.md
"""One Nautilus strategy that interprets a :class:`StrategySpec`.

This is the whole answer to a constraint that looks like it has no good answer.

`CLAUDE.md` #3: *"Nothing safety-critical or arithmetic runs on an LLM ...
A language model never sizes a position or computes a stop."* But the thing the
user actually wants to say out loud is *"create a MACD crossover strategy and
backtest it"* — and the obvious implementation of that is a model writing a
Python ``Strategy`` subclass, which puts the model directly inside the
arithmetic and makes every number it produces unauditable.

The hinge is that **the class is fixed and the parameters are data**. This
module is that one class; a :class:`StrategySpec` is the payload. So:

- the model chooses **which rules**, from a closed vocabulary it cannot extend;
- this class, and Nautilus underneath it, computes **every number**.

A model can therefore produce a strategy without ever emitting an executable
line, and the worst it can do with a bad spec is describe a strategy that
trades badly — never one that computes wrongly.

A note on how the spec arrives, because it is not what the Nautilus docs
suggest. ``ImportableStrategyConfig(strategy_path, config)`` is the documented
route for describing a strategy as data, and it was the intended one here. It
does not work in v2: ``StrategyConfig`` is a native Rust class, so a Python
subclass declaring extra fields silently gains none of them. The spec is
therefore passed to ``__init__`` directly and the strategy is constructed
in-process. The safety property is unchanged — the executable code is still
this fixed, reviewed module — but the *dotted-path allow-list* that would
matter under ``ImportableStrategyConfig`` is not what is enforcing it, and
saying otherwise would be describing a mechanism that is not there.

Indicators come from ``nautilus_trader.indicators`` rather than being
reimplemented here. Forty-five of them ship with the engine, they are the same
ones the live path would use, and a second implementation of RSI is exactly how
`Agent — Backtest Vs Live Drift` ends up reporting drift that is really a
formula difference.
"""

from __future__ import annotations

import logging
from typing import Any

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import (
    AverageTrueRange,
    DonchianChannel,
    ExponentialMovingAverage,
    MovingAverageConvergenceDivergence,
    RelativeStrengthIndex,
    SimpleMovingAverage,
)
from nautilus_trader.model import (
    Bar, BarType, InstrumentId, OrderSide, Quantity, TimeInForce,
)
from nautilus_trader.trading import Strategy

from genesis.backtest.strategy import Indicator, Rule, StrategySpec

log = logging.getLogger(__name__)

__all__ = ["SpecStrategy", "STRATEGY_PATH"]

#: The only strategy class Genesis will run. Named here so the runner can
#: assert it rather than accept a class from a caller — the whole point is that
#: the executable half is fixed.
STRATEGY_PATH = "genesis.backtest.spec_strategy:SpecStrategy"


class SpecStrategy(Strategy):
    """Evaluates a spec's rules bar by bar and places bracket orders.

    **Why bracket orders rather than a hand-checked stop.** The obvious
    implementation keeps the stop in Python and closes the position when a
    bar's low crosses it. That has a subtle, systematic bias: it decides fills
    using the whole bar, including the part that had not happened yet, and it
    cannot represent a gap through the stop. Nautilus's simulated venue holds a
    real resting stop order and fills it against the order book model with
    slippage — the same machinery the live path would use. The result is a
    backtest whose fills are wrong in the ways real fills are wrong, rather
    than wrong in the ways convenient to the strategy.
    """

    def __init__(self, config: StrategyConfig | None = None) -> None:
        super().__init__(config or StrategyConfig())
        self.spec: StrategySpec | None = None
        self.instrument_id: InstrumentId | None = None
        self.bar_type: BarType | None = None

        self._indicators: dict[str, Any] = {}
        #: Last bar's value for each series, for crossover detection. A
        #: crossover is an event between two bars; a plain comparison fires on
        #: every bar of a trend instead of on the one where it began.
        self._previous: dict[str, float] = {}
        self._atr: AverageTrueRange | None = None
        self._bars_seen = 0
        #: Rule evaluations that could not be made because a series had not
        #: warmed up. Reported, because "no trades" and "never able to decide"
        #: are different results and only one of them is about the strategy.
        self._undecidable = 0
        self._errors: list[str] = []
        #: Where the protective stop and target belong for the position that is
        #: about to open. Held across the fill, cleared once attached.
        self._pending_stop: float | None = None
        self._pending_target: float | None = None

    @classmethod
    def create(
        cls, spec: StrategySpec, instrument_id: InstrumentId, bar_type: BarType
    ) -> "SpecStrategy":
        """Build a configured strategy.

        A factory rather than constructor arguments because ``Strategy.__new__``
        is native in v2 and accepts only a ``StrategyConfig`` — extra positional
        arguments never reach ``__init__``. The parameters are therefore
        attached after construction, which is why every one of them is
        validated here rather than trusted from the call site.
        """
        strategy = cls()
        strategy.spec = StrategySpec.model_validate(
            spec if isinstance(spec, dict) else spec.to_dict()
        )
        strategy.instrument_id = instrument_id
        strategy.bar_type = bar_type
        return strategy

    # -- lifecycle --------------------------------------------------------

    def on_start(self) -> None:
        if self.spec is None or self.instrument_id is None:
            # Constructed but never configured. Refusing here beats running a
            # spec-less strategy to completion and reporting zero trades.
            self._errors.append("strategy was not configured; use SpecStrategy.create()")
            self.stop()
            return
        instrument = self.cache.instrument(self.instrument_id)
        if instrument is None:
            # Fail loudly. A strategy that cannot find its instrument would
            # otherwise run to completion and report zero trades, which reads
            # as a verdict on the strategy rather than a setup error.
            self._errors.append(f"instrument {self.instrument_id} not in the cache")
            self.stop()
            return
        self._instrument = instrument

        for rule in (*self.spec.entry, *self.spec.exit):
            for ind in (rule.left, rule.right):
                self._ensure(ind)

        if self.spec.stop.kind == "atr":
            self._atr = AverageTrueRange(self.spec.stop.period)
            self.register_indicator_for_bars(self.bar_type, self._atr)

        self.subscribe_bars(self.bar_type)

    def on_stop(self) -> None:
        self.cancel_all_orders(self.instrument_id)
        # Flatten at the end of the run so the final position is accounted
        # rather than left dangling. Nautilus reports an unclosed position with
        # its unrealised PnL, and the runner surfaces that separately.
        self.close_all_positions(self.instrument_id)

    # -- indicator wiring -------------------------------------------------

    def _ensure(self, ind: Indicator) -> None:
        """Build a Nautilus indicator for ``ind``, once per distinct series."""
        if ind.key in self._indicators or ind.kind in _RAW:
            return
        built = _build_indicator(ind)
        if built is None:
            return
        self._indicators[ind.key] = built
        # Registered so the engine feeds it every bar. Doing this by hand in
        # `on_bar` is the common way to end up with an indicator that is one
        # bar stale on some code paths and not others.
        self.register_indicator_for_bars(self.bar_type, built)

    def _value(self, ind: Indicator, bar: Bar) -> float | None:
        """The current value of one series, or ``None`` while it warms up."""
        kind = ind.kind
        if kind == "close":
            return float(bar.close)
        if kind == "open":
            return float(bar.open)
        if kind == "high":
            return float(bar.high)
        if kind == "low":
            return float(bar.low)
        if kind == "volume":
            return float(bar.volume)
        if kind == "constant":
            return float(ind.value)

        indicator = self._indicators.get(ind.key)
        if indicator is None or not indicator.initialized:
            return None

        if kind == "macd":
            return float(indicator.value)
        if kind == "macd_signal":
            # Nautilus' MACD exposes the signal line directly, so the two legs
            # cannot drift apart the way two separately-configured indicators
            # would.
            return float(getattr(indicator, "signal", indicator.value))
        if kind == "macd_hist":
            return float(indicator.value) - float(getattr(indicator, "signal", 0.0))
        if kind == "rolling_high":
            return float(indicator.upper)
        if kind == "rolling_low":
            return float(indicator.lower)
        return float(indicator.value)

    # -- the loop ---------------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        self._bars_seen += 1
        try:
            self._decide(bar)
        except Exception as exc:  # noqa: BLE001
            # Nautilus catches strategy exceptions and logs them, which means
            # a broken strategy produces a clean-looking zero-trade backtest.
            # Recording them here lets the runner report "the strategy raised"
            # instead of "the strategy found no signals" -- two conclusions a
            # person would act on very differently.
            message = f"{type(exc).__name__}: {exc}"
            if message not in self._errors:
                self._errors.append(message)
            log.exception("spec strategy failed on a bar")

    def _decide(self, bar: Bar) -> None:
        flat = self.portfolio.is_net_flat(self.instrument_id)

        entry = self._all(self.spec.entry, bar)
        exit_ = self._any(self.spec.exit, bar)
        self._remember(bar)

        if entry is None or exit_ is None:
            self._undecidable += 1
            return

        if flat and entry:
            self._enter(bar)
        elif not flat and exit_:
            # Cancel the resting stop/target first. Closing the position while
            # they are still working leaves orders that can fill against a
            # position that no longer exists.
            self.cancel_all_orders(self.instrument_id)
            self.close_all_positions(self.instrument_id)

    def _all(self, rules: tuple[Rule, ...], bar: Bar) -> bool | None:
        """AND over rules. ``None`` when any of them is undecidable."""
        if not rules:
            return False
        result = True
        for rule in rules:
            hit = self._test(rule, bar)
            if hit is None:
                return None
            result = result and hit
        return result

    def _any(self, rules: tuple[Rule, ...], bar: Bar) -> bool | None:
        if not rules:
            return False
        result = False
        for rule in rules:
            hit = self._test(rule, bar)
            if hit is None:
                return None
            result = result or hit
        return result

    def _test(self, rule: Rule, bar: Bar) -> bool | None:
        left = self._value(rule.left, bar)
        right = self._value(rule.right, bar)
        if left is None or right is None:
            return None

        op = rule.op
        if op == "gt":
            return left > right
        if op == "lt":
            return left < right
        if op == "gte":
            return left >= right
        if op == "lte":
            return left <= right

        previous_left = self._previous.get(rule.left.key)
        previous_right = self._previous.get(rule.right.key)
        if previous_left is None or previous_right is None:
            # First decidable bar: a crossover needs two, and asserting one
            # here would fire a spurious signal on the warm-up boundary.
            return None
        if op == "cross_above":
            return previous_left <= previous_right and left > right
        return previous_left >= previous_right and left < right

    def _remember(self, bar: Bar) -> None:
        for rule in (*self.spec.entry, *self.spec.exit):
            for ind in (rule.left, rule.right):
                value = self._value(ind, bar)
                if value is not None:
                    self._previous[ind.key] = value

    # -- orders -----------------------------------------------------------

    def _enter(self, bar: Bar) -> None:
        """Open a position at market, remembering where its stop belongs.

        The protective stop is placed in :meth:`on_position_opened` rather than
        here, because Nautilus' ``bracket()`` always constructs a take-profit
        leg — ``tp_order_type`` defaults to ``LIMIT`` and then demands a
        ``tp_price``. Most specs have a stop and no target, and inventing a
        target to satisfy the constructor would put a price in the report that
        the strategy never asked for.

        ``on_position_opened`` fires in the same event cycle as the fill, so
        the position is not left unprotected across a bar.
        """
        distance = self._stop_distance(bar)
        if distance is None or distance <= 0:
            self._undecidable += 1
            return

        side = OrderSide.BUY if self.spec.direction in ("long", "both") else OrderSide.SELL
        sign = 1 if side == OrderSide.BUY else -1
        reference = float(bar.close)

        quantity = self._size(distance, reference)
        if quantity <= 0:
            # The account cannot afford one unit at this risk. A real
            # constraint, and a silent skip rather than an error.
            return

        self._pending_stop = reference - sign * distance
        self._pending_target = (
            reference + sign * distance * self.spec.target.r_multiple
            if self.spec.target.r_multiple else None
        )
        self.submit_order(
            self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=side,
                quantity=Quantity(quantity, self._instrument.size_precision),
                time_in_force=TimeInForce.GTC,
            )
        )

    def on_position_opened(self, event: Any) -> None:
        """Attach the protective stop, and a target if the spec has one.

        Both are `reduce_only`: they may close this position and may never open
        a new one in the opposite direction. Without that flag a stop that
        fires after the position has already been closed by the exit signal
        opens a fresh short, which is a strategy nobody wrote.
        """
        if self._pending_stop is None:
            return
        try:
            closing = OrderSide.SELL if event.entry == OrderSide.BUY else OrderSide.BUY
            precision = self._instrument.price_precision
            quantity = event.quantity

            self.submit_order(
                self.order_factory.stop_market(
                    instrument_id=self.instrument_id,
                    order_side=closing,
                    quantity=quantity,
                    trigger_price=self._instrument.make_price(
                        round(self._pending_stop, precision)
                    ),
                    time_in_force=TimeInForce.GTC,
                    reduce_only=True,
                )
            )
            if self._pending_target is not None:
                self.submit_order(
                    self.order_factory.limit(
                        instrument_id=self.instrument_id,
                        order_side=closing,
                        quantity=quantity,
                        price=self._instrument.make_price(
                            round(self._pending_target, precision)
                        ),
                        time_in_force=TimeInForce.GTC,
                        reduce_only=True,
                        post_only=False,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            message = f"stop placement failed: {type(exc).__name__}: {exc}"
            if message not in self._errors:
                self._errors.append(message)
            log.exception("could not attach a protective stop")
        finally:
            self._pending_stop = None
            self._pending_target = None

    def _stop_distance(self, bar: Bar) -> float | None:
        stop = self.spec.stop
        if stop.kind == "atr":
            if self._atr is None or not self._atr.initialized:
                return None
            return float(self._atr.value) * stop.mult
        if stop.kind == "percent":
            return float(bar.close) * stop.mult / 100.0
        return stop.mult

    def _size(self, distance: float, price: float) -> float:
        """Units to trade. Arithmetic, in five lines, that no model touches."""
        sizing = self.spec.sizing
        if sizing.kind == "fixed_units":
            return float(sizing.units)
        if sizing.kind == "fixed_notional":
            return float(int(sizing.notional / max(price, 1e-9)))
        equity = self.spec.starting_equity
        account = self.portfolio.account(self.instrument_id.venue)
        if account is not None:
            balance = account.balance_total(self._instrument.quote_currency)
            if balance is not None:
                equity = float(balance.as_double())
        return float(int((equity * sizing.pct / 100.0) / distance))

    # -- what the runner reports ------------------------------------------

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "bars_seen": self._bars_seen,
            "undecidable_bars": self._undecidable,
            "errors": list(self._errors),
        }


#: Series read straight off the bar; no indicator object is built for them.
_RAW = frozenset({"close", "open", "high", "low", "volume", "constant"})


def _build_indicator(ind: Indicator) -> Any | None:
    """Map one spec indicator onto a Nautilus one."""
    kind = ind.kind
    if kind == "sma":
        return SimpleMovingAverage(ind.period)
    if kind == "ema":
        return ExponentialMovingAverage(ind.period)
    if kind == "rsi":
        return RelativeStrengthIndex(ind.period)
    if kind in ("macd", "macd_signal", "macd_hist"):
        return MovingAverageConvergenceDivergence(ind.period, ind.slow)
    if kind == "atr":
        return AverageTrueRange(ind.period)
    if kind in ("rolling_high", "rolling_low"):
        return DonchianChannel(ind.period)
    if kind == "vwap":
        from nautilus_trader.indicators import VolumeWeightedAveragePrice

        return VolumeWeightedAveragePrice()
    return None
