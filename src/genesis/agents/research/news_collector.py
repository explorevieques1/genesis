# Spec: Genesis Markdown/20-Agents/Research/Agent — News Collector.md
"""The afferent nerve for news. Tier none: gathers, stores, logs. Never reads meaning."""

from __future__ import annotations

from typing import Any, Callable

from genesis.agents.base import Agent, AgentDeclaration, TaskResult
from genesis.news.collect import collect
from genesis.news.store import NewsStore

__all__ = ["DECLARATION", "NewsCollectorAgent"]

DECLARATION = AgentDeclaration(
    id="news-collector",
    name="News Collector",
    family="research",
    # Tighter while the market is open; hourly otherwise so a Sunday-evening
    # brief has the weekend's stories without anyone pressing refresh.
    cadence=[
        {"type": "market-open", "interval_sec": 900},
        {"type": "market-closed", "interval_sec": 3600},
        {"type": "on-demand"},
    ],
    # No gateway tools: yfinance is called directly, like the company profile
    # provider does. Nothing here can reach a model or a broker.
    tools=[],
    memory={"read": ["shared"], "write": ["news-collector"]},
    model_tier="none",
    timeout_sec=120,
    max_concurrent=1,
)


class NewsCollectorAgent(Agent):
    def __init__(self, store: NewsStore, *, collect_fn: Callable[..., dict[str, Any]] = collect) -> None:
        super().__init__(DECLARATION)
        self.store = store
        self._collect = collect_fn

    def execute(self, task: Any) -> TaskResult:
        args = dict(getattr(task, "args", {}) or {})
        symbols = args.get("symbols") or None
        queries = args.get("queries") or None
        if isinstance(symbols, str):
            symbols = [s for s in symbols.replace(";", ",").split(",") if s.strip()]
        if isinstance(queries, str):
            queries = [q for q in queries.split(",") if q.strip()]
        # A failed run is degraded on the result and in the store's log, not a
        # sticky agent state: one bad hour of yfinance is not a down organ.
        run = self._collect(self.store, symbols, queries)
        return TaskResult(
            task_id=getattr(task, "id", "<none>"),
            agent=self.id,
            data=run,
            wrote=({"layer": "store", "path": "news.db", "new": run["new"]},),
            degraded=not run["ok"],
        )
