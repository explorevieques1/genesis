# Spec: Genesis Markdown/10-Architecture/Orchestrator Tools.md
"""The orchestrator's own tool surface -- how it drives the fleet.

Sixteen tools, fixed. Everything here is *fleet control*: no market data, no
indicators, no charting, no orders. The note's test for whether a tool belongs
here is one question -- *could an agent do this instead?* -- and if the answer
is yes it does not belong.

The count is the design. Orchestrator.md's budget is wake to first spoken word
in under 1.5 s and *"adding 50 MCP tools changes orchestrator latency by less
than 10%"*, and both hold only while this list stays small: every tool added
here is one the planner weighs on every single utterance. :data:`TOOL_NAMES` is
asserted against the class in the tests, so adding a method to this class fails
a test rather than quietly costing latency forever.

Three properties are structural rather than documented:

**Payloads never enter orchestrator context.** :meth:`result_summary` returns
the agent's own ``spoken_summary`` and nothing else; :meth:`result` projects
named fields and refuses anything over :data:`MAX_RESULT_CHARS`. The note is
blunt about why: if the screener returns 40 candidates and the orchestrator
holds them to hand to the synthesizer, the payload is in the latency path and
the context budget is gone by the third turn. **The orchestrator moves ids and
summaries. Never rows.**

**Autonomy can only be tightened.** See :meth:`tighten_autonomy`.

**halt() bypasses the bus.** The bus may be the broken thing. It is a direct
call to the [[Kill Switch]] with no queue, no LLM and no dependency on agent
health in the path.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from genesis.bus.bus import TaskBus
from genesis.bus.task import TERMINAL_STATES, Lane, Task, TaskState
from genesis.orchestrator.plan import Plan

__all__ = [
    "ACCESSORS",
    "AutonomyMode",
    "MAX_RESULT_CHARS",
    "OrchestratorTools",
    "PlanHandle",
    "PlanState",
    "ResultTooLargeError",
    "TOOL_NAMES",
    "Tightening",
]

#: A projection larger than this is a payload wearing a projection's clothes.
#: Roughly a long paragraph -- more than any spoken summary and less than any
#: result set.
MAX_RESULT_CHARS = 600

#: The closed surface. Asserted against the class in the tests, because the
#: only way this list stays small is if growing it is a test failure.
#:
#: ``await_plan`` is the note's ``await``; the name is a Python keyword, and a
#: renamed method is better than a surface that cannot be written in Python.
TOOL_NAMES = frozenset(
    {
        # dispatch
        "dispatch", "cancel", "await_plan",
        # observe
        "task_status", "fleet_status", "queue_depth",
        # results -- references, not payloads
        "result_summary", "result",
        # fleet control
        "start_agent", "stop_agent", "restart_agent", "set_cadence",
        # safety
        "request_approval", "tighten_autonomy", "halt",
        # escape hatch
        "tool_search",
    }
)

#: Public members that are *not* tools: they take no fleet action and reach
#: nothing the tools above have not already reached. Named explicitly so the
#: surface test can subtract them, rather than letting "it's only an accessor"
#: become the hole this list eventually leaks through.
#:
#: ``plan_state`` is the zero-timeout form of ``await_plan`` -- the same reach,
#: without the block -- and is used by the runner between turns.
ACCESSORS = frozenset({"approval_mode", "handle", "plan_state"})


class AutonomyMode(IntEnum):
    """Approval Modes' ladder, ordered by how much autonomy each grants.

    The integer order *is* the semantics: ``min()`` over two modes is the
    stricter one, which is exactly the note's rule for combining a global mode
    with a per-strategy override (*"the effective mode is always
    min(global, strategy)"*) and exactly what makes tightening monotone.
    """

    HALT = 0
    ADVISORY = 1
    CONFIRM = 2
    AUTO_WITHIN_LIMITS = 3

    @property
    def wire_name(self) -> str:
        return self.name.lower().replace("_", "-")

    @classmethod
    def parse(cls, value: str | AutonomyMode) -> AutonomyMode:
        if isinstance(value, AutonomyMode):
            return value
        try:
            return cls[value.upper().replace("-", "_")]
        except KeyError:
            raise ValueError(f"unknown approval mode {value!r}") from None


class Tightening(IntEnum):
    """The modes :meth:`OrchestratorTools.tighten_autonomy` accepts.

    Note what is missing: there is no ``AUTO_WITHIN_LIMITS`` member. The
    loosest mode on the ladder is **not expressible** as an argument to the
    tightening tool -- not rejected at runtime, absent from the type. Approval
    Modes: *"An LLM can never loosen a mode"*, and loosening to full autonomy
    requires the Dashboard.

    Python's type system cannot express "strictly stricter than the current
    value", so the remaining guarantee is carried arithmetically: the tool
    assigns ``min(current, requested)``, which is monotone decreasing and can
    therefore never raise autonomy no matter what is passed. Two mechanisms,
    neither of which is a prompt.
    """

    HALT = AutonomyMode.HALT.value
    ADVISORY = AutonomyMode.ADVISORY.value
    CONFIRM = AutonomyMode.CONFIRM.value


class ResultTooLargeError(ValueError):
    """A projection that would put a payload into orchestrator context."""


@dataclass(frozen=True)
class PlanHandle:
    """What :meth:`OrchestratorTools.dispatch` hands back.

    ``plan_id`` is the trace id every task in the plan shares, so the whole
    plan is one query against the bus and one thread in the Episodic Log.
    """

    plan_id: str
    #: plan-local id (``t1``) -> bus task id. The planner speaks in local ids;
    #: the bus speaks in its own. Nothing outside this class sees both.
    task_ids: dict[str, str]
    speak_after: str
    utterance: str = ""

    @property
    def speak_after_task_id(self) -> str:
        return self.task_ids[self.speak_after]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "tasks": dict(self.task_ids),
            "speak_after": self.speak_after,
        }


@dataclass(frozen=True)
class PlanState:
    """Partial state of a plan -- states only, never payloads."""

    plan_id: str
    states: dict[str, str]
    done: bool
    failed: tuple[str, ...] = ()
    running: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()

    @property
    def any_failed(self) -> bool:
        return bool(self.failed)


class OrchestratorTools:
    """Fleet control. The orchestrator's entire reach into the system.

    Every collaborator is optional and every tool degrades to an honest
    negative rather than an exception when its collaborator is missing. That is
    not politeness: these are called from the voice path, where an unhandled
    exception is silence, and Error Handling And Degradation is explicit that
    voice is a surface, not the spine.

    ``halt`` is the exception to the exception -- if the kill switch is not
    wired, that is a configuration error worth raising about, because a halt
    that quietly does nothing is the worst failure in the system.
    """

    def __init__(
        self,
        bus: TaskBus,
        *,
        supervisor: Any = None,
        scheduler: Any = None,
        kill_switch: Callable[[str], Any] | None = None,
        approver: Callable[[str], Any] | None = None,
        searcher: Callable[[str], Any] | None = None,
        approval_mode: AutonomyMode | str = AutonomyMode.CONFIRM,
        on_autonomy_change: Callable[[AutonomyMode, str], None] | None = None,
    ) -> None:
        self.bus = bus
        self.supervisor = supervisor
        self.scheduler = scheduler
        self._kill_switch = kill_switch
        self._approver = approver
        self._searcher = searcher
        self._mode = AutonomyMode.parse(approval_mode)
        self._on_autonomy_change = on_autonomy_change
        self._plans: dict[str, PlanHandle] = {}

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, plan: Plan) -> PlanHandle:
        """Submit a whole validated DAG at once.

        Taking the plan rather than one task per call is the load-bearing
        choice in the note: a ``run_agent()``-per-call API forces sequential
        round-trips through the planner and makes parallel work impossible to
        express. Fan-out and joins come free here because the bus already
        honours ``depends_on``.

        Two things are decided *here*, not by the planner:

        * **The lane is always** :attr:`Lane.USER`. A plan authored by a model
          cannot place itself in ``execution`` or ``risk``; there is no field
          for it to try.
        * **The idempotency key is derived from the plan's content**, so
          dispatching an identical plan while the first one is still in flight
          adopts the live tasks instead of duplicating them -- and dispatching
          it again *after* it finished runs it again, because the bus's unique
          index covers only live states. Asked twice while it runs is one scan;
          asked again tomorrow is a new scan. Both are what you meant.

        The plan must already have passed
        :func:`~genesis.orchestrator.plan.validate_plan` -- it is submitted in
        the dependency order that produced, so every dependency exists on the
        bus before anything referring to it.
        """
        if not plan.tasks:
            raise ValueError("cannot dispatch an empty plan")
        speak_after = plan.speak_after or plan.tasks[-1].id

        digest = _plan_digest(plan)
        plan_id: str | None = None
        task_ids: dict[str, str] = {}
        for planned in plan.tasks:
            missing = [d for d in planned.depends_on if d not in task_ids]
            if missing:
                # Only reachable if the plan was hand-built out of dependency
                # order. Submitting anyway would create a task whose parent id
                # does not exist, which the bus cancels at claim time with a
                # confusing reason.
                raise ValueError(
                    f"task {planned.id!r} was submitted before its dependencies "
                    f"({', '.join(missing)}) — the plan is not in topological order"
                )
            key = f"{digest}:{planned.id}"
            task = self.bus.submit(
                type=planned.type,
                agent=planned.agent,
                lane=Lane.USER,
                args=dict(planned.args),
                depends_on=[task_ids[d] for d in planned.depends_on],
                origin={"kind": "voice", "ref": plan.utterance[:200]},
                idempotency_key=key,
                trace_id=plan_id,
            )
            if task is None:
                # An identical key is live: reuse the in-flight task rather than
                # duplicating the work. Per Task Bus, a duplicate submit is a
                # no-op, not an error.
                live = [
                    t for t in self.bus.by_idempotency_key(key)
                    if t.state not in TERMINAL_STATES
                ]
                if not live:
                    raise RuntimeError(f"task {planned.id!r} was rejected and is not live")
                task = live[0]
            plan_id = plan_id or task.trace_id
            task_ids[planned.id] = task.id

        assert plan_id is not None
        handle = PlanHandle(
            plan_id=plan_id,
            task_ids=task_ids,
            speak_after=speak_after,
            utterance=plan.utterance,
        )
        self._plans[plan_id] = handle
        return handle

    def cancel(self, ref: str, reason: str) -> int:
        """Cancel a plan or a single task. Returns how many were cancelled.

        The reason propagates: the bus cancels dependents carrying the parent's
        reason, so nothing downstream disappears silently and the orchestrator
        can still say what happened.
        """
        handle = self._plans.get(ref)
        if handle is not None:
            cancelled = 0
            for task_id in handle.task_ids.values():
                if self.bus.cancel(task_id, reason) is not None:
                    cancelled += 1
            return cancelled
        return 1 if self.bus.cancel(ref, reason) is not None else 0

    def await_plan(self, plan_id: str, timeout_ms: int = 2000, *, poll_ms: int = 50) -> PlanState:
        """Block *briefly*. On timeout, return what is done so far.

        Never blocks longer than ``timeout_ms``, and that ceiling is the whole
        point: a backtest takes minutes, and Orchestrator Tools is explicit
        that **voice must never hang on a task**. The caller's contract is to
        speak "on it" on a timeout, not to wait.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        state = self._plan_state(plan_id)
        while not state.done and time.monotonic() < deadline:
            time.sleep(min(poll_ms / 1000, max(0.0, deadline - time.monotonic())))
            state = self._plan_state(plan_id)
        return state

    def plan_state(self, plan_id: str) -> PlanState:
        """Non-blocking :meth:`await_plan`. Not a tool -- an accessor."""
        return self._plan_state(plan_id)

    def handle(self, plan_id: str) -> PlanHandle | None:
        return self._plans.get(plan_id)

    # ------------------------------------------------------------------
    # Observe
    # ------------------------------------------------------------------

    def task_status(self, ids: Sequence[str]) -> dict[str, str]:
        """States only. No payloads, by contract."""
        out: dict[str, str] = {}
        for task_id in ids:
            task = self.bus.get(task_id)
            out[task_id] = task.state.value if task is not None else "unknown"
        return out

    def fleet_status(self) -> dict[str, dict[str, Any]]:
        """Every agent's ``status()`` in one call, not thirty."""
        if self.supervisor is None:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for agent_id in self.supervisor.agent_ids:
            agent = self.supervisor.agent(agent_id)
            if agent is not None:
                out[agent_id] = agent.status().to_dict()
        return out

    def queue_depth(self) -> dict[str, int]:
        """Depth per lane, so the orchestrator can warn you when work is shed."""
        return {lane.name.lower(): self.bus.depth(lane) for lane in Lane}

    # ------------------------------------------------------------------
    # Results -- references, not payloads
    # ------------------------------------------------------------------

    def result_summary(self, task_id: str) -> str | None:
        """The agent's own ``spoken_summary``, already number-formatted.

        The only payload the orchestrator should ever hold, because saying it
        out loud is its job.
        """
        task = self.bus.get(task_id)
        if task is None or task.result is None:
            return None
        summary = task.result.get("spoken_summary")
        return summary if isinstance(summary, str) and summary.strip() else None

    def result(self, task_id: str, fields: Sequence[str]) -> dict[str, Any]:
        """Named fields, projected. Never the whole object.

        Raises :class:`ResultTooLargeError` rather than truncating: a silently
        clipped projection is a number that looks complete and is not, and this
        system speaks numbers aloud.
        """
        if not fields:
            raise ValueError("result() requires explicit field names — it never returns the whole object")
        task = self.bus.get(task_id)
        if task is None or task.result is None:
            return {}
        data = task.result.get("data") or {}
        projection = {f: data[f] for f in fields if f in data}
        size = len(json.dumps(projection, default=str))
        if size > MAX_RESULT_CHARS:
            raise ResultTooLargeError(
                f"projection of {', '.join(fields)} is {size} chars, over the "
                f"{MAX_RESULT_CHARS} limit — pass a reference, not rows"
            )
        return projection

    # ------------------------------------------------------------------
    # Fleet control
    # ------------------------------------------------------------------

    def start_agent(self, agent_id: str) -> bool:
        agent = self._agent(agent_id)
        if agent is None:
            return False
        agent.start()
        return True

    def stop_agent(self, agent_id: str, grace_sec: float = 5.0) -> bool:
        agent = self._agent(agent_id)
        if agent is None:
            return False
        agent.stop(grace_sec=grace_sec)
        return True

    def restart_agent(self, agent_id: str) -> bool:
        import datetime as dt

        if self.supervisor is None or self._agent(agent_id) is None:
            return False
        return bool(self.supervisor.restart(agent_id, dt.datetime.now(dt.UTC)))

    def set_cadence(self, agent_id: str, interval_sec: int) -> bool:
        """Transiently change an agent's interval. Reverts at the next session."""
        if self.scheduler is None:
            return False
        return bool(self.scheduler.set_cadence(agent_id, interval_sec))

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    @property
    def approval_mode(self) -> AutonomyMode:
        return self._mode

    def request_approval(self, proposal_id: str) -> Any:
        """Route a proposal to Approval Modes.

        Fails closed. With no approver wired there is no path to an approval,
        and the honest answer is a refusal -- never "assume fine and continue"
        (Safety Invariants §2).
        """
        if self._approver is None:
            return {"approved": False, "reason": "no approval path is wired"}
        return self._approver(proposal_id)

    def tighten_autonomy(self, mode: Tightening, reason: str = "") -> AutonomyMode:
        """Tighten the approval mode. **Tighten only.**

        Two independent reasons this cannot loosen:

        1. :class:`Tightening` has no ``AUTO_WITHIN_LIMITS`` member, so the
           loosest mode cannot be named at the call site at all.
        2. The assignment is ``min(current, requested)`` -- monotone
           decreasing. Passing ``CONFIRM`` while already in ``ADVISORY`` is a
           no-op, not a loosening.

        Safety Invariants §9: loosening is a Dashboard action, never by voice,
        never by an agent.
        """
        requested = AutonomyMode(int(mode))
        previous = self._mode
        self._mode = AutonomyMode(min(previous, requested))
        if self._mode is not previous and self._on_autonomy_change is not None:
            self._on_autonomy_change(self._mode, reason)
        return self._mode

    def halt(self, reason: str = "operator") -> Any:
        """Straight to the Kill Switch. Bypasses the bus.

        The bus may be the broken thing, so nothing here queues, waits on agent
        health, or touches a model. This is the one tool that must work when
        nothing else does, and an unwired kill switch raises rather than
        returning a falsy value nobody checks.
        """
        if self._kill_switch is None:
            raise RuntimeError(
                "halt() called with no kill switch wired — this must never be "
                "reachable in a running system (Safety Invariants §4)"
            )
        return self._kill_switch(reason)

    # ------------------------------------------------------------------
    # Escape hatch
    # ------------------------------------------------------------------

    def tool_search(self, query: str) -> Any:
        """When no agent fits: let the gateway route tools directly.

        The planner's fail-open rule made concrete. Returns an empty list until
        the Phase 3 gateway exists, which the caller reads as "nothing found"
        and answers on the large tier.
        """
        if self._searcher is None:
            return []
        return self._searcher(query)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _agent(self, agent_id: str) -> Any:
        if self.supervisor is None:
            return None
        return self.supervisor.agent(agent_id)

    def _plan_state(self, plan_id: str) -> PlanState:
        handle = self._plans.get(plan_id)
        tasks: list[Task] = (
            [t for t in (self.bus.get(i) for i in handle.task_ids.values()) if t is not None]
            if handle is not None
            else self.bus.by_trace(plan_id)
        )
        states = {t.id: t.state.value for t in tasks}
        failed = tuple(
            t.id for t in tasks
            if t.state in (TaskState.FAILED, TaskState.CANCELLED, TaskState.SHED)
        )
        running = tuple(t.id for t in tasks if t.state in (TaskState.CLAIMED, TaskState.RUNNING))
        pending = tuple(t.id for t in tasks if t.state is TaskState.PENDING)
        done = bool(tasks) and all(t.state in TERMINAL_STATES for t in tasks)
        return PlanState(
            plan_id=plan_id,
            states=states,
            done=done,
            failed=failed,
            running=running,
            pending=pending,
        )


def _plan_digest(plan: Plan) -> str:
    """A stable fingerprint of what a plan asks for.

    Deliberately excludes the utterance: *"check semis"* and *"have a look at
    semis"* produce the same tasks and should not run twice. What it covers is
    exactly what the bus would execute -- agent, type, args, ordering.
    """
    payload = json.dumps(
        [
            {
                "id": t.id,
                "agent": t.agent,
                "type": t.type,
                "args": t.args,
                "depends_on": list(t.depends_on),
            }
            for t in plan.tasks
        ],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
