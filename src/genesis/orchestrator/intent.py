# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""Deciding whether you were talking to it.

Orchestrator.md gives five classes -- ``directed``, ``ambient``, ``follow-up``,
``stop``, ``echo`` -- and assigns the job to the nano tier. This module runs
that decision **deterministically first and reaches for a model last**, and the
reason is measurement rather than taste.

On this machine the nano model (``qwen2.5:3b``, CPU) takes 1.3-6.5 s to emit a
one-word class, against a budget of 100 ms, and answers "followup" to
everything including a plainly wake-worded question. A tier that is 13-65x over
budget and wrong is not a tier; using it would break the *"wake -> first spoken
word in under 1.5 s"* criterion on its own.

It is also unnecessary, which is the more interesting half. Biological Design's
reflex arc argues that most things reached for a model are reflexes, and intent
classification is largely one:

============================  ==========================  ==========
Question                      How it is answered          Cost
============================  ==========================  ==========
Is this a kill phrase?        table lookup                ~0 ms
Is this us, echoing?          token overlap               ~0 ms
Is the wake word present?     substring                   ~0 ms
Is a follow-up window open?   a timestamp comparison      ~0 ms
Anything else                 **ambient -- do nothing**   ~0 ms
============================  ==========================  ==========

The last row is the safety property. The residue after the deterministic checks
is *speech in a room that was not addressed to the system*, and the correct
action there is to buffer and stay silent. Uncertainty resolves to inaction,
which is the fail-closed direction: a missed request costs you repeating
yourself, while a false ``directed`` dispatches agents at conversation.

An optional ``judge`` can be supplied to adjudicate the residue for installs
with a genuinely fast nano tier. It is **off by default**, it may only ever
promote ``ambient`` to ``directed`` (never demote, never reach a reflex), and
it is skipped entirely when a reflex, an echo, a wake word, or an open window
already decided -- so no model can ever sit between you and the kill switch.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from genesis.voice.echo import EchoFilter
from genesis.voice.reflex import Reflex, match_reflex, normalise

__all__ = ["Intent", "IntentClassifier", "IntentResult"]


class Intent(str, Enum):
    DIRECTED = "directed"
    AMBIENT = "ambient"
    FOLLOW_UP = "follow-up"
    STOP = "stop"
    ECHO = "echo"


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    text: str
    #: Which rule decided. Logged on every utterance so that "why did it do
    #: that" is answerable from the trace rather than by guesswork.
    path: str
    reflex: Reflex | None = None
    latency_ms: float = 0.0

    @property
    def actionable(self) -> bool:
        """True when the orchestrator should plan and dispatch."""
        return self.intent in (Intent.DIRECTED, Intent.FOLLOW_UP)


class IntentClassifier:
    """Classify an utterance. Deterministic unless explicitly told otherwise."""

    def __init__(
        self,
        *,
        wake_word: str = "genesis",
        echo: EchoFilter | None = None,
        follow_up_sec: float = 4.0,
        follow_up_max_words: int = 6,
        judge: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.wake_word = wake_word
        self.echo = echo or EchoFilter()
        self.follow_up_sec = follow_up_sec
        self.follow_up_max_words = follow_up_max_words
        self._judge = judge
        self._window_until: float = 0.0

    # -- the window --------------------------------------------------------

    def open_follow_up(self, *, seconds: float | None = None) -> None:
        """Open the no-wake-word window after Genesis replies.

        Orchestrator: *"Extend the window if the reply asked a question."*
        Callers pass a longer ``seconds`` for that case.
        """
        self._window_until = time.monotonic() + (self.follow_up_sec if seconds is None else seconds)

    def close_follow_up(self) -> None:
        self._window_until = 0.0

    @property
    def follow_up_open(self) -> bool:
        return time.monotonic() < self._window_until

    # -- classification ----------------------------------------------------

    def classify(self, text: str, *, ambient_context: str = "") -> IntentResult:
        """Classify one transcript. Never raises; never blocks on the network
        unless a ``judge`` was supplied, and then only for the residue."""
        start = time.monotonic()

        def done(intent: Intent, path: str, reflex: Reflex | None = None) -> IntentResult:
            return IntentResult(
                intent=intent,
                text=text,
                path=path,
                reflex=reflex,
                latency_ms=(time.monotonic() - start) * 1000,
            )

        if not normalise(text):
            return done(Intent.AMBIENT, "empty")

        # 1. Reflexes first -- before echo, before everything. Voice Stack is
        #    explicit that "stop" must never be swallowed as echo, and the only
        #    way to guarantee that is to check for it before the echo filter
        #    runs at all.
        if (hit := match_reflex(text, wake_word=self.wake_word)) is not None:
            return done(Intent.STOP, "reflex", hit.reflex)

        # 2. Us, coming back through the microphone.
        if self.echo.is_echo(text):
            return done(Intent.ECHO, "echo")

        # 3. Addressed by name, anywhere in the sentence.
        if self._has_wake_word(text):
            self.close_follow_up()
            return done(Intent.DIRECTED, "wake")

        # 4. Inside the window we opened after speaking -- but only for speech
        #    that plausibly continues the exchange.
        #
        #    A bare time window is not enough, and testing showed why: Genesis
        #    answers, you turn to a colleague and keep talking, and the next
        #    two sentences land inside the window and get answered. That
        #    violates the Voice UX criterion that ambient conversation produces
        #    zero unprompted speech, which outranks the convenience of the
        #    window.
        #
        #    The discriminator is length. Real follow-ups are short -- "and
        #    what about SPY?" (4), "give me the full version" (5), "what's the
        #    stop?" (4), "confirm that" (2), "never mind" (2). Continued
        #    conversation with another person is not: the sentence that broke
        #    this in testing was eight words. Six covers every follow-up the
        #    notes give as an example, with a word of headroom. This is a heuristic and it will occasionally cost
        #    you a long follow-up, which costs one repetition with the wake
        #    word; the failure it prevents costs an assistant that talks over
        #    your meetings.
        if self.follow_up_open:
            if len(normalise(text).split()) <= self.follow_up_max_words:
                return done(Intent.FOLLOW_UP, "window")
            return done(Intent.AMBIENT, "window-too-long")

        # 5. Optional, off by default, may only promote.
        if self._judge is not None:
            try:
                if self._judge(text, ambient_context):
                    return done(Intent.DIRECTED, "judge")
            except Exception:  # noqa: BLE001
                # A judge that errors leaves the utterance ambient. Failing
                # towards inaction is the whole point of where it sits.
                return done(Intent.AMBIENT, "judge-failed")

        # 6. Everything else is the room talking. Buffer it; do nothing.
        return done(Intent.AMBIENT, "default")

    def _has_wake_word(self, text: str) -> bool:
        import re

        norm = normalise(text)
        wake = normalise(self.wake_word)
        return bool(wake) and re.search(rf"(?<!\w){re.escape(wake)}(?!\w)", norm) is not None
