# Spec: Genesis Markdown/10-Architecture/Agent Contract.md
"""Test-only building blocks.

The echo agent lives here rather than in ``src/`` deliberately: Build Order's
Phase 1 exit criterion calls for a *no-op* agent that exercises the spine, not a
shipped component. Nothing in the fleet can import it.

Imported as ``from helpers import ...`` -- ``tests`` is on the pytest pythonpath,
the same arrangement ``evals/`` uses.
"""

from __future__ import annotations

from typing import Any

from genesis.agents import Agent, AgentDeclaration, TaskResult

__all__ = ["EchoAgent", "echo_declaration"]


def echo_declaration(**overrides: Any) -> AgentDeclaration:
    base: dict[str, Any] = {
        "id": "echo",
        "name": "Echo",
        "family": "core",
        "cadence": [{"type": "market-open", "interval_sec": 60}],
        "tools": (),
        "memory": {"read": ["shared"], "write": ["echo"]},
        "model_tier": "none",
        "timeout_sec": 5,
    }
    base.update(overrides)
    return AgentDeclaration(**base)


class EchoAgent(Agent):
    """A no-op agent. Returns its input, counts its runs, and can be told to fail.

    It exists to exercise the spine end to end without any intelligence in the
    path, which is exactly what Phase 1 is meant to prove.
    """

    def __init__(self, declaration: AgentDeclaration | None = None) -> None:
        super().__init__(declaration or echo_declaration())
        self.runs: list[str] = []
        self.starts = 0
        self.stops = 0
        self.fail_with: Exception | None = None

    def on_start(self) -> None:
        self.starts += 1

    def on_stop(self) -> None:
        self.stops += 1

    def execute(self, task: Any) -> TaskResult:
        if self.fail_with is not None:
            raise self.fail_with
        self.runs.append(task.id)
        return TaskResult(
            task_id=task.id,
            agent=self.id,
            data={"echoed": task.args},
            spoken_summary="Echo ran.",
            cost={"llm_tokens": 0, "tool_calls": 0, "wall_ms": 0},
        )
