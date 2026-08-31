# Spec: Genesis Markdown/10-Architecture/Orchestrator Tools.md
"""Running a plan without ever letting voice wait on it.

The note names three behaviours to get right, and this module is where all
three are either true or not:

**Fan-out / fan-in.** Free, because :meth:`OrchestratorTools.dispatch` submits
the whole DAG in one call and the bus honours ``depends_on``. Three independent
tasks are three parallel tasks; nothing here serialises them.

**Never block on slow work.** Dispatch, await ~2 s, and if it is not done say
*"running it now, I'll tell you when it's done"* and return. A backtest takes
minutes and **voice must never hang on a task**. The plan keeps running; a
later :meth:`PlanRunner.collect` speaks its result when it lands.

**Fail honestly.** When a dependency fails the bus cancels its dependents
carrying the parent's reason, so the spoken failure names the actual cause --
*"the screener couldn't reach the feed, so there's no chart"* -- rather than
going quiet or blaming the last task in the chain. Silence on failure is the
behaviour Error Handling And Degradation and Safety Invariants §10 both forbid.

The runner holds ids and one sentence per plan. It never reads a task's
``data``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from genesis.bus.task import TaskState
from genesis.orchestrator.answers import Answer
from genesis.orchestrator.plan import Plan
from genesis.orchestrator.tools import OrchestratorTools, PlanHandle, PlanState

__all__ = ["PlanRunner"]

#: How long a spoken failure reason may be. Long enough for a real cause, short
#: enough that a stack trace or a paragraph of provider error cannot be read
#: aloud at someone.
MAX_REASON_CHARS = 160


@dataclass
class PlanRunner:
    """Dispatches a plan and turns its outcome into one spoken sentence."""

    tools: OrchestratorTools
    memory: Any = None
    await_ms: int = 2000
    #: Plans that outlived their await window, still running. Spoken on
    #: :meth:`collect`, which the voice loop calls while it is idle.
    _watching: dict[str, PlanHandle] = field(default_factory=dict, repr=False)

    # -- the voice-path entry point ---------------------------------------

    def run(self, plan: Plan) -> Answer:
        """Dispatch, wait briefly, and answer.

        Returns an :class:`~genesis.orchestrator.answers.Answer` in every case
        -- done, failed, or still running. There is no path through this method
        that leaves the operator without a sentence.
        """
        try:
            handle = self.tools.dispatch(plan)
        except Exception as exc:  # noqa: BLE001 - a dispatch fault must not be silence
            return Answer(
                f"I couldn't start that: {_clip(str(exc))}", "plan:dispatch-failed"
            )

        if self.memory is not None:
            self.memory.set_plan({**handle.to_dict(), "utterance": plan.utterance})

        state = self.tools.await_plan(handle.plan_id, self.await_ms)
        if not state.done:
            self._watching[handle.plan_id] = handle
            return Answer(_still_running(plan), f"plan:{handle.plan_id}:running")
        return self._final_answer(handle, state)

    # -- the idle path ------------------------------------------------------

    def collect(self) -> list[Answer]:
        """Answers for watched plans that have since finished.

        Called from the voice loop's idle moments rather than from a thread of
        its own: the loop already wakes every 200 ms waiting for speech, and a
        second thread speaking into the same speaker is a race nobody needs.
        """
        answers: list[Answer] = []
        for plan_id, handle in list(self._watching.items()):
            state = self.tools.plan_state(plan_id)
            if not state.done:
                continue
            del self._watching[plan_id]
            answers.append(self._final_answer(handle, state))
        return answers

    @property
    def watching(self) -> tuple[str, ...]:
        return tuple(self._watching)

    def forget(self, plan_id: str) -> None:
        """Stop watching a plan -- used when it is cancelled."""
        self._watching.pop(plan_id, None)

    # -- turning an outcome into a sentence --------------------------------

    def _final_answer(self, handle: PlanHandle, state: PlanState) -> Answer:
        if state.any_failed:
            return Answer(self._failure_sentence(handle, state), f"plan:{handle.plan_id}:failed")

        task_id = handle.speak_after_task_id
        summary = self.tools.result_summary(task_id)
        if summary:
            if self.memory is not None:
                self.memory.note_result(task_id, summary)
            return Answer(summary, f"plan:{handle.plan_id}")

        # Done, but the agent gave nothing to say. Saying so is better than
        # inventing a summary, and it is a real bug report about that agent --
        # Agent Contract requires a spoken_summary on anything voice-initiated.
        agent = self._agent_of(handle, handle.speak_after)
        return Answer(
            f"{_article(agent)} finished, but didn't give me anything to say.",
            f"plan:{handle.plan_id}:no-summary",
        )

    def _failure_sentence(self, handle: PlanHandle, state: PlanState) -> str:
        """Name the cause, not the symptom.

        Downstream tasks are cancelled carrying *"dependency … failed: …"*, so
        the last task in the chain always looks broken. The root cause is the
        first task that actually failed, and that is the one worth saying.
        """
        root_id, root_reason, is_spoken = self._root_cause(handle, state)
        agent = self._agent_of(handle, self._local_id(handle, root_id) or "")
        reason = _clip(root_reason) if root_reason else "failed"

        # Two shapes of reason, and they do not read the same way. An agent's
        # own ``spoken_summary`` is written as a clause to follow its name
        # ("couldn't reach the feed"); a raw ``reason`` is a noun phrase from
        # whatever raised ("no agent registered as 'screener'"). Splicing the
        # second into the first's slot produces "The screener no agent
        # registered as 'screener'", which is the sort of sentence that makes
        # a voice system feel broken even when it is behaving correctly.
        clause = reason if is_spoken else f"failed: {reason}"

        if self._local_id(handle, root_id) == handle.speak_after:
            return f"{_article(agent)} {clause}."
        # Something upstream broke, so what you asked for does not exist.
        return f"{_article(agent)} {clause}, so I don't have the rest of it."

    def _root_cause(self, handle: PlanHandle, state: PlanState) -> tuple[str, str, bool]:
        """``(task_id, reason, reason_is_speakable)`` for the first real failure.

        The third element says which of the two reason shapes came back, so the
        caller can build a sentence rather than a splice.
        """
        ordered = list(handle.task_ids.values())
        failed = [t for t in ordered if t in state.failed]

        # A real failure beats a cancellation: a cancellation is almost always
        # this task being told its parent died.
        for task_id in failed:
            task = self.tools.bus.get(task_id)
            if task is not None and task.state is TaskState.FAILED:
                failure = task.failure or {}
                spoken = failure.get("spoken_summary")
                if spoken:
                    return task_id, spoken, True
                return task_id, failure.get("reason", "failed"), False
        for task_id in failed:
            task = self.tools.bus.get(task_id)
            if task is None:
                continue
            failure = task.failure or {}
            return task_id, failure.get("reason", task.state.value), False
        return (failed[0] if failed else ""), "failed", False

    def _local_id(self, handle: PlanHandle, task_id: str) -> str | None:
        for local, real in handle.task_ids.items():
            if real == task_id:
                return local
        return None

    def _agent_of(self, handle: PlanHandle, local_id: str) -> str:
        task_id = handle.task_ids.get(local_id)
        if task_id is None:
            return "that agent"
        task = self.tools.bus.get(task_id)
        return task.agent if task is not None else "that agent"


def _still_running(plan: Plan) -> str:
    if len(plan.tasks) == 1:
        return "Running it now. I'll tell you when it's done."
    return f"Running it now — {len(plan.tasks)} steps. I'll tell you when it's done."


def _article(agent: str) -> str:
    """``screener`` -> ``The screener``. Agent ids are kebab-case, not prose."""
    if not agent:
        return "That agent"
    return f"The {agent.replace('-', ' ')}"


def _clip(reason: str) -> str:
    reason = " ".join(reason.split())
    if len(reason) <= MAX_REASON_CHARS:
        return reason
    return reason[: MAX_REASON_CHARS - 1].rstrip() + "…"
