# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Voice activity detection -- the cheap gate before anything expensive.

Voice Stack: *"local (webrtcvad / silero) -- cheap gate before anything
expensive."* Its whole job is to answer "is anyone talking" for near-zero cost,
so that wake detection, STT and the network are only ever asked about audio
that contains speech.

This implementation is energy-based with hysteresis, deliberately. It has no
model, no dependency beyond numpy, and runs in microseconds, which means it can
sit on the audio callback where a neural VAD cannot. It is less discriminating
than silero against non-speech noise -- but a false positive here costs one
wake-detector call on a local model, not an action and not a network round
trip, so the asymmetry is comfortable.

Hysteresis is the part that matters. A bare threshold flickers on every pause
between words and would chop utterances into fragments; separate start and stop
thresholds plus a hangover keep a sentence together across its own gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["SpeechEvent", "Vad", "rms"]


def rms(frame: bytes) -> float:
    """Root-mean-square amplitude of an int16 frame, normalised to 0-1."""
    import numpy as np

    if not frame:
        return 0.0
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)) / 32768.0)


class SpeechEvent(str, Enum):
    NONE = "none"
    STARTED = "started"
    """This frame began an utterance."""
    CONTINUING = "continuing"
    ENDED = "ended"
    """This frame closed an utterance -- the hangover expired."""


@dataclass
class Vad:
    """Energy VAD with start/stop hysteresis and a hangover.

    ``start_threshold`` is higher than ``stop_threshold`` on purpose: it takes
    a clear signal to open an utterance and a longer silence to close one.
    Defaults are tuned for a laptop mic at conversational distance; a noisy
    room wants :meth:`calibrate`.
    """

    start_threshold: float = 0.020
    stop_threshold: float = 0.010
    hangover_ms: int = 500
    frame_ms: int = 20

    _active: bool = False
    _silent_ms: int = 0

    def reset(self) -> None:
        self._active = False
        self._silent_ms = 0

    def push(self, frame: bytes) -> SpeechEvent:
        """Classify one frame."""
        level = rms(frame)
        if not self._active:
            if level >= self.start_threshold:
                self._active = True
                self._silent_ms = 0
                return SpeechEvent.STARTED
            return SpeechEvent.NONE

        if level >= self.stop_threshold:
            self._silent_ms = 0
            return SpeechEvent.CONTINUING

        self._silent_ms += self.frame_ms
        if self._silent_ms >= self.hangover_ms:
            self._active = False
            self._silent_ms = 0
            return SpeechEvent.ENDED
        return SpeechEvent.CONTINUING

    @property
    def active(self) -> bool:
        return self._active

    def calibrate(self, frames: list[bytes], *, margin: float = 4.0) -> None:
        """Set thresholds from a sample of room noise.

        Called at startup on a second of silence. A fixed threshold that works
        in a quiet office either never fires or never stops in a room with a
        fan, and asking the operator to tune two floats by hand is a good way
        to have them never get tuned.
        """
        if not frames:
            return
        levels = sorted(rms(f) for f in frames)
        floor = levels[len(levels) // 2]  # median: robust to a stray bang
        self.start_threshold = max(0.008, floor * margin)
        self.stop_threshold = max(0.004, floor * margin / 2)
