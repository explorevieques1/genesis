# Spec: Genesis Markdown/60-UI/Voice UX.md
"""When Genesis speaks without being asked.

Voice UX states the design in one line -- *"Restraint is the whole design. An
assistant that talks too much gets muted, and a muted assistant is worthless"* --
and then gives a three-way table. This module is that table, as code, because
a policy that lives only in prose gets re-decided by whoever writes the next
component, and the failure mode is cumulative: each addition is individually
defensible and the system ends up talking constantly.

Three rules:

**Always speaks.** Money and safety. An invalidation on an open position, a
risk breach, a fill in ``auto-within-limits``, a prop-firm warning, a
reconciliation failure or halt, an execution-path component down. These do not
consult presence, because *"nobody was listening"* is not a reason to swallow a
risk breach -- it is a reason it also went to the [[Dashboard]] and a
notification.

**Speaks if you are present.** A new high-confidence idea, a level touched, a
scheduled brief. Present means recent voice activity, which
:class:`Presence` tracks from the loop rather than inferring from a screen.

**Never speaks.** Routine agent completions, level approaches, health issues
that do not affect execution, research without an actionable conclusion. These
are dashboard-only, and this is the rule most likely to be violated by
accident: every agent that finishes something wants to tell you about it.

**Work you asked for out loud is not an unprompted event.** A plan dispatched
from an utterance answers to the person who asked, whether it took two seconds
or four minutes, and :data:`REQUESTED` says so explicitly rather than leaving
the distinction to whoever reads the "routine agent completions" row next.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

__all__ = ["Presence", "SpeechPolicy", "Urgency", "REQUESTED"]


class Urgency(str, Enum):
    """How an event earns the voice."""

    ALWAYS = "always"
    IF_PRESENT = "if-present"
    NEVER = "never"


#: The event kind for "the thing you asked for has finished". Always spoken:
#: you asked, so an answer is owed regardless of presence.
REQUESTED = "plan.done"


#: Voice UX's table, verbatim, keyed by [[Event Schema]]-style event kinds.
POLICY: dict[str, Urgency] = {
    # Always. Money and safety.
    REQUESTED: Urgency.ALWAYS,
    "position.invalidated": Urgency.ALWAYS,
    "risk.breach": Urgency.ALWAYS,
    "risk.approaching_limit": Urgency.ALWAYS,
    "order.filled": Urgency.ALWAYS,
    "propfirm.warning": Urgency.ALWAYS,
    "reconciliation.failed": Urgency.ALWAYS,
    "system.halt": Urgency.ALWAYS,
    "execution.component_down": Urgency.ALWAYS,
    # If you are in the room.
    "idea.high_confidence": Urgency.IF_PRESENT,
    "level.touched": Urgency.IF_PRESENT,
    "brief.ready": Urgency.IF_PRESENT,
    "recap.ready": Urgency.IF_PRESENT,
    # Dashboard only.
    "task.done": Urgency.NEVER,
    "agent.completed": Urgency.NEVER,
    "level.approaching": Urgency.NEVER,
    "agent.degraded": Urgency.NEVER,
    "research.finding": Urgency.NEVER,
}

#: Anything not in the table. Silence is the safe default here in a way it
#: almost never is elsewhere: an unspoken event is still on the dashboard and
#: still in the [[Episodic Log]], so the cost of staying quiet is a delay,
#: while the cost of speaking is the operator muting the system.
UNKNOWN_EVENT = Urgency.NEVER


@dataclass
class Presence:
    """Whether anyone is in the room, from recent voice activity.

    Deliberately not a camera, a calendar or an idle timer. The signal Voice UX
    names is *"recent voice activity"*, and the loop already knows about every
    utterance it hears -- including ambient speech, which is the strongest
    evidence of presence precisely because it was not addressed to Genesis.
    """

    window_sec: float = 300.0
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    _last_activity: float | None = field(default=None, repr=False)

    def heard_something(self) -> None:
        self._last_activity = self._clock()

    @property
    def present(self) -> bool:
        if self._last_activity is None:
            return False
        return (self._clock() - self._last_activity) <= self.window_sec

    @property
    def seconds_since_activity(self) -> float | None:
        if self._last_activity is None:
            return None
        return self._clock() - self._last_activity


class SpeechPolicy:
    """Decides whether an event gets spoken.

    One method, one boolean, no side effects -- so the same decision can be
    asserted in a test, shown on the [[Dashboard]], and explained out loud
    without three implementations drifting apart.
    """

    def __init__(self, presence: Presence | None = None, *, muted: bool = False) -> None:
        self.presence = presence or Presence()
        #: Set while the operator has asked for quiet. Never suppresses an
        #: ``ALWAYS`` event: muting the voice must not be a way to silence a
        #: risk breach, which would make it a safety control by accident.
        self.muted = muted

    def urgency(self, event_kind: str) -> Urgency:
        return POLICY.get(event_kind, UNKNOWN_EVENT)

    def should_speak(self, event_kind: str) -> bool:
        urgency = self.urgency(event_kind)
        if urgency is Urgency.ALWAYS:
            return True
        if self.muted or urgency is Urgency.NEVER:
            return False
        return self.presence.present

    def explain(self, event_kind: str) -> str:
        """Why the decision went the way it did. For the trace and the UI."""
        urgency = self.urgency(event_kind)
        if urgency is Urgency.ALWAYS:
            return f"{event_kind}: always spoken"
        if urgency is Urgency.NEVER:
            return f"{event_kind}: dashboard only"
        if self.muted:
            return f"{event_kind}: muted"
        return (
            f"{event_kind}: spoken (you're here)"
            if self.presence.present
            else f"{event_kind}: held, no recent voice activity"
        )
