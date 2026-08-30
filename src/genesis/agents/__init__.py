# Spec: Genesis Markdown/10-Architecture/Agent Contract.md
"""The agent fleet. Phase 1 ships the contract only — no real agents."""

from genesis.agents.base import (
    Agent,
    AgentDeclaration,
    AgentState,
    Cadence,
    Health,
    Status,
    TaskFailure,
    TaskResult,
)

__all__ = [
    "Agent",
    "AgentDeclaration",
    "AgentState",
    "Cadence",
    "Health",
    "Status",
    "TaskFailure",
    "TaskResult",
]
