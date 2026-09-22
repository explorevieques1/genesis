# Spec: Genesis Markdown/20-Agents/Charting/Charting Family.md
"""Wiring: how the charting family is constructed and what the planner is told.

Two concerns, kept apart on purpose.

:func:`build_fleet` constructs the agents. Everything they need -- a bar source,
a spec store, model backends -- is injected, so the same five agents run against
a live gateway in the daemon and against static frames in a test with no branch
between the two.

:func:`register` tells the [[Orchestrator]] planner what exists. Orchestrator.md
is strict about what may go in that catalogue: *"the orchestrator picks the
agent, not the tool"*, one short line per agent, no tool schemas. So the entries
below are one sentence each and name **task types and argument shapes only**.

The task type names are the contract between a planned task and
:meth:`Agent.execute`, so they are declared once, here, rather than spelled out
in the planner prompt and again in each agent -- which is how a plan comes to
dispatch ``chart.mark`` at an agent that handles ``chart.markup``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from genesis.agents.charting.chart_markup import ChartMarkupAgent
from genesis.agents.charting.data_viz import DataVizAgent, MacroSource
from genesis.agents.charting.level_watcher import LevelWatcherAgent
from genesis.agents.charting.multi_timeframe import MultiTimeframeAgent
from genesis.agents.charting.pattern_recognition import PatternRecognitionAgent
from genesis.charting.source import BarSource, GatewayBarSource
from genesis.charting.store import SpecStore
from genesis.observability import Console
from genesis.orchestrator.registry import Capability, CapabilityRegistry

__all__ = ["CAPABILITIES", "CHARTING_FLEET", "build_fleet", "register"]

#: What the planner is allowed to know. One line each, no tools, no schemas.
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        agent="chart-markup",
        family="charting",
        summary="Marks up a price chart: computes the levels that matter, renders it, explains each one.",
        task_types=("chart.markup",),
        args_hint='symbol (required), timeframe (1m..1M, default 1D), lookback_bars',
    ),
    Capability(
        agent="pattern-recognition",
        family="charting",
        summary="Names a chart's structure from a marked-up spec. Vision cross-checked against a rule engine.",
        task_types=("chart.pattern",),
        args_hint="spec_id (required — from a chart.markup result)",
    ),
    Capability(
        agent="multi-timeframe",
        family="charting",
        summary="Checks whether timeframes agree on a symbol, and what higher-timeframe level is in the way.",
        task_types=("chart.align",),
        args_hint="symbol (required), direction (long|short|none), timeframes",
    ),
    Capability(
        agent="level-watcher",
        family="charting",
        summary="Reports which marked levels price is at right now. Deterministic, no model.",
        task_types=("level.poll",),
        args_hint="no arguments — polls every active markup spec",
    ),
    Capability(
        agent="data-viz",
        family="charting",
        summary="Non-price charts: sector rankings, macro series, symbol comparisons, correlation matrices.",
        task_types=("viz.render",),
        args_hint=(
            "recipe: sector_performance | macro_series | compare | correlation; "
            "days, years, symbols, series; interpret=true for a theory"
        ),
    ),
)

CHARTING_FLEET = tuple(capability.agent for capability in CAPABILITIES)


@dataclass
class ChartingFleet:
    """The five agents, plus the store they share."""

    chart_markup: ChartMarkupAgent
    pattern_recognition: PatternRecognitionAgent
    multi_timeframe: MultiTimeframeAgent
    level_watcher: LevelWatcherAgent
    data_viz: DataVizAgent
    store: SpecStore

    def all(self) -> tuple[Any, ...]:
        return (
            self.chart_markup,
            self.pattern_recognition,
            self.multi_timeframe,
            self.level_watcher,
            self.data_viz,
        )


def register(registry: CapabilityRegistry) -> CapabilityRegistry:
    """Add the charting family to the planner's catalogue."""
    for capability in CAPABILITIES:
        registry.register(capability)
    return registry


def build_fleet(
    *,
    gateway: Any = None,
    source: BarSource | None = None,
    store: SpecStore | None = None,
    macro: Any = None,
    backend: Any = None,
    vision_backend: Any = None,
    chart_dir: str = "~/.genesis/vault/20-Charts",
    db_path: str = "~/.genesis/memory/charting.db",
    publish: Any = None,
    journal: Any = None,
    console: Console | None = None,
) -> ChartingFleet:
    """Construct the family.

    ``gateway`` is the ordinary path: each agent gets a bar source bound to
    **its own id**, so the per-agent allow-list is checked against the agent
    that is actually asking rather than against a shared charting identity. That
    distinction is the entire value of a per-agent allow-list, and sharing one
    source object would quietly discard it.

    Everything else is optional and degrades honestly. With no ``backend`` the
    markup is deterministic; with no ``vision_backend`` pattern recognition runs
    rules-only; with no ``macro`` the macro recipes refuse rather than invent.
    """
    if source is None and gateway is None:
        raise ValueError("build_fleet needs either a gateway or a bar source")

    # Not `store or ...`: SpecStore defines __len__, so an empty store is falsy
    # and `or` would quietly discard a caller's database for the default one.
    store = store if store is not None else SpecStore(db_path)

    def _source(agent_id: str) -> BarSource:
        if source is not None:
            return source
        return GatewayBarSource(gateway, agent=agent_id)

    if macro is None and gateway is not None:
        macro = MacroSource(gateway)

    return ChartingFleet(
        chart_markup=ChartMarkupAgent(
            _source("chart-markup"), store, backend=backend,
            chart_dir=chart_dir, console=console,
        ),
        pattern_recognition=PatternRecognitionAgent(
            _source("pattern-recognition"), store,
            backend=vision_backend or backend, console=console,
        ),
        multi_timeframe=MultiTimeframeAgent(
            _source("multi-timeframe"), store,
            backend=vision_backend or backend, chart_dir=chart_dir, console=console,
        ),
        level_watcher=LevelWatcherAgent(
            _source("level-watcher"), store, publish=publish, journal=journal,
            console=console,
        ),
        data_viz=DataVizAgent(
            _source("data-viz"), macro=macro, backend=backend,
            chart_dir=chart_dir, console=console,
        ),
        store=store,
    )
