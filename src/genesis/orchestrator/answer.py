# Spec: Genesis Markdown/00-Meta/UI-0 Build Order.md §step 0
#       Genesis Markdown/10-Architecture/Operating Model.md §2 §4
#       Genesis Markdown/10-Architecture/Orchestrator.md §the answer ladder
"""The answer ladder, reachable without a microphone.

Orchestrator.md specifies the ladder -- *verbosity command, deterministic
answer, plan, fail open to the large tier* -- and each rung only pays for
itself when the one above declines. That was already built. It was built
**inside** :meth:`~genesis.orchestrator.loop.VoiceLoop._handle`, whose input is
audio frames, so it had exactly one caller and that caller needed a working
microphone.

Meanwhile ``POST /v1/command`` matched the deterministic command table and
stopped, answering *"I didn't catch a command in that"* with a fully-built
reasoner one import away.

That is the whole of the parity failure Operating Model §2 is written against:
**a capability reachable only by speaking is not shipped.** Not because typing
is more convenient -- because a system where the model can reach further than
its operator is one where the operator cannot check the model's work.

So the ladder lives here, as a function of its rungs and nothing else. No
audio, no HTTP, no transport of any kind. Two callers pass what they have:

* :class:`~genesis.orchestrator.loop.VoiceLoop` -- keeps the mic, the wake gate,
  the STT, the earcons, the follow-up window, the speaker. Loses the ladder.
* ``genesis.server.app`` -- calls it when the command table declines.

**What is deliberately *not* here.** The safety reflexes
(:mod:`genesis.voice.reflex`) and the deterministic command table
(:mod:`genesis.commands`) both sit *in front* of this on both paths and neither
moves. A reflex that could be reached through a ladder rung would be a reflex
that waits on a model, which is the one thing Biological Design says it must
never do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from genesis.orchestrator.answers import Answer

__all__ = ["Ladder", "Rung", "UNREACHED"]

#: What the trader hears when every rung declined and the large tier is not
#: available. The fail-open rule is that the user is never left unanswered, so
#: this is a sentence rather than silence or an exception.
UNREACHED = "I can't reach my reasoning model right now."


@dataclass(frozen=True)
class Rung:
    """An answer, plus which rung produced it.

    ``path`` is not decoration: it is what tells you afterwards whether a
    question cost a hosted round trip or was answered by a calendar lookup, and
    it is the field a test asserts on to prove the typed and spoken routes took
    the *same* rung rather than merely arriving at similar text.
    """

    answer: Answer
    path: str
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def reached(self) -> bool:
        """Did anything actually answer? ``False`` is honest, not an error."""
        return self.path != "unhandled"


@dataclass
class Ladder:
    """The rungs, in priority order. Every one is optional.

    Optional means *a quieter Genesis, not a broken one*: with nothing wired at
    all this still returns a sentence saying so. A missing rung is skipped, and
    the cost of skipping is the next rung down -- which is the whole point of
    ordering them by price.

    Constructed per call by :class:`VoiceLoop` from its own attributes, and
    once (lazily) by the server. It holds no state between calls on purpose:
    the conversation lives in Working Memory, not here.
    """

    #: "be terse" -- a command about the system, not a question about the
    #: market, so it never reaches a model. Top of the ladder for that reason.
    verbosity: Any = None
    #: Calendar and clock. A fact the system already knows.
    answerer: Any = None
    #: Both halves or neither -- a planner with nothing to dispatch to would
    #: only ever decline.
    planner: Any = None
    runner: Any = None
    #: The fail-open path: tools, or the model's own knowledge.
    reasoner: Any = None

    def answer(
        self,
        text: str,
        *,
        context: str = "",
        on_dispatch: Callable[[], None] | None = None,
    ) -> Rung:
        """Walk the ladder. Always returns a Rung; never raises for an answer.

        ``on_dispatch`` fires once, **before** a validated plan runs -- the
        acknowledgement hook. Voice Stack's budget cannot survive agent work
        inside 1.5 s, so the voice path plays an earcon here rather than after,
        and Operating Model §6 makes the same point for the screen: a
        multi-minute job that answers with silence is indistinguishable from a
        hang. The ladder does not know or care which one it is calling.
        """
        fields: dict[str, Any] = {}

        answer = self.verbosity.answer(text) if self.verbosity is not None else None
        path = "verbosity"
        if answer is not None:
            fields["verbosity"] = self.verbosity.level.wire_name

        if answer is None and self.answerer is not None:
            answer = self.answerer.answer(text)
            path = "trivial"

        # Anything the deterministic rungs declined gets one attempt at a task
        # list before the large tier does the work itself. A decline here is
        # normal and cheap -- with no agents registered the planner returns
        # without calling a model at all.
        if answer is None and self.planner is not None and self.runner is not None:
            # Reflex before judgement: what is already stored about the
            # companies named is looked up in code and handed to the planner,
            # so it plans around a fresh read instead of repeating it.
            # The reasoner below reads the same context if planning declines.
            known = self.runner.known(text) if hasattr(self.runner, "known") else ""
            if known:
                context = f"{context}\n\nAlready known (stored findings):\n{known}".strip()
            outcome = self.planner.plan(text, context=context)
            fields["plan"] = outcome.reason
            if outcome.plan is not None:
                fields["plan_tasks"] = len(outcome.plan.tasks)
                path = "planned"
                if on_dispatch is not None:
                    on_dispatch()
                answer = self.runner.run(outcome.plan)

        if self.reasoner is not None:
            self.reasoner.last_error = None
        if answer is None and self.reasoner is not None:
            # Default down, then escalate: the cheap rungs get first refusal,
            # and only what they decline costs a hosted round trip.
            answer = self.reasoner.answer(text, context=context)
            path = "reasoned"

        if answer is None:
            # Say which failure it was. "I can't reach my reasoning model" is
            # the same sentence for a missing key, a spent free-tier quota and
            # a vendor having a bad minute -- and each one sends the operator
            # somewhere different. The reason is already in hand; withholding
            # it is what made the surface look dead.
            reason = getattr(self.reasoner, "last_error", None)
            if reason:
                fields["reason"] = reason
            return Rung(
                Answer(f"{UNREACHED} {reason}" if reason else UNREACHED, "unhandled"),
                "unhandled",
                fields,
            )
        return Rung(answer, path, fields)
