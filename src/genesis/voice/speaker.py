# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""The mouth: streaming speech with barge-in and a fallback chain.

This is where Voice Stack's degradation table becomes code:

===========================  ====================================================
ElevenLabs TTS down          fall back to local TTS; voice changes, system
                             doesn't stop
Anything else                never hard-fail the whole system on a voice fault
===========================  ====================================================

:class:`Speaker` owns the chain and the interrupt. Three properties it must
hold, each of which is a spec line rather than a preference:

1. **Speech starts before it finishes generating.** Chunks go to the player as
   they arrive off the socket, so time-to-first-syllable is the API's first
   chunk (~210 ms warm), not the length of the sentence.
2. **:meth:`stop` returns immediately** and silences within one device block.
   It is safe to call from any thread, including from the audio callback's
   observer, and it never waits on the network -- the generator is abandoned,
   not drained.
3. **A failing voice degrades, never raises.** :meth:`say` returns a
   :class:`SpeechResult` saying what happened. A caller that crashes because
   TTS 402'd would take the daemon with it, and Voice Stack is explicit that
   voice is a surface, not the spine.

The fallback order is deliberate: the configured voice, then a premade voice
on the same account (which covers the common free-plan 402 without a network
change), then local Piper, then silence-with-a-log.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum

from genesis.errors import DegradedError
from genesis.voice.echo import EchoFilter
from genesis.voice.player import Player
from genesis.voice.speech import speakable
from genesis.voice.tts import FALLBACK_VOICE_ID, TTSBackend

__all__ = ["Speaker", "SpeechOutcome", "SpeechResult"]


class SpeechOutcome(str, Enum):
    SPOKEN = "spoken"
    """Said in full, on the configured voice."""

    DEGRADED = "degraded"
    """Said, but on a fallback voice. Worth logging, not worth announcing."""

    INTERRUPTED = "interrupted"
    """Cut off by barge-in or an explicit stop. Not a failure."""

    SILENT = "silent"
    """Nothing was said. Every backend failed."""


@dataclass(frozen=True)
class SpeechResult:
    outcome: SpeechOutcome
    text: str
    """The rendered text -- what was actually sent to the voice."""
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in (SpeechOutcome.SPOKEN, SpeechOutcome.DEGRADED)


class Speaker:
    """Speak text, interruptibly, with a fallback chain.

    ``backends`` is tried in order. The echo filter is fed the *rendered* text
    rather than the input, because what the microphone hears is
    "N-V-D-A long from one twenty-one oh six", not "NVDA long from 121.06" --
    feeding it the raw form silently defeats echo detection, which is the kind
    of bug that only shows up as the assistant answering itself in a live room.
    """

    def __init__(
        self,
        backends: list[TTSBackend],
        player: Player,
        *,
        echo: EchoFilter | None = None,
        on_event=None,
    ) -> None:
        if not backends:
            raise ValueError("Speaker needs at least one TTS backend")
        self._backends = backends
        self._player = player
        self.echo = echo or EchoFilter()
        self._on_event = on_event
        self._interrupt = threading.Event()
        self._lock = threading.Lock()

    # -- speaking ----------------------------------------------------------

    def say(self, text: str, *, trace_id: str | None = None) -> SpeechResult:
        """Speak ``text``. Blocks until spoken or interrupted.

        Never raises on a voice fault -- inspect the returned outcome.
        """
        rendered = speakable(text)
        if not rendered.strip():
            return SpeechResult(SpeechOutcome.SILENT, rendered, "nothing to say")

        # Record before the first sample plays. If the mic hears the opening
        # words while we are still deciding, the filter must already know them.
        self.echo.note_spoken(rendered)
        self._interrupt.clear()

        last_detail: str | None = None
        for index, backend in enumerate(self._backends):
            try:
                spoke_any = self._pump(backend.stream(text))
            except DegradedError as exc:
                last_detail = exc.reason
                self._emit("voice.backend_failed", trace_id, backend=type(backend).__name__, reason=exc.reason)
                continue

            if self._interrupt.is_set():
                return SpeechResult(SpeechOutcome.INTERRUPTED, rendered, last_detail)
            if spoke_any:
                outcome = SpeechOutcome.SPOKEN if index == 0 else SpeechOutcome.DEGRADED
                return SpeechResult(outcome, rendered, last_detail)
            last_detail = last_detail or "backend produced no audio"

        self._emit("voice.silent", trace_id, reason=last_detail)
        return SpeechResult(SpeechOutcome.SILENT, rendered, last_detail)

    def _pump(self, chunks: Iterator[bytes]) -> bool:
        """Feed a chunk stream to the player, abandoning it on interrupt.

        The generator is closed rather than exhausted: on barge-in there may be
        seconds of audio still coming, and draining it would hold the socket
        and delay the next utterance.
        """
        spoke_any = False
        try:
            for chunk in chunks:
                if self._interrupt.is_set():
                    return spoke_any
                if chunk:
                    self._player.feed(chunk)
                    spoke_any = True
        finally:
            close = getattr(chunks, "close", None)
            if close is not None:
                close()
        if spoke_any:
            # Wait for the queue to drain so callers can sequence speech, but
            # stay responsive to an interrupt while doing it.
            #
            # The deadline is not optional. A player that never drains -- a
            # misbehaving device, a sink with no consumer -- would otherwise
            # hang the voice loop permanently, and Voice Stack is explicit that
            # nothing may hard-fail the system on a voice fault. Bound it by the
            # audio actually queued, then give up and move on rather than block
            # the next utterance forever.
            deadline = time.monotonic() + self._drain_timeout()
            while not self._player.wait(timeout=0.05):
                if self._interrupt.is_set() or time.monotonic() > deadline:
                    break
        return spoke_any

    def _drain_timeout(self) -> float:
        """How long the queued audio could possibly take, plus slack."""
        rate = getattr(self._player, "sample_rate", 24_000) or 24_000
        seconds = self._player.queued_bytes / 2 / rate
        return max(5.0, seconds * 2 + 2.0)

    # -- interrupting ------------------------------------------------------

    def stop(self) -> None:
        """Cut speech now. Safe from any thread, returns immediately."""
        self._interrupt.set()
        self._player.stop()

    @property
    def speaking(self) -> bool:
        return self._player.speaking.is_set()

    def _emit(self, event: str, trace_id: str | None, **fields: object) -> None:
        if self._on_event is not None:
            self._on_event(event, trace_id, fields)


def default_backends(
    voice_id: str,
    *,
    api_key: str | None = None,
    piper_model: str | None = None,
    sample_rate: int = 24_000,
) -> list[TTSBackend]:
    """Build the standard chain: configured voice, premade voice, local Piper.

    Missing pieces are skipped rather than raising: no API key means the chain
    is local-only, which is a degraded system rather than a broken one.
    """
    from genesis.voice.tts import ElevenLabsTTS, PiperTTS, TTSVoice

    backends: list[TTSBackend] = []
    try:
        backends.append(ElevenLabsTTS(TTSVoice(voice_id=voice_id), api_key=api_key, sample_rate=sample_rate))
        if voice_id != FALLBACK_VOICE_ID:
            backends.append(
                ElevenLabsTTS(TTSVoice(voice_id=FALLBACK_VOICE_ID), api_key=api_key, sample_rate=sample_rate)
            )
    except DegradedError:
        pass
    if piper_model:
        backends.append(PiperTTS(piper_model))
    return backends
