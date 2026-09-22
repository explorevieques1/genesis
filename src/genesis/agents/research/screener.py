# Spec: Genesis Markdown/20-Agents/Research/Agent — Screener.md
"""The screener's afferent half: keep the S&P 500 fundamentals snapshot fresh.

Tier none. Interpreting a request is the small tier's job and happens in the
conversation (:mod:`genesis.screener.chat`), not on the bus -- this agent only
fetches, and a fetch has no judgement in it.
"""

from __future__ import annotations

from typing import Any, Callable

from genesis.agents.base import Agent, AgentDeclaration, TaskResult
from genesis.screener.snapshot import build_snapshot

__all__ = ["DECLARATION", "ScreenerAgent"]

DECLARATION = AgentDeclaration(
    id="screener",
    name="Screener",
    family="research",
    # Fundamentals do not move intraday; once per closed session is plenty.
    cadence=[{"type": "market-closed", "interval_sec": 86400}, {"type": "on-demand"}],
    tools=[],
    memory={"read": ["shared"], "write": ["screener"]},
    model_tier="none",
    timeout_sec=600,
    max_concurrent=1,
)


class ScreenerAgent(Agent):
    def __init__(self, *, build: Callable[[], dict[str, Any]] = build_snapshot) -> None:
        super().__init__(DECLARATION)
        self._build = build

    def execute(self, task: Any) -> TaskResult:
        report = self._build()
        return TaskResult(
            task_id=getattr(task, "id", "<none>"),
            agent=self.id,
            data=report,
            wrote=({"layer": "store", "path": "screener.db", "rows": report["fetched"]},) if report["ok"] else (),
            spoken_summary=f"Screener snapshot: {report['fetched']} of {report['members']} companies.",
            degraded=not report["ok"],
        )
