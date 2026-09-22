# Spec: Genesis Markdown/20-Agents/Research/Research Family.md
"""Wiring: how the research family is built and what the planner is told.

Two concerns, kept apart on purpose -- the same split the charting family uses,
for the same reason.

:func:`build_fleet` constructs the agents. The gateway, the bar source, the
research store and the model backends are all injected, so the same three
agents run against a live gateway in the daemon and against fakes in a test
with no branch between them.

:func:`register` tells the [[Orchestrator]] planner what exists. Orchestrator.md
is strict: *"the orchestrator picks the agent, not the tool"*. One sentence per
agent, task types and argument shapes only, no tool schemas.

**Most of the seven, plus the news collector, and the absences are honest.**
Research Family names seven agents. Sentiment and Regime And Correlation
are not built, so they are not registered -- an entry in the
catalogue for an agent nothing will drain turns "I'll check the news" into a
task that queues forever, which is worse than the planner declining.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from genesis.agents.research.fundamental import FundamentalAgent
from genesis.agents.research.idea_synthesizer import IdeaSynthesizerAgent
from genesis.agents.research.market_analyst import MarketAnalystAgent
from genesis.agents.research.news_catalyst import NewsCatalystAgent
from genesis.agents.research.news_collector import NewsCollectorAgent
from genesis.agents.research.screener import ScreenerAgent
from genesis.agents.research.session_plan import PlanInputs, SessionPlanAgent
from genesis.agents.research.topic_researcher import TopicResearcherAgent
from genesis.observability import Console
from genesis.orchestrator.registry import Capability, CapabilityRegistry
from genesis.research.store import ResearchStore

__all__ = ["CAPABILITIES", "RESEARCH_FLEET", "ResearchFleet", "build_fleet", "register"]

#: What the planner is allowed to know. One line each, no tools, no schemas.
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        agent="topic-researcher",
        family="research",
        summary=(
            "Researches any subject on the web and saves a cited note — or "
            "summarises the notes already stored on it, without searching."
        ),
        # One agent, two jobs, and the registry keys capabilities by agent --
        # a second Capability row for the same agent would silently replace
        # this one rather than sit beside it.
        task_types=("research.topic", "research.summarise"),
        args_hint=(
            "subject (required — a topic, not a ticker: 'W.D. Gann', 'gamma "
            "squeezes'), depth (quick|deep, default deep), tags. Use "
            "research.summarise when the question is about what Genesis "
            "already found — 'summarise my notes on X', 'what did we conclude "
            "about X' — and research.topic to go and look."
        ),
    ),
    Capability(
        agent="fundamental",
        family="research",
        summary=(
            "Analyses one company as an investment — fair value, value checklist, "
            "earnings record, business judgement — and saves it as a note."
        ),
        task_types=("research.company",),
        args_hint="symbol (required — a ticker or an S&P 500 company name)",
    ),
    Capability(
        agent="screener",
        family="research",
        summary=(
            "Rebuilds the S&P 500 fundamentals snapshot the screener filters. "
            "Screening itself is answered directly in the conversation, not planned."
        ),
        task_types=("screen.refresh",),
        args_hint="no arguments",
    ),
    Capability(
        agent="market-analyst",
        family="research",
        summary=(
            "The top-down read: regime, trend, breadth, volatility and which "
            "sectors lead. Measured from bars, not narrated."
        ),
        task_types=("research.regime",),
        args_hint="no arguments — reads the whole tape",
    ),
    Capability(
        agent="idea-synthesizer",
        family="research",
        summary=(
            "Fuses the research already gathered into ranked trade ideas, each "
            "with an invalidation. Returns nothing when evidence is thin."
        ),
        task_types=("research.ideas",),
        args_hint="symbols (optional), max_ideas (default 3)",
    ),
    Capability(
        agent="news-catalyst",
        family="research",
        summary=(
            "Reads the collected news, picks the stories that matter, reads "
            "them and writes a brief with insights and trade ideas."
        ),
        task_types=("news.brief",),
        args_hint=(
            "hours (default 24; ~64 for 'over the weekend'), symbols (optional), "
            "focus (optional text), max_articles (default 8), refresh (true to "
            "collect fresh headlines first)"
        ),
    ),
    Capability(
        agent="session-plan",
        family="research",
        summary=(
            "Records the trader's own trade ideas, and turns the ideas on the "
            "desk into a plan of action: ranked, sized by the risk gate, saved "
            "as a brief."
        ),
        task_types=("idea.record", "plan.build"),
        args_hint=(
            "idea.record: symbol, direction (long|short), thesis (the trader's "
            "words), entry_zone [low, high], stop_price (where it's wrong, as a "
            "number), targets [..], setup, timeframe (scalp|intraday|swing|"
            "position), horizon_days, confidence 0-1 — use ONLY numbers the "
            "trader said; never supply a price they did not state. "
            "plan.build: no arguments ('what should I do', 'make me a plan', "
            "'plan my session'); save=false to not write the brief."
        ),
    ),
)

RESEARCH_FLEET = tuple(capability.agent for capability in CAPABILITIES)


@dataclass
class ResearchFleet:
    """The research agents, plus the directory they write to."""

    topic_researcher: TopicResearcherAgent | None
    market_analyst: MarketAnalystAgent | None
    idea_synthesizer: IdeaSynthesizerAgent
    store: ResearchStore
    #: Needs nothing but yfinance, so it is always built.
    news_collector: NewsCollectorAgent | None = None
    #: Needs a model; without one it would fail every task, so it is absent.
    news_catalyst: NewsCatalystAgent | None = None
    #: Needs nothing but yfinance and SSGA, so it is always built.
    screener: ScreenerAgent | None = None
    #: Always built: without a model it still writes the computed fact sheet.
    fundamental: FundamentalAgent | None = None
    #: Built when the caller supplies plan inputs. Needs no model.
    session_plan: SessionPlanAgent | None = None

    def all(self) -> tuple[Any, ...]:
        """Only the agents that could actually be built.

        The topic researcher needs a gateway and the market analyst needs bars.
        Registering one without its input would give the daemon an agent that
        fails every task it is handed, which reads as a broken system rather
        than an unconfigured one.
        """
        return tuple(
            a for a in (
                self.topic_researcher, self.market_analyst, self.idea_synthesizer,
                self.news_collector, self.news_catalyst, self.screener, self.fundamental,
                self.session_plan,
            ) if a is not None
        )


def register(registry: CapabilityRegistry, *, fleet: ResearchFleet | None = None) -> CapabilityRegistry:
    """Add the research family to the planner's catalogue.

    With a ``fleet``, only the agents in it are registered -- so a Genesis with
    no market data does not advertise a regime read it cannot perform.
    """
    live = {a.id for a in fleet.all()} if fleet is not None else None
    for capability in CAPABILITIES:
        if live is None or capability.agent in live:
            registry.register(capability)
    return registry


def build_fleet(
    *,
    gateway: Any = None,
    source: Any = None,
    store: ResearchStore | None = None,
    journal: Any = None,
    backend: Any = None,
    planner_backend: Any = None,
    vault: str | None = "~/GenesisVault",
    db_path: str = "~/.genesis/memory/research.db",
    plan_inputs: PlanInputs | None = None,
    console: Console | None = None,
) -> ResearchFleet:
    """Construct the research family from what is actually available.

    Nothing here raises on a missing input. A Genesis with no gateway still
    gets a research directory and an idea synthesizer; it just cannot search
    the web, and :meth:`ResearchFleet.all` reflects that rather than hiding it.
    """
    console = console or Console(enabled=False)
    store = store or ResearchStore(path=db_path, vault=vault)

    # Built with or without a gateway. Only `research.topic` needs the web;
    # `research.summarise` reads the directory, and withholding the agent
    # entirely would take the offline half down with the online half.
    topic = TopicResearcherAgent(
        gateway, store, backend=backend, planner_backend=planner_backend,
        console=console,
    )
    if gateway is None:
        console.warn(
            "No MCP gateway — the topic researcher can summarise stored notes "
            "but cannot search the web."
        )

    analyst = None
    if source is not None:
        analyst = MarketAnalystAgent(source, store, backend=backend, console=console)
    else:
        console.warn("No bar source — the market analyst is not registered.")

    from pathlib import Path

    from genesis.news.store import NewsStore

    news = NewsStore(Path(db_path).expanduser().parent / "news.db")
    return ResearchFleet(
        news_collector=NewsCollectorAgent(news),
        screener=ScreenerAgent(),
        fundamental=FundamentalAgent(store, backend=backend),
        news_catalyst=(NewsCatalystAgent(news, backend=backend, select_backend=planner_backend)
                       if backend is not None else None),
        topic_researcher=topic,
        market_analyst=analyst,
        idea_synthesizer=IdeaSynthesizerAgent(
            store, backend=backend, journal=journal, console=console
        ),
        session_plan=(SessionPlanAgent(store, inputs=plan_inputs)
                      if plan_inputs is not None else None),
        store=store,
    )
