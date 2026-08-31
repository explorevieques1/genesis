# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""Utterance in, task DAG out -- or an honest decline.

Orchestrator.md gives four planning rules, and the order they are implemented
in matters more than any of them individually:

1. **Trivial requests skip planning.** Handled upstream by
   :class:`~genesis.orchestrator.answers.TrivialAnswerer`, before this module
   is reached. *"What time is it"* needs no task list and no model.
2. **Fail open.** If planning fails, hand the raw utterance to the large tier.
   Never leave the user unanswered. Every failure path here returns a
   :class:`PlanOutcome` with ``plan=None`` and a reason; **nothing raises**.
3. **Small models get direct-exec** -- resolve one step at a time rather than
   planning the whole chain. ``direct_exec=True``.
4. **Dependencies are explicit.** The bus honours them; this module only has
   to emit them correctly, and :func:`~genesis.orchestrator.plan.validate_plan`
   proves it did.

**The model's output is never trusted.** It is JSON parsed into a strict
schema, then validated against the live agent catalogue, then rejected for
cycles, dangling references, unknown agents, wrong task types, oversized args,
and the execution family. What survives is a plan whose every field was checked
by deterministic code. This is the reflex-arc principle applied to a planner:
the safety property does not live in the prompt, because *a reflex cannot be
talked out of firing by a persuasive prompt* -- and an utterance can contain
anything, including text someone else wrote.

**An empty catalogue costs nothing.** With no agents registered there is
nothing to plan, and the planner declines before the model call rather than
paying a round trip to hallucinate an agent name. That is the honest state
until Phase 4.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from genesis.errors import GenesisError
from genesis.orchestrator.plan import (
    MAX_TASKS,
    Plan,
    PlanError,
    parse_plan,
    validate_plan,
)
from genesis.orchestrator.registry import CapabilityRegistry

__all__ = ["PLANNER_SYSTEM", "PlanOutcome", "Planner"]

# The stable half of the prompt. Frozen and volatile-free for the same reason
# as the Reasoner's: prompt caching is a prefix match, so a timestamp or a
# session id here would invalidate the cache on every single turn.
PLANNER_SYSTEM = """You are the planner inside Genesis, a voice-driven trading system.

You do not answer questions and you do not do the work. You decide which agents \
should do it, and in what order. Another component speaks the result.

Given what the trader said, emit a task list as JSON:

{"tasks": [{"id": "t1", "type": "<task type>", "agent": "<agent id>", \
"args": {}, "depends_on": []}], "speak_after": "t1"}

Rules:
- Use only the agents listed below, and only the task types listed for each. \
Never invent an agent, a task type, or an argument name.
- depends_on names other task ids in this same plan. Use it only for a real \
ordering requirement — independent work should run in parallel, not in a chain.
- args carry parameters, never data. Keep them small.
- speak_after is the id of the task whose result should be spoken. Usually the \
last one.
- Prefer the smallest plan that answers the request. One task is a good plan.

If no listed agent can do what was asked, reply with exactly: {"tasks": []}
That is a correct answer, not a failure. Something else handles it.

Reply with JSON and nothing else. No prose, no markdown fence, no explanation."""

_DIRECT_EXEC_RULE = (
    "\n\nPlan ONE task only — the first step. Do not chain. "
    "The next step is planned after this one returns."
)


@dataclass(frozen=True)
class PlanOutcome:
    """What planning produced, and why.

    ``plan is None`` always means *fail open* -- the caller hands the utterance
    to the large tier. ``reason`` is why, in plain words, so the Episodic Log
    records a decline as a decision rather than a silence.
    """

    plan: Plan | None
    reason: str = ""
    latency_ms: float = 0.0
    #: True when the planner declined without calling a model. Distinguishes
    #: "nothing to plan for" from "the model got it wrong", which are different
    #: problems with different fixes.
    free: bool = False

    def __bool__(self) -> bool:
        return self.plan is not None


class Planner:
    """Decomposes a directed utterance into a task DAG.

    ``backend`` is any :class:`~genesis.llm.backend.Backend`. The small tier is
    the right default -- this is a routing decision over a short fixed
    catalogue, not analysis -- and LLM Model Tiers' rule is to default down.
    """

    def __init__(
        self,
        backend: Any,
        registry: CapabilityRegistry,
        *,
        max_tasks: int = MAX_TASKS,
        direct_exec: bool = False,
        max_output_tokens: int = 700,
        verbosity: str = "brief",
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.direct_exec = direct_exec
        self.max_tasks = 1 if direct_exec else max_tasks
        self.max_output_tokens = max_output_tokens
        self.verbosity = verbosity

    # -- the prompt --------------------------------------------------------

    def system_prompt(self) -> str:
        """Frozen preamble, then the catalogue.

        The catalogue goes last because it is the part that changes when an
        agent is added or its cadence altered; everything before it stays
        byte-identical across turns and therefore stays cacheable.
        """
        parts = [PLANNER_SYSTEM]
        if self.direct_exec:
            parts.append(_DIRECT_EXEC_RULE)
        parts.append(f"\n\nAgents available to you:\n{self.registry.catalogue()}")
        return "".join(parts)

    # -- planning ----------------------------------------------------------

    def plan(self, utterance: str, *, context: str = "") -> PlanOutcome:
        """Plan, or decline. Never raises.

        The exception handling is deliberately total. This sits on the voice
        path between hearing a request and answering it, and there is no
        failure here -- a malformed model response, an unreachable API, a
        hallucinated agent, a bug in this file -- that is worse than falling
        through to the large tier and answering the person.
        """
        started = time.monotonic()

        def outcome(plan: Plan | None, reason: str, *, free: bool = False) -> PlanOutcome:
            return PlanOutcome(
                plan=plan,
                reason=reason,
                latency_ms=(time.monotonic() - started) * 1000,
                free=free,
            )

        if not utterance.strip():
            return outcome(None, "nothing was said", free=True)
        if not self.registry:
            return outcome(None, "no agents are registered to plan for", free=True)
        if self.backend is None:
            return outcome(None, "no planning model is available", free=True)

        try:
            completion = self.backend.complete(
                self._user_prompt(utterance, context),
                system=self.system_prompt(),
                max_tokens=self.max_output_tokens,
            )
        except GenesisError as exc:
            return outcome(None, f"planning model unavailable: {exc.reason}")
        except Exception as exc:  # noqa: BLE001 - never leak onto the voice path
            return outcome(None, f"planning model raised {type(exc).__name__}: {exc}")

        raw = (getattr(completion, "text", "") or "").strip()
        if not raw:
            return outcome(None, "the planner returned nothing")

        try:
            data = _decode(raw)
        except PlanError as exc:
            return outcome(None, str(exc))

        # The explicit "no agent fits" answer. A decline the model was told to
        # make is a correct answer, and must not be logged as a parse failure --
        # they need different fixes and would otherwise be indistinguishable.
        if isinstance(data, dict) and data.get("tasks") == []:
            return outcome(None, "no registered agent can do that")

        try:
            candidate = parse_plan(data, utterance=utterance)
            plan = validate_plan(candidate, self.registry, max_tasks=self.max_tasks)
        except PlanError as exc:
            return outcome(None, f"the plan was rejected: {exc}")

        if plan.verbosity != self.verbosity:
            plan = plan.model_copy(update={"verbosity": self.verbosity})
        return outcome(plan, "planned")

    def _user_prompt(self, utterance: str, context: str) -> str:
        if not context:
            return f"They said: {utterance}"
        return f"Recent conversation:\n{context}\n\nThey said: {utterance}"


def _decode(raw: str) -> Any:
    """Decode model output into JSON, tolerating the usual wrappers.

    Models fence JSON in markdown and prepend "Here's the plan:" no matter how
    firmly the prompt says not to. Recovering from that is worth four lines;
    the alternative is a fail-open answer for a plan that was actually correct.
    Recovery stops at *structurally* recoverable -- nothing here guesses at
    contents.
    """
    text = raw.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise PlanError(f"the planner did not return JSON: {text[:120]!r}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise PlanError(f"the planner returned invalid JSON: {exc}") from exc
