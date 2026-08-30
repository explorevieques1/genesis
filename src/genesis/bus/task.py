# Spec: Genesis Markdown/10-Architecture/Task Bus.md
"""Task and lane definitions.

Lane order is the scheduling contract, so it lives in the enum's value rather
than in a lookup table that could disagree with it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any

__all__ = ["Lane", "Task", "TaskState", "TERMINAL_STATES"]


class Lane(IntEnum):
    """Priority lanes. Lower value drains first.

    ``execution`` and ``risk`` are never shed and never share a worker pool with
    research -- a task in either must never wait behind an LLM call.
    """

    EXECUTION = 0
    RISK = 1
    USER = 2
    EVENT = 3
    RESEARCH = 4
    MAINTENANCE = 5

    @property
    def sheddable(self) -> bool:
        """Whether this lane may be dropped under load.

        The three protected lanes are protected structurally: nothing in the
        shedding path can reach them, so a future tuning change to thresholds
        cannot accidentally start dropping orders.
        """
        return self >= Lane.EVENT

    @property
    def critical(self) -> bool:
        """Lanes that get the dedicated worker pool."""
        return self <= Lane.USER

    @classmethod
    def parse(cls, value: str | Lane) -> Lane:
        if isinstance(value, Lane):
            return value
        try:
            return cls[value.upper().replace("-", "_")]
        except KeyError:
            raise ValueError(
                f"unknown lane {value!r}; expected one of "
                f"{', '.join(l.name.lower() for l in cls)}"
            ) from None


class TaskState(str, Enum):
    """``pending -> claimed -> running -> done | failed | cancelled | shed``"""

    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SHED = "shed"


TERMINAL_STATES = frozenset(
    {TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED, TaskState.SHED}
)


@dataclass(frozen=True)
class Task:
    """One unit of work, in the note's task shape."""

    id: str
    type: str
    lane: Lane
    agent: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    origin: dict[str, Any] = field(default_factory=dict)
    deadline: str | None = None
    idempotency_key: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    state: TaskState = TaskState.PENDING
    trace_id: str = ""
    claim_id: str | None = None
    claimed_until: float | None = None
    not_before: float | None = None
    result: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Task:
        return cls(
            id=row["id"],
            type=row["type"],
            lane=Lane(row["lane"]),
            agent=row["agent"],
            args=json.loads(row["args"]) if row["args"] else {},
            depends_on=tuple(json.loads(row["depends_on"]) if row["depends_on"] else ()),
            origin=json.loads(row["origin"]) if row["origin"] else {},
            deadline=row["deadline"],
            idempotency_key=row["idempotency_key"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            state=TaskState(row["state"]),
            trace_id=row["trace_id"],
            claim_id=row["claim_id"],
            claimed_until=row["claimed_until"],
            not_before=row["not_before"],
            result=json.loads(row["result"]) if row["result"] else None,
            failure=json.loads(row["failure"]) if row["failure"] else None,
            created_at=row["created_at"],
        )
