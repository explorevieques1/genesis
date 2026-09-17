# Spec: Genesis Markdown/20-Agents/Journal/Journal Family.md
"""Wiring for the Journal Family: construction, and what the planner is told.

Same split as the charting family's, and for the same reasons.
:func:`build_fleet` constructs the agents with everything injected;
:func:`register` gives the [[Orchestrator]] planner one line each and no tool
schemas.

One family-specific note on what is registered. **The Trade Journal and the
Drift agent are deliberately absent from the planner catalogue.** Neither is
something a person asks for by voice: the journal writes itself on a fill event,
and drift runs nightly per strategy. Putting them in the catalogue would invite
the planner to dispatch ``journal.record`` with no trade, which fails honestly
but wastes a turn -- and a catalogue is a menu, so everything on it should be
orderable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from genesis.agents.journal.digest import DigestAgent
from genesis.agents.journal.drift import DriftAgent
from genesis.agents.journal.insight_miner import InsightMinerAgent
from genesis.agents.journal.performance_analyst import PerformanceAnalystAgent
from genesis.agents.journal.trade_journal import TradeJournalAgent
from genesis.agents.journal.watchdog import WatchdogAgent
from genesis.journal.drift import Expectation
from genesis.journal.store import JournalStore
from genesis.observability import Console
from genesis.orchestrator.registry import Capability, CapabilityRegistry

__all__ = ["CAPABILITIES", "JOURNAL_FLEET", "JournalFleet", "build_fleet", "register"]

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        agent="performance-analyst",
        family="journal",
        summary="Where the edge is and is not: performance sliced by setup, session, size and adherence.",
        task_types=("perf.review",),
        args_hint="days (default 7); speak=false for numbers only",
    ),
    Capability(
        agent="insight-miner",
        family="journal",
        summary="Behavioural patterns in your own trading, written as lessons once the evidence supports them.",
        task_types=("insight.mine",),
        args_hint="days (default 180)",
    ),
    Capability(
        agent="watchdog",
        family="journal",
        summary="Is everything running? Agents, tool servers, feeds and queues, with freshness checked.",
        task_types=("health.check",),
        args_hint="no arguments",
    ),
    Capability(
        agent="digest",
        family="journal",
        summary="The morning brief, the evening recap, and the nightly memory compression.",
        task_types=("digest.brief",),
        args_hint="kind: morning | evening | compress",
    ),
)

JOURNAL_FLEET = tuple(capability.agent for capability in CAPABILITIES)


@dataclass
class JournalFleet:
    trade_journal: TradeJournalAgent
    performance_analyst: PerformanceAnalystAgent
    insight_miner: InsightMinerAgent
    drift: DriftAgent
    watchdog: WatchdogAgent
    digest: DigestAgent
    store: JournalStore

    def all(self) -> tuple[Any, ...]:
        return (
            self.trade_journal,
            self.performance_analyst,
            self.insight_miner,
            self.drift,
            self.watchdog,
            self.digest,
        )


def register(registry: CapabilityRegistry) -> CapabilityRegistry:
    for capability in CAPABILITIES:
        registry.register(capability)
    return registry


def build_fleet(
    *,
    store: JournalStore | None = None,
    db_path: str = "~/.genesis/memory/journal.db",
    backend: Any = None,
    small_backend: Any = None,
    ledger: Any = None,
    specs: Any = None,
    episodic: Any = None,
    vault: Any = None,
    supervisor: Any = None,
    gateway: Any = None,
    bus: Any = None,
    expectations: Mapping[str, Expectation] | None = None,
    research: Any = None,
    news: Any = None,
    consolidator: Any = None,
    console: Console | None = None,
) -> JournalFleet:
    """Construct the family. Everything optional degrades honestly.

    With no ``backend`` the analyst and the miner report their computed numbers
    and skip the prose -- which is the half that was never load-bearing. With no
    ``ledger`` the journal still records whatever it is handed. With no
    ``expectations`` the drift agent reports which strategies it cannot measure
    instead of inventing a baseline.
    """
    # Not `store or JournalStore(...)`: JournalStore defines __len__, so an
    # empty store is falsy and `or` would silently swap a caller's database for
    # the default one in ~/.genesis.
    store = store if store is not None else JournalStore(db_path)
    small = small_backend if small_backend is not None else backend

    fleet = JournalFleet(
        trade_journal=TradeJournalAgent(
            store, ledger=ledger, specs=specs, vault=vault, console=console
        ),
        performance_analyst=PerformanceAnalystAgent(
            store, backend=backend, console=console
        ),
        insight_miner=InsightMinerAgent(store, backend=backend, console=console),
        drift=DriftAgent(store, expectations=expectations, console=console),
        watchdog=WatchdogAgent(
            store=store, supervisor=supervisor, gateway=gateway, bus=bus, console=console
        ),
        digest=DigestAgent(
            store, episodic=episodic, backend=small, research=research, news=news,
            consolidator=consolidator, console=console,
        ),
        store=store,
    )
    # The consolidator's pass 6 is the digest's own classification, so the two
    # point at each other. Closed here rather than in either constructor: a
    # cycle built inside one of them is a cycle nobody can see from outside.
    if consolidator is not None and getattr(consolidator, "digest", None) is None:
        consolidator.digest = fleet.digest
    return fleet
