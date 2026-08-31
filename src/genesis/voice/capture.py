# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""The ear: a continuous microphone with a rolling memory.

Voice Stack's capture stage is *"local mic, continuous ring buffer -- keeps
~30 s of rolling audio so the wake word can be anywhere in a sentence"*. The
ring buffer is not an optimisation; it is what makes

    "Give me the semis setup, Genesis"

work at all. By the time the wake word is recognised, the words that matter
have already been spoken. A system that starts recording *when* it hears its
name can only ever handle the wake word coming first, which is not how people
talk.

So the mic runs continuously into a fixed-size ring, and the wake gate reaches
*backwards* into it. Nothing leaves the machine until that gate opens -- see
:mod:`genesis.voice.wake`.

Audio is 16 kHz mono int16 throughout the input path: what VAD, wake detection
and Scribe all want, and small enough that thirty seconds of it is under a
megabyte.
"""

from __future__ import annotations

import threading
from collections import deque

__all__ = ["Microphone", "RingBuffer", "SAMPLE_RATE", "FRAME_MS", "FRAME_SAMPLES"]

SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320 samples, 640 bytes


class RingBuffer:
    """A fixed-duration rolling window of PCM, safe across threads.

    Stores frames rather than a flat array so that appends are O(1) and the
    audio callback never copies the whole buffer. ``deque(maxlen=...)`` does
    the eviction, which means the memory ceiling is structural rather than
    something a caller has to remember to enforce.
    """

    def __init__(self, seconds: float = 30.0, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.seconds = seconds
        self._max_frames = max(1, int(seconds * 1000 / FRAME_MS))
        self._frames: deque[bytes] = deque(maxlen=self._max_frames)
        self._lock = threading.Lock()

    def write(self, frame: bytes) -> None:
        with self._lock:
            self._frames.append(frame)

    def tail(self, seconds: float) -> bytes:
        """The most recent ``seconds`` of audio, oldest first."""
        wanted = max(1, int(seconds * 1000 / FRAME_MS))
        with self._lock:
            frames = list(self._frames)[-wanted:]
        return b"".join(frames)

    def all(self) -> bytes:
        with self._lock:
            return b"".join(self._frames)

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()

    @property
    def duration(self) -> float:
        with self._lock:
            return len(self._frames) * FRAME_MS / 1000


class Microphone:
    """Continuous capture into a ring buffer, with an optional frame tap.

    ``on_frame`` is called on the audio thread for every frame -- it is how VAD
    and wake detection see audio without polling. It must be as cheap as
    :meth:`Player._callback`: no network, no locks held long, no model.
    """

    def __init__(
        self,
        *,
        sample_rate: int = SAMPLE_RATE,
        buffer_seconds: float = 30.0,
        device: int | str | None = None,
        on_frame=None,
    ) -> None:
        self.sample_rate = sample_rate
        self.buffer = RingBuffer(buffer_seconds, sample_rate)
        self._device = device
        self._on_frame = on_frame
        self._stream = None
        #: Set while capture is running, so the loop can report a dead mic
        #: rather than waiting silently forever.
        self.running = threading.Event()

    def open(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd

        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=FRAME_SAMPLES,
            device=self._device,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()
        self.running.set()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.running.clear()

    def __enter__(self) -> Microphone:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _callback(self, indata, frames: int, time_info, status) -> None:  # noqa: ANN001, ARG002
        frame = bytes(indata)
        self.buffer.write(frame)
        if self._on_frame is not None:
            self._on_frame(frame)
