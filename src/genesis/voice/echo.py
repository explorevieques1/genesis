# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Not hearing yourself.

An always-on mic in the same room as the speakers hears everything Genesis
says. Without a filter the system answers its own answers, which is both
absurd and, in a trading loop, expensive.

Voice Stack names the exact trap, having watched it happen in the reference
implementation:

    Guard: echo detection must run *before* barge-in, or the assistant
    interrupts itself. (Known failure mode: "stop" during speech sometimes
    filtered as echo. Fix: exact-match echo filtering, but always honour
    ``stop`` keywords even if they look like echo.)

That is the whole design, and the second clause matters more than the first.
An over-eager echo filter is not a cosmetic bug: it is a filter that swallows
the one word whose entire purpose is to work when everything else is talking
over you. So :func:`is_echo` refuses to classify anything containing a stop
word as echo -- a false barge-in costs a sentence, a swallowed "stop" costs
trust in the interrupt.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from genesis.voice.reflex import STOP_WORDS, normalise

__all__ = ["EchoFilter"]


@dataclass
class _Spoken:
    text: str
    at: float


@dataclass
class EchoFilter:
    """Remembers what Genesis just said, so the mic can discount it.

    ``window_sec`` bounds how long a phrase stays suspicious. It should exceed
    the longest utterance plus the STT lag, and no more -- an unbounded memory
    would eventually filter a legitimate repetition of an old sentence.
    """

    window_sec: float = 20.0
    #: Token overlap above which heard text counts as our own. Exact match is
    #: too brittle: STT drops filler words and mangles the tail of a clipped
    #: sentence, so a strict equality check catches almost no real echo.
    threshold: float = 0.75
    _spoken: deque[_Spoken] = field(default_factory=deque)

    def note_spoken(self, text: str) -> None:
        """Record something Genesis said. Call this as it goes to the player."""
        norm = normalise(text)
        if norm:
            self._spoken.append(_Spoken(norm, time.monotonic()))
        self._expire()

    def is_echo(self, heard: str) -> bool:
        """True if ``heard`` is Genesis hearing itself.

        A stop word in the transcript makes this False unconditionally, even
        when the rest of the sentence is a verbatim match -- see the module
        docstring.
        """
        norm = normalise(heard)
        if not norm:
            return False

        heard_tokens = set(norm.split())
        if heard_tokens & STOP_WORDS or any(" " in w and w in norm for w in STOP_WORDS):
            return False

        self._expire()
        for spoken in self._spoken:
            if self._overlap(norm, spoken.text) >= self.threshold:
                return True
        return False

    def clear(self) -> None:
        self._spoken.clear()

    def _expire(self) -> None:
        cutoff = time.monotonic() - self.window_sec
        while self._spoken and self._spoken[0].at < cutoff:
            self._spoken.popleft()

    @staticmethod
    def _overlap(heard: str, spoken: str) -> float:
        """Fraction of the heard tokens that appear in what we said.

        Asymmetric on purpose. A short fragment of a long sentence -- which is
        what a mic picks up through room noise -- scores high, while a long new
        sentence that happens to share a few words with an old one scores low.
        Symmetric similarity would fail the first case, which is the common one.
        """
        heard_tokens = heard.split()
        if not heard_tokens:
            return 0.0
        spoken_tokens = set(spoken.split())
        hits = sum(1 for t in heard_tokens if t in spoken_tokens)
        return hits / len(heard_tokens)
