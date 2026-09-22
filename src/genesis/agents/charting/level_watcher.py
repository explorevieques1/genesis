# Spec: Genesis Markdown/20-Agents/Charting/Agent — Level Watcher.md
"""Agent — Level Watcher. Spinal cord, not cortex.

``tier: none``, and that is a design decision with a reason, not a stage this
agent grows out of. Biological Design:

> A limit check, a retry decision, a kill switch are *spinal* — deterministic
> code, sub-millisecond, incapable of hallucinating. ``tier: none`` components
> are not "agents without a model yet"; they are spinal cord, and giving one a
> model is the bug.

This is what turns static analysis into a live system: you marked a level three
days ago and Genesis tells you the instant it matters. It must therefore run
when every LLM backend is down, which it does, because there is no model
anywhere in this file.

**The one distinction that decides whether the system is useful.** A wick
through a level is not a break; a close beyond it is. Conflating them produces
constant false alerts, and an alerting system that cries wolf gets muted, and a
muted alerting system is worth nothing. So ``touch`` and ``break`` are separate
watch types with separate conditions, and ``reclaim`` exists because a level
lost and taken back is information of the opposite sign.

**Noise control is the rest of the design**, and it is all here: an ATR-relative
tolerance (10c means different things on a $5 and a $500 stock), a per-level
cooldown, debounce across an oscillation, expiry by the spec's own timeframe,
and an hourly cap on spoken alerts above which everything degrades to the
dashboard and the orchestrator says *"several levels hit, check the board."*
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Iterable, Literal

from genesis.agents.base import Agent, AgentDeclaration, TaskFailure, TaskResult
from genesis.charting import indicators as ind
from genesis.charting.source import BarSource
from genesis.charting.spec import Level, MarkupSpec, TradePlan, Zone
from genesis.charting.store import SpecStore
from genesis.errors import DegradedError
from genesis.observability import Console

__all__ = ["DECLARATION", "Fire", "LevelWatcherAgent", "Watch"]

WatchType = Literal["touch", "approach", "break", "reclaim", "zone_entry", "invalidation"]

#: Tolerance for "price is at the level", in ATR. Small, because a touch should
#: mean a touch.
TOUCH_ATR = 0.08

#: The early warning band. Dashboard only -- never spoken, or the voice becomes
#: a running commentary on price drifting around.
APPROACH_ATR = 0.6

#: Bars of silence after a level fires. Debounce and cooldown in one number:
#: price oscillating across a level fires once per cooldown, not per tick.
COOLDOWN_BARS = 5

#: Spoken alerts per hour before everything degrades to dashboard-only. The
#: note's rate cap, and the number below which a person still listens.
VOICE_CAP_PER_HOUR = 6

#: Priority by watch type. ``invalidation`` on an open position is the one that
#: interrupts, and it is highest by construction rather than by a runtime rule
#: that could be reordered.
_PRIORITY: dict[str, str] = {
    "invalidation": "critical",
    "break": "high",
    "touch": "high",
    "reclaim": "high",
    "zone_entry": "normal",
    "approach": "low",
}

DECLARATION = AgentDeclaration(
    id="level-watcher",
    name="Level Watcher",
    family="charting",
    cadence=[
        # A one-minute poll during the session. Market Data Plane's posture is
        # batch-first, and streaming is the upgrade path -- so the poll is the
        # shipped behaviour, not a placeholder.
        {"type": "market-open", "interval_sec": 60},
        {"type": "event", "on": ["markup.created", "idea.ranked", "position.opened"]},
    ],
    tools=["market-data.ohlcv", "market-data.quote"],
    memory={
        "read": ["shared", "chart-markup", "idea-synthesizer", "ledger"],
        "write": ["level-watcher"],
    },
    # No LLM. The whole point.
    model_tier="none",
    vision=False,
    timeout_sec=30,
    max_concurrent=1,
)


@dataclass(frozen=True)
class Watch:
    """One thing being watched, flattened out of a spec."""

    spec_id: str
    symbol: str
    timeframe: str
    label: str
    kind: str  # level | zone | trade_plan
    price: float
    low: float
    high: float
    level_type: str = ""
    why: str = ""
    #: A trade plan's stop is an invalidation, which outranks everything.
    invalidation: bool = False

    @property
    def key(self) -> str:
        return f"{self.symbol}:{self.timeframe}:{self.label}:{self.price:.4f}"


@dataclass(frozen=True)
class Fire:
    """One event, in the note's ``level.touched`` shape."""

    event: str
    symbol: str
    price: float
    watch: Watch
    watch_type: WatchType
    priority: str
    spoken: bool
    at: datetime
    context: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "symbol": self.symbol,
            "price": round(self.price, 4),
            "level": {
                "price": round(self.watch.price, 4),
                "label": self.watch.label,
                "type": self.watch.level_type or self.watch.kind,
                "spec": self.watch.spec_id,
            },
            "watch_type": self.watch_type,
            "context": self.context,
            "priority": self.priority,
            "spoken": self.spoken,
            "at": self.at.isoformat(),
        }

    def spoken_summary(self) -> str:
        verb = {
            "touch": "is testing",
            "break": "closed through",
            "reclaim": "reclaimed",
            "zone_entry": "entered",
            "invalidation": "hit the invalidation at",
            "approach": "is approaching",
        }[self.watch_type]
        return (
            f"{self.symbol} {verb} {self.watch.label} "
            f"{self.watch.price:,.2f}. Last {self.price:,.2f}."
        )


class LevelWatcherAgent(Agent):
    """Watches every level in every active spec. Deterministic, always awake."""

    def __init__(
        self,
        source: BarSource,
        store: SpecStore,
        *,
        publish: Any = None,
        journal: Any = None,
        console: Console | None = None,
        voice_cap_per_hour: int = VOICE_CAP_PER_HOUR,
        clock: Any = None,
    ) -> None:
        super().__init__(DECLARATION)
        self.source = source
        self.store = store
        self.publish = publish
        #: Optional journal store. Every fire recorded here is one row the
        #: Insight Miner can later aggregate into "which of my levels hold" --
        #: the family's stated distinctive edge, and the reason this is wired
        #: before any trade exists.
        self.journal = journal
        self.console = console or Console(enabled=False)
        self.voice_cap_per_hour = voice_cap_per_hour
        self._clock = clock or (lambda: datetime.now(UTC))
        #: key -> bar index at last fire, for cooldown and debounce.
        self._last_fire: dict[str, int] = {}
        #: Which side of each level price was on last, so a reclaim is
        #: detectable at all -- it is defined by a transition, not a position.
        self._side: dict[str, str] = {}
        self._spoken_at: list[float] = []

    # -- the contract ------------------------------------------------------

    def execute(self, task: Any) -> TaskResult | TaskFailure:
        fires = self.poll()
        spoken = [fire for fire in fires if fire.spoken]
        return TaskResult(
            task_id=getattr(task, "id", "<none>"),
            agent=self.id,
            data={
                "fires": [fire.to_event() for fire in fires],
                "watched": len(self.watches()),
            },
            wrote=tuple(
                {"layer": "knowledge-graph", "entity": f"level:{f.symbol}:{f.watch.price:.2f}"}
                for f in fires
            ),
            spoken_summary=self._speak(fires, spoken),
            cost={"tool_calls": len({f.symbol for f in fires}) or 0},
        )

    def health(self):
        """Cheap and model-free, as the contract requires.

        Notable only because it is the same in this agent as in every other one:
        this agent has no degraded mode that depends on a backend, so its health
        never reflects one.
        """
        return super().health()

    # -- the watch list ----------------------------------------------------

    def watches(self, now: datetime | None = None) -> list[Watch]:
        """Flatten every active spec into things to watch.

        Rebuilt from the store on every call rather than held in memory. The
        note requires the list be rebuilt whenever a spec is created or expires,
        and a query that is always correct beats a subscription that is usually
        correct -- especially for a component whose job is to still work after
        everything else has restarted.
        """
        out: list[Watch] = []
        for spec in self.store.active(now or self._clock()):
            out.extend(_flatten(spec))
        return out

    # -- the loop ----------------------------------------------------------

    def poll(self, now: datetime | None = None) -> list[Fire]:
        """One pass over every watched symbol. Never raises.

        A symbol whose data is unavailable is skipped and logged, not fatal:
        this loop must keep running for the other twenty symbols, and a watcher
        that dies because one feed hiccupped is a watcher that misses the level
        it existed for.
        """
        stamp = now or self._clock()
        watches = self.watches(stamp)
        by_symbol: dict[tuple[str, str], list[Watch]] = {}
        for watch in watches:
            by_symbol.setdefault((watch.symbol, watch.timeframe), []).append(watch)

        fires: list[Fire] = []
        for (symbol, timeframe), group in by_symbol.items():
            try:
                bars = self.source.fetch(symbol, timeframe)
            except DegradedError as exc:
                self.console.warn(f"level-watcher skipped {symbol}: {exc.reason}")
                continue
            fires.extend(self._check(group, bars, stamp))

        for fire in fires:
            if self.publish is not None:
                self.publish(fire.event, fire.to_event())
            if self.journal is not None:
                try:
                    from genesis.journal.bridge import record_level_fire

                    record_level_fire(self.journal, fire)
                except Exception as exc:  # noqa: BLE001 - never lose an alert to a write
                    self.console.warn(f"level-watcher could not record the fire: {exc}")
        return fires

    def _check(self, watches: list[Watch], bars, stamp: datetime) -> list[Fire]:
        atr = ind.last_atr(bars) or (bars.last * 0.01)
        last = bars.last
        index = len(bars) - 1
        fires: list[Fire] = []

        for watch in watches:
            watch_type = self._classify(watch, bars, atr, last, index)
            if watch_type is None:
                continue
            if not self._cooled(watch.key, index, watch_type):
                continue
            self._last_fire[watch.key] = index

            priority = "critical" if watch.invalidation else _PRIORITY[watch_type]
            spoken = self._may_speak(watch_type, priority, stamp)
            fires.append(
                Fire(
                    event=_EVENT_NAMES[watch_type],
                    symbol=watch.symbol,
                    price=last,
                    watch=watch,
                    watch_type=watch_type,
                    priority=priority,
                    spoken=spoken,
                    at=stamp,
                    context={
                        "spec": watch.spec_id,
                        "timeframe": watch.timeframe,
                        "why": watch.why,
                        "rel_volume": _relative_volume(bars),
                        "atr": round(atr, 4),
                    },
                )
            )
        return fires

    def _classify(self, watch: Watch, bars, atr: float, last: float, index: int) -> WatchType | None:
        """Which watch type, if any, fired on this bar.

        Order matters and is by severity: an invalidation is not also reported
        as a break, and a break is not also reported as a touch. Reporting one
        price event three ways is the same noise problem in a different costume.
        """
        band = atr * TOUCH_ATR
        previous_side = self._side.get(watch.key)
        side = "above" if last > watch.price else "below"
        self._side[watch.key] = side

        if watch.kind == "zone":
            if watch.low - band <= last <= watch.high + band:
                return "zone_entry"
            return None

        closed_beyond = (
            last > watch.price + band
            if watch.level_type in ("resistance", "ma", "pivot", "vwap", "poc", "value_area")
            else last < watch.price - band
        )

        if watch.invalidation:
            # A trade plan's stop. Direction is baked into the watch when it is
            # flattened, so this is a single comparison rather than a guess
            # about which side counts as wrong.
            if (watch.level_type == "stop_long" and last <= watch.price) or (
                watch.level_type == "stop_short" and last >= watch.price
            ):
                return "invalidation"
            return None

        # A reclaim: it was beyond, and this close is back on the original side.
        if previous_side is not None and previous_side != side and not closed_beyond:
            if self._last_fire.get(watch.key) is not None:
                return "reclaim"

        if closed_beyond:
            return "break"
        if abs(last - watch.price) <= band:
            return "touch"
        if abs(last - watch.price) <= atr * APPROACH_ATR:
            return "approach"
        return None

    def _cooled(self, key: str, index: int, watch_type: WatchType) -> bool:
        """Cooldown and debounce. An invalidation is never suppressed.

        Suppressing an invalidation to keep the alert rate down would be the
        noise control eating the one alert it exists to protect.
        """
        if watch_type == "invalidation":
            return True
        last = self._last_fire.get(key)
        return last is None or (index - last) >= COOLDOWN_BARS

    def _may_speak(self, watch_type: WatchType, priority: str, stamp: datetime) -> bool:
        """The rate cap. Critical always speaks; approach never does."""
        if priority == "critical":
            return True
        if watch_type == "approach":
            return False
        cutoff = stamp.timestamp() - 3600
        self._spoken_at = [t for t in self._spoken_at if t > cutoff]
        if len(self._spoken_at) >= self.voice_cap_per_hour:
            return False
        self._spoken_at.append(stamp.timestamp())
        return True

    def _speak(self, fires: list[Fire], spoken: list[Fire]) -> str | None:
        """What the orchestrator may read aloud, if anything.

        ``None`` on a quiet pass is deliberate: this agent runs every minute for
        hours, and a summary on every pass would be a voice reading out that
        nothing happened, sixty times an hour.
        """
        if not spoken:
            if len(fires) > self.voice_cap_per_hour:
                return "Several levels hit — check the board."
            return None
        if len(spoken) == 1:
            return spoken[0].spoken_summary()
        first = spoken[0].spoken_summary()
        return f"{first} And {len(spoken) - 1} more."


_EVENT_NAMES: dict[str, str] = {
    "touch": "level.touched",
    "approach": "level.approached",
    "break": "level.broken",
    "reclaim": "level.reclaimed",
    "zone_entry": "zone.entered",
    "invalidation": "idea.invalidated",
}


def _flatten(spec: MarkupSpec) -> Iterable[Watch]:
    """A spec's watchable annotations as flat watches.

    Levels, zones and trade plans -- exactly what Markup Spec Schema lists as
    the Level Watcher's subscription. A trade plan contributes its stop as an
    *invalidation* watch, which is why the stop's direction is carried in
    ``level_type``: the watcher must not have to infer which side is wrong.
    """
    for annotation in spec.watchable():
        if isinstance(annotation, Level):
            yield Watch(
                spec_id=spec.id, symbol=spec.symbol, timeframe=spec.timeframe,
                label=annotation.label, kind="level", price=annotation.price,
                low=annotation.price, high=annotation.price,
                level_type=annotation.type, why=annotation.why,
            )
        elif isinstance(annotation, Zone):
            yield Watch(
                spec_id=spec.id, symbol=spec.symbol, timeframe=spec.timeframe,
                label=annotation.label, kind="zone",
                price=annotation.midpoint,
                low=annotation.from_price, high=annotation.to_price,
                level_type=annotation.subtype, why=annotation.why,
            )
        elif isinstance(annotation, TradePlan):
            yield Watch(
                spec_id=spec.id, symbol=spec.symbol, timeframe=spec.timeframe,
                label=f"{annotation.label} stop", kind="trade_plan",
                price=annotation.stop, low=annotation.stop, high=annotation.stop,
                level_type="stop_long" if annotation.side == "long" else "stop_short",
                why=annotation.why, invalidation=True,
            )


def _relative_volume(bars) -> float | None:
    """Last bar's volume against its 20-bar average. Context for a fire.

    A touch on twice the average volume is a different event from a touch on
    half of it, and it costs one division to say so.
    """
    if len(bars) < 21 or float(bars.volume[-21:-1].mean()) <= 0:
        return None
    return round(float(bars.volume[-1] / bars.volume[-21:-1].mean()), 2)
