# Spec: Genesis Markdown/60-UI/Automation.md
"""A compiled workflow, as an agent, and the wiring that puts it on the roster.

:class:`WorkflowAgent` walks the chain from ``start``: each step either passes
(follow ``next``) or fails. A failed check or pass/fail node with an ``on_fail``
branch is a branch, not a failure; anything else that fails stops the run and
records why. The run reads its version once, at construction, so editing a
workflow never changes a run already in flight -- the edit re-registers a new
agent object.

What each step receives: ``input`` names an earlier step, or ``trigger`` -- the
data the run started with (the event that fired it, or the caller's data when a
workflow runs as a process inside another).

A process runs inline, as one step of its caller, under the caller's agent id:
it is the same runner walking another list, not one agent calling another. It
is bounded -- three levels deep, and never a workflow already on the stack.

No order path. This package imports nothing from execution or risk, and
``tests/automation/test_import_graph.py`` proves it by importing every module in
a clean interpreter and inspecting what got loaded.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from genesis.agents.base import Agent, TaskFailure, TaskResult
from genesis.automation import actions as act
from genesis.automation.store import WorkflowStore
from genesis.automation.workflow import TRIGGER_INPUT, Step, Workflow, agent_id_for, compile_declaration
from genesis.bus import Lane
from genesis.mcp.fence import text_of

__all__ = ["WorkflowAgent", "register_all", "sync"]

REPO = Path(__file__).resolve().parents[3]
#: Closed registry. A target is a command in the repo, never a string from a row.
REFRESH_COMMANDS: dict[str, list[str]] = {
    "vault-map": [sys.executable, "scripts/build_vault_map.py"],
    "corpus-index": ["bash", "build_index.sh"],
}
OUTPUT_TEXT_LIMIT = 4000
MAX_PROCESS_DEPTH = 3
MAX_EACH = 50

#: Kept as the name the rest of the package already uses.
StepFailed = act.Fail


class WorkflowAgent(Agent):
    def __init__(
        self,
        workflow: Workflow,
        version: int,
        *,
        store: WorkflowStore,
        bus: Any,
        gateway: Any = None,
        family_of: Callable[[str], str | None] = lambda _agent: None,
        calendar: Any = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(compile_declaration(workflow))
        self.workflow = workflow
        self.version = version
        self.store = store
        self.bus = bus
        self.gateway = gateway
        self.family_of = family_of
        if calendar is None:
            from genesis.daemon.calendar import MarketCalendar

            calendar = MarketCalendar()
        self.calendar = calendar
        self.clock = clock

    def execute(self, task: Any) -> TaskResult | TaskFailure:
        started = self.clock().isoformat(timespec="seconds")
        args = dict(getattr(task, "args", {}) or {})
        seed = act.out(str(args.get("event") or args.get("reason") or ""), args)
        status, reason, record, _last = self._walk(self.workflow, task, seed, stack=[self.workflow.id])

        self.store.record_run(
            run_id=task.id, workflow_id=self.workflow.id, version=self.version,
            started_at=started, status=status, steps=record,
        )
        self.bus.log.append(
            actor=self.id, kind=f"automation.run.{status}",
            trace_id=getattr(task, "trace_id", "") or task.id,
            summary=f"{self.workflow.name}: {status}" + (f" — {reason}" if reason else ""),
            payload={"workflow": self.workflow.id, "version": self.version, "run": task.id},
            degraded=status == "failed",
        )
        if status == "failed":
            # The work failed, not the agent: degraded and not retryable, so a
            # flaky news source neither loops on the bus nor counts as a crash.
            return TaskFailure(task_id=task.id, agent=self.id, failure_class="degraded",
                               reason=reason or "failed", retryable=False)
        return TaskResult(task_id=task.id, agent=self.id,
                          data={"run": task.id, "status": status, "steps": record})

    # -- the walk ----------------------------------------------------------

    def _walk(
        self, workflow: Workflow, task: Any, seed: dict[str, Any], *, stack: list[str],
    ) -> tuple[str, str | None, list[dict[str, Any]], dict[str, Any] | None]:
        """Run one chain. Returns (status, reason, per-step record, last output)."""
        outputs: dict[str, dict[str, Any]] = {TRIGGER_INPUT: seed}
        record: list[dict[str, Any]] = []
        status, reason, last = "ok", None, None
        at = workflow.start

        while at is not None:
            step = workflow.step(at)
            try:
                outputs[step.id] = last = self._run(workflow, step, outputs, task, stack)
                record.append({"step": step.id, "status": "ok", "output": outputs[step.id]})
                at = step.next
            except act.Stop as exc:
                record.append({"step": step.id, "status": "ok", "output": act.out(str(exc))})
                at = None
            except act.Fail as exc:
                record.append({"step": step.id, "status": "failed", "reason": str(exc)})
                if step.on_fail is not None:
                    outputs[step.id] = act.out(str(exc), {"failed": True, "reason": str(exc)})
                    at = step.on_fail
                    continue
                status, reason, at = "failed", f"{step.id}: {exc}", None
            except Exception as exc:  # noqa: BLE001 - recorded, then reported as a failure
                record.append({"step": step.id, "status": "failed",
                               "reason": f"{type(exc).__name__}: {exc}"})
                status, reason, at = "failed", f"{step.id}: {exc}", None

        ran = {r["step"] for r in record}
        record += [{"step": s.id, "status": "skipped"} for s in workflow.steps if s.id not in ran]
        return status, reason, record, last

    # -- steps -------------------------------------------------------------

    def _run(
        self, workflow: Workflow, step: Step, outputs: dict[str, dict[str, Any]],
        task: Any, stack: list[str],
    ) -> dict[str, Any]:
        data = outputs.get(step.input) if step.input else None

        if step.kind == "gather":
            return self._gather(workflow, step, data, task, stack)

        if step.kind == "check":
            _check(step, data or {})
            return {"passed": True, **(data or {})}

        if step.kind == "refresh":
            done = subprocess.run(
                REFRESH_COMMANDS[step.target], cwd=REPO, capture_output=True,  # type: ignore[index]
                text=True, timeout=300,
            )
            if done.returncode != 0:
                raise act.Fail(done.stderr.strip()[-500:] or f"exit {done.returncode}")
            return {"text": done.stdout.strip()[-500:]}

        if step.kind == "run":
            handed = ({"text": data.get("text", ""), "untrusted": True}
                      if data and data.get("untrusted") else data)
            task_id = self._dispatch(workflow, task, step.agent, f"{step.agent}.run",  # type: ignore[arg-type]
                                     {**step.args, "input": handed})
            return {"text": f"handed to {step.agent}", "structured": {"task": task_id}}

        return self._action(workflow, step, data, task, stack)

    def _gather(
        self, workflow: Workflow, step: Step, data: dict[str, Any] | None, task: Any, stack: list[str],
    ) -> dict[str, Any]:
        """One tool call, or one per input item. Date slots in string args are filled first."""
        if self.gateway is None:
            raise act.Fail("no tool gateway — tools are not connected")
        ctx = self._context(workflow, step, task, stack)
        args = {k: act.render(v, ctx, data) if isinstance(v, str) else v for k, v in step.args.items()}

        def call(arguments: dict[str, Any]) -> dict[str, Any]:
            result = self.gateway.call(self.id, step.capability, arguments)
            return _tool_output(result)

        if not step.each:
            return call(args)
        rows = act.items_of(data)[:MAX_EACH]
        if not rows:
            raise act.Fail("repeat for each: the input has no items")
        merged, errors, untrusted = [], [], False
        for row in rows:
            key = act.symbol_of(row) or row
            try:
                one = call({**args, step.each_arg: key})  # type: ignore[dict-item]
            except Exception as exc:  # noqa: BLE001 - one bad symbol is a row, not the run
                errors.append({"item": key, "error": str(exc)[:200]})
                continue
            untrusted = untrusted or bool(one.get("untrusted"))
            for item in act.items_of(one) or [one.get("structured") or {"text": one.get("text", "")}]:
                merged.append({"symbol": key, **item} if isinstance(item, dict) and "symbol" not in item else item)
        if not merged and errors:
            raise act.Fail(f"every call failed: {errors[0]['error']}")
        body = act.out(f"{len(merged)} result(s) from {len(rows)} call(s)",
                       {"items": merged, "errors": errors}, merged)
        return {**body, "untrusted": True} if untrusted else body

    def _action(
        self, workflow: Workflow, step: Step, data: dict[str, Any] | None, task: Any, stack: list[str],
    ) -> dict[str, Any]:
        action = act.ACTIONS[step.action]  # type: ignore[index]
        ctx = self._context(workflow, step, task, stack)
        params = act.numbers(step.params, action)
        if not step.each:
            return action.run(ctx, params, data)

        rows = act.items_of(data)[:MAX_EACH]
        if not rows:
            raise act.Fail("repeat for each: the input has no items")
        passed, failed = [], []
        for row in rows:
            one = {**params, action.each: act.symbol_of(row) or row}  # type: ignore[dict-item]
            try:
                result = action.run(ctx, one, {"text": "", "structured": row})
                passed.append({"item": act.symbol_of(row) or row, **(result.get("structured") or {}),
                               "text": result.get("text", "")})
            except act.Fail as exc:
                failed.append({"item": act.symbol_of(row) or row, "reason": str(exc)})
        text = "\n".join(p["text"] for p in passed) or f"none of {len(rows)} passed"
        if action.branches and not passed:
            raise act.Fail(f"none of {len(rows)} passed: " + "; ".join(f["reason"] for f in failed[:3]))
        return act.out(text, {"passed": passed, "failed": failed, "count": len(passed)}, passed)

    def _context(self, workflow: Workflow, step: Step, task: Any, stack: list[str]) -> act.Context:
        now = self.clock()

        def dispatch(agent: str, task_type: str, args: dict[str, Any]) -> str | None:
            return self._dispatch(workflow, task, agent, task_type, args)

        def alert(title: str, message: str, urgency: str) -> str:
            alert_id = f"al_{uuid.uuid4().hex[:12]}"
            self.store.add_alert(alert_id=alert_id, workflow_id=workflow.id, run_id=task.id,
                                 step_id=step.id, at=now.isoformat(timespec="seconds"),
                                 title=title[:200], message=message[:4000], urgency=urgency)
            self.bus.log.append(
                actor=self.id, kind="automation.alert",
                trace_id=getattr(task, "trace_id", "") or task.id, summary=title[:200],
                payload={"alert": alert_id, "workflow": workflow.id, "message": message[:4000],
                         "urgency": urgency},
            )
            return alert_id

        def history(step_id: str) -> list[tuple[datetime, dict[str, Any]]]:
            found = []
            for run in self.store.runs(workflow.id, limit=50):
                for rec in run["steps"]:
                    if rec.get("step") == step_id and rec.get("status") == "ok":
                        found.append((datetime.fromisoformat(run["started_at"]), rec))
            return found

        def previous_output(step_id: str) -> dict[str, Any] | None:
            hits = history(step_id)
            return hits[0][1].get("output") if hits else None

        def last_passed_at(step_id: str) -> datetime | None:
            hits = history(step_id)
            return hits[0][0] if hits else None

        def last_alert_at(step_id: str) -> datetime | None:
            at = self.store.last_alert_at(workflow.id, step_id)
            return datetime.fromisoformat(at) if at else None

        def run_process(workflow_id: str, data: dict[str, Any] | None) -> dict[str, Any]:
            if workflow_id in stack:
                raise act.Fail(f"process {workflow_id!r} is already running in this chain")
            if len(stack) >= MAX_PROCESS_DEPTH:
                raise act.Fail(f"processes nest at most {MAX_PROCESS_DEPTH} deep")
            current = self.store.current(workflow_id)
            if current is None:
                raise act.Fail(f"no process called {workflow_id!r}")
            status, reason, record, last = self._walk(
                current.workflow(), task, data or act.out(), stack=[*stack, workflow_id])
            if status == "failed":
                raise act.Fail(f"process {workflow_id}: {reason}")
            return {**(last or act.out()), "process": {"id": workflow_id, "steps": record}}

        return act.Context(
            workflow=workflow, step=step, now=now, tz=self.calendar.tz, calendar=self.calendar,
            dispatch=dispatch, alert=alert, previous_output=previous_output,
            last_passed_at=last_passed_at, last_alert_at=last_alert_at, run_process=run_process,
        )

    def _dispatch(self, workflow: Workflow, task: Any, agent: str, task_type: str,
                  args: dict[str, Any]) -> str | None:
        if self.family_of(agent) == "execution":
            raise act.Fail("a workflow cannot dispatch an execution agent")
        submitted = self.bus.submit(
            type=task_type, agent=agent, lane=Lane.RESEARCH, args=args,
            origin={"kind": "workflow", "ref": workflow.id},
            trace_id=getattr(task, "trace_id", None) or None,
        )
        return submitted.id if submitted else None


_FENCE_OPEN = re.compile(r"^\s*<untrusted[^>]*>\s*")
_FENCE_CLOSE = re.compile(r"\s*</untrusted>\s*$")


def _tool_output(result: Any) -> dict[str, Any]:
    """A tool result as a step output: text for reading, parsed data for deterministic nodes.

    Most servers return JSON as text rather than MCP structured content, so the
    payload is parsed here -- otherwise filter, sort and count see nothing. A
    fenced (untrusted) result keeps its fenced text and is marked ``untrusted``:
    the parsed fields feed comparisons and templates, and are stripped before
    anything is handed to an agent (see ``_dispatch`` callers).
    """
    text = text_of(result.content)
    structured = getattr(result, "structured", None)
    fenced = getattr(result, "fence", None) is not None
    if structured is None:
        inner = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text)) if fenced else text
        try:
            structured = json.loads(inner)
        except (TypeError, ValueError):
            structured = None
    if isinstance(structured, dict) and structured.get("success") is False and structured.get("error"):
        raise act.Fail(str(structured["error"])[:300])
    if fenced and text.lstrip().startswith("<untrusted") and "Error calling tool" in text[:200]:
        raise act.Fail(_FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text))[:300])
    body: dict[str, Any] = {"text": text[:OUTPUT_TEXT_LIMIT], "structured": structured}
    items = act.items_of(body)
    if items:
        body["items"] = items
    if fenced:
        body["untrusted"] = True
    return body


def _count(output: dict[str, Any]) -> int:
    """Items if the output holds a list (even an empty one); otherwise 1 for any content."""
    structured = output.get("structured")
    holds_list = isinstance(output.get("items"), list) or isinstance(structured, list) or (
        isinstance(structured, dict) and any(isinstance(v, list) for v in structured.values()))
    if holds_list:
        return len(act.items_of(output))
    return 1 if structured or str(output.get("text") or "").strip() else 0


def _check(step: Step, output: dict[str, Any]) -> None:
    if step.predicate == "non_empty":
        if _count(output) == 0:
            raise act.Fail(f"{step.input} returned nothing")
    elif step.predicate == "min_count":
        if (n := _count(output)) < (step.value or 0):
            raise act.Fail(f"{step.input} returned {n}, needed {step.value:g}")
    else:
        structured = output.get("structured") or {}
        raw = act.get_field(structured, step.field or "") if isinstance(structured, dict) else None
        try:
            actual = float(raw)
        except (TypeError, ValueError):
            # Fail closed: a value that is not there does not pass a comparison.
            raise act.Fail(f"{step.input} has no numeric {step.field!r}") from None
        ok = {">": actual > step.value, "<": actual < step.value,
              ">=": actual >= step.value, "<=": actual <= step.value}[step.op]  # type: ignore[operator,index]
        if not ok:
            raise act.Fail(f"{step.field} = {actual:g}, not {step.op} {step.value:g}")


# -- the roster ------------------------------------------------------------


def _family_of(daemon: Any) -> Callable[[str], str | None]:
    def family(agent_id: str) -> str | None:
        declaration = daemon.scheduler.declaration(agent_id)
        return declaration.family if declaration else None
    return family


def sync(daemon: Any, store: WorkflowStore, workflow_id: str, gateway: Any = None) -> bool:
    """Make the roster match the store for one workflow. Returns whether it is scheduled.

    Must run on the daemon's thread (``Daemon.call_soon``). An edit replaces the
    agent object without unregistering, because ``Scheduler.register`` keeps run
    history by id -- so saving a 30-second workflow does not make it due again.
    """
    agent_id = agent_id_for(workflow_id)
    current = store.current(workflow_id)
    if current is None or not current.enabled:
        daemon.unregister(agent_id)
        if gateway is not None:
            gateway.revoke(agent_id)
        return False
    old = daemon.supervisor.agent(agent_id)
    if old is not None:
        old.stop(grace_sec=0.0)
    agent = WorkflowAgent(current.workflow(), current.version, store=store, bus=daemon.bus,
                          gateway=gateway, family_of=_family_of(daemon), calendar=daemon.calendar)
    if gateway is not None:
        gateway.revoke(agent_id)
        gateway.grant(agent.declaration)
    daemon.register(agent)
    agent.start()
    return True


def register_all(daemon: Any, store: WorkflowStore, gateway: Any = None) -> int:
    """At boot: every enabled, non-deleted workflow. The store is the only source."""
    return sum(sync(daemon, store, v.workflow_id, gateway) for v in store.list())
