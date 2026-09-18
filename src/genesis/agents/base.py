# Spec: Genesis Markdown/10-Architecture/Agent Contract.md
"""The contract every agent implements.

One interface is what makes the fleet composable, supervisable and observable:
the supervisor restarts anything with ``start``/``stop``, the watchdog probes
anything with ``health``, and the dashboard renders anything with ``status``.

Two rules from the note are enforced here rather than documented and hoped for:

**No direct calls to other agents.** Nothing in this module gives an agent a
handle on another one. Work goes on the :mod:`genesis.bus`; results come from
the memory fabric. This is the rule that keeps the system legible, and it holds
because there is no API to break it with.

**Write to your own namespace.** :meth:`AgentDeclaration.may_write` is the check
the memory layer calls. Reading ``shared`` is fine; writing another agent's
namespace is not.

Phase 1 has no LLM anywhere in this file, and neither ``run_task`` nor
``health`` may make one -- ``health`` explicitly, per the note.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from genesis.errors import FailureClass, GenesisError
from genesis.mcp.allowlist import matches

__all__ = [
    "SPINAL_AGENTS",
    "SPINAL_FAMILIES",
    "Agent",
    "AgentDeclaration",
    "AgentState",
    "Cadence",
    "Health",
    "Status",
    "TaskFailure",
    "TaskResult",
]


class AgentState(str, Enum):
    """The five states the note's ``status()`` contract names."""

    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    DOWN = "down"


# --------------------------------------------------------------------------
# Declaration
# --------------------------------------------------------------------------


class Cadence(BaseModel):
    """One entry in an agent's cadence list.

    An agent may declare several -- the Idea Synthesizer is ``market-open:15m``
    plus ``cron`` plus ``event:news.spike``. See Daemon And Cadence.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["on-demand", "market-open", "market-closed", "cron", "event"]
    interval_sec: int | None = Field(default=None, gt=0)
    at: str | None = None  # HH:MM in the daemon's market timezone, for cron
    on: tuple[str, ...] = ()  # event names, for type=event

    @field_validator("on", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    def model_post_init(self, _: Any) -> None:
        # A cadence that declares nothing to fire on will never fire, and a
        # silent no-op agent is far worse than a config error at boot.
        if self.type in ("market-open", "market-closed") and self.interval_sec is None:
            raise ValueError(f"cadence {self.type!r} requires interval_sec")
        if self.type == "cron" and not self.at:
            raise ValueError("cadence 'cron' requires at (HH:MM)")
        if self.type == "event" and not self.on:
            raise ValueError("cadence 'event' requires at least one event in `on`")


class MemoryAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()

    @field_validator("read", "write", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v


#: Families with no model anywhere in them. Safety Invariants §3 names the
#: execution family whole; nothing in it reasons, it all arithmetics.
SPINAL_FAMILIES = ("execution",)

#: The named exceptions -- reflexes that live in a family which otherwise
#: thinks. The guard used to cover the execution family alone, so
#: ``level-watcher`` (family ``charting``) could have acquired a model without
#: anything objecting, and the agent that decides whether a price crossed a
#: line is the last place a sampler belongs. The value is why, so the error
#: message can say it.
SPINAL_AGENTS = {
    "level-watcher": "a price comparison, not a judgement",
    "backtest-runner": "arithmetic over bars",
    "optimizer": "a parameter sweep",
    "risk-metrics": "arithmetic",
    "portfolio-allocation": "position sizing",
    "prop-firm-guard": "a limit check",
    "position-accountant": "position and P&L arithmetic",
    "news-collector": "gathers and stores; it never reads meaning",
    "watchdog": "health thresholds",
    "session-plan": "assembly of stored ideas and the gate's own sizing",
}


class AgentDeclaration(BaseModel):
    """The YAML block at the top of every agent note, as a validated object.

    Deliberately strict: an unknown key is a typo, and a typo'd ``tools`` entry
    would silently widen or narrow an allow-list.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")  # kebab-case, Conventions
    name: str
    family: Literal[
        "research", "charting", "strategy", "execution", "journal", "core"
    ]
    cadence: tuple[Cadence, ...]
    tools: tuple[str, ...] = ()
    memory: MemoryAccess = MemoryAccess()
    model_tier: Literal["none", "nano", "small", "large", "vision"] = "none"
    vision: bool = False
    timeout_sec: int = Field(default=60, gt=0)
    max_concurrent: int = Field(default=1, gt=0)

    @field_validator("cadence", "tools", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    def model_post_init(self, _: Any) -> None:
        # Biological Design §1: these are spinal cord, not "agents we have not
        # given a model to yet", and giving one a model is the bug. Caught at
        # load time because a reflex cannot be talked out of firing by a
        # persuasive prompt -- but it *can* be quietly promoted by an edit.
        if self.family in SPINAL_FAMILIES and self.model_tier != "none":
            raise ValueError(
                f"agent {self.id!r} is in the {self.family} family and must be "
                f"model_tier 'none', got {self.model_tier!r} — see Safety Invariants"
            )
        if self.id in SPINAL_AGENTS and self.model_tier != "none":
            raise ValueError(
                f"agent {self.id!r} is {SPINAL_AGENTS[self.id]} and must be "
                f"model_tier 'none', got {self.model_tier!r} — see Safety Invariants §3"
            )

    def may_use_tool(self, capability: str) -> bool:
        """The allow-list check. The gateway rejects anything this refuses.

        Entries are capability patterns, and ``prefix.*`` grants a namespace --
        one matcher, shared with :mod:`genesis.mcp.allowlist`, because two
        implementations of an allow-list is one implementation and one bug.
        Exact matching alone would have quietly refused every real tool for an
        agent declared with ``genesis-execution.*``, which is how MCP Gateway.md
        writes a whole grant.
        """
        return any(matches(p, capability) for p in self.tools)

    def may_write(self, namespace: str) -> bool:
        """Single-writer namespaces: an agent writes its own, never another's."""
        return namespace in self.memory.write

    def may_read(self, namespace: str) -> bool:
        return namespace in self.memory.read or namespace == "shared"


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskResult:
    """A successful unit of work, in the note's result shape."""

    task_id: str
    agent: str
    data: dict[str, Any] = field(default_factory=dict)
    wrote: tuple[dict[str, Any], ...] = ()
    spoken_summary: str | None = None
    cost: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    status: Literal["ok"] = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
            "degraded": self.degraded,
            "data": self.data,
            "wrote": list(self.wrote),
            "spoken_summary": self.spoken_summary,
            "cost": self.cost,
        }


@dataclass(frozen=True)
class TaskFailure:
    """A typed failure. Never a guessed number dressed up as a result."""

    task_id: str
    agent: str
    failure_class: FailureClass
    reason: str
    retryable: bool
    spoken_summary: str | None = None
    status: Literal["failed"] = "failed"

    @classmethod
    def from_exception(
        cls, task_id: str, agent: str, exc: BaseException
    ) -> TaskFailure:
        """Classify an exception.

        A :class:`GenesisError` carries its own class. Anything else is an
        unhandled bug, and an unhandled bug is ``fatal``: retrying code that
        raised ``KeyError`` will raise ``KeyError`` again, and calling it
        transient turns a bug into an infinite loop.
        """
        if isinstance(exc, GenesisError):
            return cls(
                task_id=task_id,
                agent=agent,
                failure_class=exc.failure_class,
                reason=exc.reason,
                retryable=exc.retryable,
                spoken_summary=exc.spoken_summary,
            )
        return cls(
            task_id=task_id,
            agent=agent,
            failure_class="fatal",
            reason=f"unhandled {type(exc).__name__}: {exc}",
            retryable=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
            "class": self.failure_class,
            "reason": self.reason,
            "retryable": self.retryable,
            "spoken_summary": self.spoken_summary,
        }


@dataclass(frozen=True)
class Status:
    state: AgentState
    last_action: str | None = None
    last_action_at: datetime | None = None
    next_run_at: datetime | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "last_action": self.last_action,
            "last_action_at": (
                self.last_action_at.isoformat() if self.last_action_at else None
            ),
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Health:
    """A cheap liveness probe. No LLM calls, by contract."""

    alive: bool
    detail: str | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------


class Agent(ABC):
    """Base class for every agent in the fleet.

    Subclasses implement :meth:`execute`; the lifecycle around it is provided.
    ``start`` and ``stop`` are idempotent as the note requires, which the
    supervisor depends on -- a restart that races a shutdown must not raise.
    """

    def __init__(self, declaration: AgentDeclaration) -> None:
        self.declaration = declaration
        self._lock = threading.RLock()
        self._state = AgentState.DOWN
        self._last_action: str | None = None
        self._last_action_at: datetime | None = None
        self._next_run_at: datetime | None = None
        self._detail: str | None = None
        self._in_flight = 0

    # -- identity ----------------------------------------------------------

    @property
    def id(self) -> str:
        return self.declaration.id

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.id} {self._state.value}>"

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Acquire resources and become schedulable. Idempotent."""
        with self._lock:
            if self._state is not AgentState.DOWN:
                return
            self._state = AgentState.IDLE
        try:
            self.on_start()
        except Exception:
            with self._lock:
                self._state = AgentState.DOWN
            raise

    def stop(self, grace_sec: float = 5.0) -> None:
        """Drain in-flight work up to ``grace_sec``, then release. Idempotent."""
        with self._lock:
            if self._state is AgentState.DOWN:
                return
        deadline = datetime.now(UTC).timestamp() + grace_sec
        while datetime.now(UTC).timestamp() < deadline:
            with self._lock:
                if self._in_flight == 0:
                    break
            threading.Event().wait(0.01)
        try:
            self.on_stop()
        finally:
            with self._lock:
                self._state = AgentState.DOWN
                self._next_run_at = None

    def on_start(self) -> None:
        """Hook: acquire resources, subscribe to events. Override as needed."""

    def on_stop(self) -> None:
        """Hook: release resources. Override as needed."""

    # -- observation -------------------------------------------------------

    def status(self) -> Status:
        with self._lock:
            return Status(
                state=self._state,
                last_action=self._last_action,
                last_action_at=self._last_action_at,
                next_run_at=self._next_run_at,
                detail=self._detail,
            )

    def health(self) -> Health:
        """Cheap liveness probe for the watchdog. Must not call an LLM."""
        with self._lock:
            return Health(
                alive=self._state
                in (AgentState.IDLE, AgentState.WORKING, AgentState.BLOCKED),
                detail=self._detail,
            )

    def mark_degraded(self, detail: str) -> None:
        with self._lock:
            self._state = AgentState.DEGRADED
            self._detail = detail

    def set_next_run(self, when: datetime | None) -> None:
        with self._lock:
            self._next_run_at = when

    # -- work --------------------------------------------------------------

    def run_task(self, task: Any) -> TaskResult | TaskFailure:
        """Do one unit of work. Returns a typed result or a typed failure.

        Never raises: the supervisor and the bus branch on the returned type,
        and an exception escaping here would bypass the retry classification in
        :meth:`TaskFailure.from_exception`.
        """
        with self._lock:
            if self._state is AgentState.DOWN:
                return TaskFailure(
                    task_id=getattr(task, "id", "<unknown>"),
                    agent=self.id,
                    failure_class="fatal",
                    reason=f"agent {self.id!r} is not started",
                    retryable=False,
                )
            previous = self._state
            self._state = AgentState.WORKING
            self._in_flight += 1

        try:
            result = self.execute(task)
        except BaseException as exc:  # noqa: BLE001 - classified, not swallowed
            result = TaskFailure.from_exception(
                getattr(task, "id", "<unknown>"), self.id, exc
            )
        finally:
            with self._lock:
                self._in_flight -= 1
                self._last_action = getattr(task, "type", None)
                self._last_action_at = datetime.now(UTC)
                # A degraded agent stays degraded until something clears it;
                # finishing one task is not evidence of recovery.
                if self._state is AgentState.WORKING:
                    self._state = (
                        AgentState.IDLE if previous is not AgentState.DEGRADED else previous
                    )
        return result

    @abstractmethod
    def execute(self, task: Any) -> TaskResult | TaskFailure:
        """The agent's actual work. Raise a typed error or return a result."""
        raise NotImplementedError
