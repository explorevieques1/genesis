# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""The wake gate -- the boundary audio may not cross uninvited.

Voice Stack states it as a hard property, not a feature:

    Wake | on-device keyword ("Genesis") | **no audio leaves until this fires**

and the privacy note explains what it is protecting: Genesis diverges from
jarvis's offline-first rule by sending voice to a cloud API, and *"audio leaves
only after the local wake gate fires"* is the line it holds in exchange.

A property stated in a note is a property nobody enforces. So the gate is an
**object that owns the audio**, and the only way to get bytes out of it is
:meth:`WakeGate.take`, which returns ``None`` until a local detector has fired.
There is no code path that hands the ring buffer to Scribe directly, which
means the invariant cannot be violated by someone wiring the pipeline wrong
later -- the same reasoning that puts ``propose_order``/``place_approved``
behind a token instead of documenting "always call the risk engine first".

The detector runs a **local** model. That is the entire point; a cloud
transcriber deciding whether the wake word was present would have to receive
the audio to decide, which is the thing being prevented.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from genesis.voice.reflex import normalise

__all__ = ["LocalWhisperWake", "WakeDetector", "WakeGate", "WakeHit"]


@dataclass(frozen=True)
class WakeHit:
    """A local detection. ``text`` is the locally-transcribed utterance."""

    text: str
    latency_ms: float


class WakeDetector(Protocol):
    def detect(self, pcm: bytes, sample_rate: int) -> WakeHit | None: ...


class LocalWhisperWake:
    """Wake detection by local transcription (faster-whisper).

    Chosen over a dedicated keyword spotter for a specific reason: Voice Stack
    requires the wake word to be recognised **anywhere in a sentence**, and to
    hand *"the whole surrounding utterance"* to intent classification rather
    than only what followed the wake word. A keyword spotter emits a timestamp,
    not a transcript, so it satisfies the first requirement and not the second
    -- it would still need a transcriber behind it to recover the sentence.

    Transcribing locally gets both at once, and the transcript it produces is
    reused as the utterance, so the cloud STT call becomes an accuracy upgrade
    rather than a dependency. When the network is down this path alone still
    works, which is what Voice Stack's degradation table asks for.

    ``tiny.en`` with int8 quantisation is the default: on CPU it is fast enough
    for a gate and its accuracy on a two-word wake phrase is not the binding
    constraint. A machine with a GPU should use ``base.en``.
    """

    def __init__(
        self,
        wake_word: str = "genesis",
        *,
        model_size: str = "tiny.en",
        device: str = "cpu",
        compute_type: str = "int8",
        aliases: tuple[str, ...] = ("genesis", "genesys", "genesus", "jenesis", "genisis"),
    ) -> None:
        self.wake_word = wake_word
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        # Whisper on a short clip mishears a proper noun in predictable ways,
        # and a wake gate that needs perfect spelling is a wake gate that makes
        # you say your assistant's name three times. Aliases are cheap; a
        # missed wake is the failure people actually notice.
        self.aliases = tuple(normalise(a) for a in aliases)
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model. Slow -- call at startup, never on the first wake."""
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self._model_size, device=self._device, compute_type=self._compute_type)

    def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        """Locally transcribe int16 mono PCM. No audio leaves the machine."""
        import numpy as np

        self.load()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return ""
        with self._lock:
            segments, _ = self._model.transcribe(  # type: ignore[union-attr]
                audio,
                language="en",
                beam_size=1,          # greedy: this is a gate, not a transcript
                vad_filter=False,     # our own VAD already segmented it
                condition_on_previous_text=False,
            )
            return " ".join(s.text for s in segments).strip()

    def detect(self, pcm: bytes, sample_rate: int) -> WakeHit | None:
        import time

        start = time.monotonic()
        text = self.transcribe(pcm, sample_rate)
        if not text:
            return None
        norm = normalise(text)
        tokens = set(norm.split())
        if tokens & set(self.aliases):
            return WakeHit(text=text, latency_ms=(time.monotonic() - start) * 1000)
        return None


class WakeGate:
    """Holds captured audio until a local detector says it was addressed.

    ``take`` is the only exit. It returns the audio *and* the local transcript,
    so the caller never needs to reach around the gate to the ring buffer.
    """

    def __init__(self, detector: WakeDetector, *, sample_rate: int = 16_000) -> None:
        self._detector = detector
        self._sample_rate = sample_rate
        self._held: bytes | None = None
        self._hit: WakeHit | None = None
        self._lock = threading.Lock()
        #: Number of utterances examined and discarded without firing. The
        #: Voice UX criterion "ten minutes of ambient conversation produces
        #: zero actions" is measured from this.
        self.rejected = 0

    def examine(self, pcm: bytes) -> tuple[bool, str]:
        """Locally transcribe and decide, returning the transcript either way.

        The transcript of *un-addressed* speech is what feeds Working Memory's
        ambient buffer -- the thing that lets "Genesis, what do you think?"
        know what "this" refers to. It is produced locally and, per Working
        Memory.md, never persisted: it exists in memory for thirty seconds and
        is gone.

        Returning it here rather than transcribing twice matters on a CPU where
        each pass costs about a second.
        """
        detector = self._detector
        transcribe = getattr(detector, "transcribe", None)
        if transcribe is None:
            return self.offer(pcm), ""
        text = transcribe(pcm, self._sample_rate)
        import time

        norm = normalise(text)
        aliases = set(getattr(detector, "aliases", ()))
        if norm and (set(norm.split()) & aliases):
            with self._lock:
                self._held = pcm
                self._hit = WakeHit(text=text, latency_ms=0.0)
            return True, text
        with self._lock:
            self.rejected += 1
        return False, text

    def offer(self, pcm: bytes) -> bool:
        """Submit a completed utterance for local examination.

        Returns True if it woke the system. Audio that does not wake it is
        dropped here and never stored, buffered, or transmitted.
        """
        hit = self._detector.detect(pcm, self._sample_rate)
        if hit is None:
            with self._lock:
                self.rejected += 1
            return False
        with self._lock:
            self._held = pcm
            self._hit = hit
        return True

    def take(self) -> tuple[bytes, WakeHit] | None:
        """Claim the woken audio. ``None`` if the gate has not fired.

        Single-use: taking clears the gate, so the same audio cannot be sent
        twice by two callers racing.
        """
        with self._lock:
            if self._held is None or self._hit is None:
                return None
            audio, hit = self._held, self._hit
            self._held = None
            self._hit = None
            return audio, hit

    @property
    def open(self) -> bool:
        with self._lock:
            return self._held is not None
