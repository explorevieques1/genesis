# Spec: Genesis Markdown/40-Memory/Working Memory.md
"""What the system is thinking about right now.

Working Memory.md: *"Fast, small, and disposable."* It sits in the hot path of
every utterance, so everything here is in-process and bounded. Nothing touches
disk on the read path.

Three rules from the note are enforced as code rather than trusted to callers:

**Ambient speech is buffered but never acted on, and never persisted.** The
ambient buffer is what lets you say "Genesis, what do you think?" and have it
know what "this" is. It is also a microphone recording of a private
conversation, so :meth:`ambient_context` is read-only and
:meth:`WorkingMemory.snapshot` -- the thing that gets summarised to disk --
excludes it unless a directed utterance has claimed it.

**Pending confirmations expire on restart, never restore.** Working memory is
in-process, so this is free; the note calls it a safety property and
:meth:`restore` exists to make the intent explicit rather than incidental. A
resurrected trade confirmation is a trade you agreed to at a price that no
longer exists, while you were not in the room.

**Exceeding the cap triggers summarisation, not growth.** Turns roll off
oldest-first into a caller-supplied sink (the Episodic Log). Rolloff is
summarisation, not deletion.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

__all__ = [
    "AmbientBuffer",
    "PendingConfirmation",
    "Turn",
    "WorkingMemory",
]

Speaker = Literal["user", "genesis"]


@dataclass(frozen=True)
class Turn:
    """One exchange. Full text -- turns are few and bounded."""

    speaker: Speaker
    text: str
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trace_id: str | None = None

    def approx_tokens(self) -> int:
        """Cheap token estimate. Four characters per token is close enough for
        a cap whose purpose is to stop unbounded growth, and it costs nothing --
        a real tokeniser in the hot path would be the wrong trade."""
        return max(1, len(self.text) // 4)


@dataclass(frozen=True)
class PendingConfirmation:
    """An order proposal awaiting a spoken yes.

    ``expires_at`` is monotonic, not wall-clock: a confirmation must not be
    extendable by an NTP correction or a DST jump.
    """

    proposal_id: str
    symbol: str
    spoken: str
    expires_at: float

    def expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.monotonic()) >= self.expires_at


class AmbientBuffer:
    """A rolling window of speech that was not addressed to Genesis.

    Bounded by *time* rather than by turn count, because the thing being
    modelled is "the last thirty seconds of the room", not "the last N things
    anyone said".
    """

    def __init__(self, window_sec: float = 30.0, max_items: int = 40) -> None:
        self.window_sec = window_sec
        self.max_items = max_items
        self._items: deque[tuple[float, str]] = deque(maxlen=max_items)
        self._lock = threading.Lock()

    def add(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._items.append((time.monotonic(), text))

    def context(self) -> str:
        """The buffered speech still inside the window, oldest first."""
        cutoff = time.monotonic() - self.window_sec
        with self._lock:
            return " ".join(text for at, text in self._items if at >= cutoff)

    def clear(self) -> None:
        """Called on wake, after the relevant portion is handed to intent."""
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        cutoff = time.monotonic() - self.window_sec
        with self._lock:
            return sum(1 for at, _ in self._items if at >= cutoff)


class WorkingMemory:
    """The orchestrator's live context.

    ``on_rolloff`` receives turns as they age out, for summarisation into the
    Episodic Log. If it is ``None`` turns are dropped, which is correct for
    tests and wrong for production -- the daemon wires it.
    """

    def __init__(
        self,
        *,
        max_turns: int = 20,
        max_tokens: int = 2000,
        ambient_window_sec: float = 30.0,
        on_rolloff: Callable[[list[Turn]], None] | None = None,
    ) -> None:
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.ambient = AmbientBuffer(ambient_window_sec)
        self._turns: deque[Turn] = deque()
        self._on_rolloff = on_rolloff
        self._lock = threading.RLock()

        #: What is on the Dashboard, the last chart shown, the symbol under
        #: discussion. Small and free-form by design -- pinning a schema here
        #: would mean editing this module every time the UI grows a surface.
        self.active_context: dict[str, Any] = {}
        self._plan: dict[str, Any] | None = None
        self._pending: dict[str, PendingConfirmation] = {}
        #: Task id -> spoken_summary. Orchestrator Tools is emphatic that the
        #: orchestrator moves ids and summaries, never rows, so this holds
        #: strings and nothing else.
        self._results: dict[str, str] = {}

    # -- turns -------------------------------------------------------------

    def add_turn(self, speaker: Speaker, text: str, *, trace_id: str | None = None) -> Turn:
        turn = Turn(speaker=speaker, text=text, trace_id=trace_id)
        with self._lock:
            self._turns.append(turn)
            self._enforce_caps()
        return turn

    def turns(self) -> list[Turn]:
        with self._lock:
            return list(self._turns)

    def transcript(self) -> str:
        """The conversation as text, for a prompt."""
        with self._lock:
            return "\n".join(f"{t.speaker}: {t.text}" for t in self._turns)

    def token_estimate(self) -> int:
        with self._lock:
            return sum(t.approx_tokens() for t in self._turns)

    def _enforce_caps(self) -> None:
        """Roll off oldest-first until both caps hold.

        Both caps, not either: a burst of agent results can blow the token cap
        long before the turn count, and a long idle conversation does the
        reverse.
        """
        rolled: list[Turn] = []
        while self._turns and (
            len(self._turns) > self.max_turns or self.token_estimate_unlocked() > self.max_tokens
        ):
            rolled.append(self._turns.popleft())
        if rolled and self._on_rolloff is not None:
            self._on_rolloff(rolled)

    def token_estimate_unlocked(self) -> int:
        return sum(t.approx_tokens() for t in self._turns)

    # -- plan and results --------------------------------------------------

    def set_plan(self, plan: dict[str, Any] | None) -> None:
        with self._lock:
            self._plan = plan

    @property
    def plan(self) -> dict[str, Any] | None:
        with self._lock:
            return self._plan

    def note_result(self, task_id: str, spoken_summary: str) -> None:
        """Remember an agent's spoken summary so a follow-up need not re-run it."""
        with self._lock:
            self._results[task_id] = spoken_summary
            # Bounded like everything else here.
            while len(self._results) > 20:
                self._results.pop(next(iter(self._results)))

    def result_summary(self, task_id: str) -> str | None:
        with self._lock:
            return self._results.get(task_id)

    # -- confirmations -----------------------------------------------------

    def add_confirmation(self, confirmation: PendingConfirmation) -> None:
        with self._lock:
            self._pending[confirmation.proposal_id] = confirmation

    def take_confirmation(self, proposal_id: str) -> PendingConfirmation | None:
        """Claim a confirmation, removing it. ``None`` if absent or expired.

        Single-use by construction: Voice UX says *"Never asks twice for the
        same proposal"*, and a confirmation that could be claimed twice is a
        double order waiting for a stutter.
        """
        with self._lock:
            found = self._pending.pop(proposal_id, None)
        if found is None or found.expired():
            return None
        return found

    def pending_confirmations(self) -> list[PendingConfirmation]:
        with self._lock:
            live = [c for c in self._pending.values() if not c.expired()]
            self._pending = {c.proposal_id: c for c in live}
            return live

    def expire_confirmations(self) -> None:
        with self._lock:
            self._pending.clear()

    # -- lifecycle ---------------------------------------------------------

    def restore(self, summary: str | None = None) -> None:
        """Restart behaviour, per the note.

        Conversation comes back as a *summary*, not verbatim. Pending
        confirmations are dropped. The task list is not restored here at all --
        it comes from the Task Bus, which is the durable thing.
        """
        with self._lock:
            self._turns.clear()
            self._results.clear()
            self._pending.clear()
            self._plan = None
            self.ambient.clear()
            if summary:
                self._turns.append(Turn(speaker="genesis", text=summary))

    def snapshot(self) -> dict[str, Any]:
        """Serialisable view, for the Dashboard and the Episodic Log.

        Excludes the ambient buffer. Conversation you did not address to the
        system does not end up on disk.
        """
        with self._lock:
            return {
                "turns": [
                    {"speaker": t.speaker, "text": t.text, "at": t.at.isoformat(), "trace_id": t.trace_id}
                    for t in self._turns
                ],
                "active_context": dict(self.active_context),
                "plan": self._plan,
                "pending_confirmations": [c.proposal_id for c in self.pending_confirmations()],
                "token_estimate": self.token_estimate_unlocked(),
            }
