# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Interruptible PCM playback.

Voice Stack requires speech that can be cut *mid-word*, and Voice UX puts a
number on it: **"stop" cuts speech in under 300 ms**. That single requirement
decides the whole shape of this module.

A blocking ``play(whole_clip)`` cannot meet it -- once audio is handed to the
device there is nothing left to interrupt. So playback is a queue drained by a
callback, and :meth:`Player.stop` empties the queue rather than waiting for it.
The only latency left is the device buffer, which is one block.

**This is a reflex, not a judgement.** Nothing here may block on the network,
take a lock the audio callback also wants, or consult a model. The callback
runs on PortAudio's realtime thread: work done there is measured against the
block deadline, and overrunning it is an audible glitch. It therefore does
exactly two things -- copy bytes out of a deque, and zero-fill when there are
none.
"""

from __future__ import annotations

import threading
from collections import deque

__all__ = ["Player", "NullPlayer"]


class Player:
    """A mono PCM sink that can be silenced instantly.

    ``sounddevice`` is imported lazily so that importing :mod:`genesis.voice`
    on a machine with no audio stack -- CI, a headless daemon host -- does not
    fail. Voice is a surface, not the spine.
    """

    def __init__(self, sample_rate: int = 24_000, *, blocksize: int = 1024, device: int | str | None = None) -> None:
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        self._device = device
        self._chunks: deque[bytes] = deque()
        self._lock = threading.Lock()
        self._stream = None
        self._tail = b""
        #: Set while audio is queued or playing. The wake gate reads this to
        #: know whether inbound speech might be our own voice coming back.
        self.speaking = threading.Event()
        self._drained = threading.Event()
        self._drained.set()

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        """Open the output device. Idempotent."""
        if self._stream is not None:
            return
        import sounddevice as sd

        self._stream = sd.RawOutputStream(
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            device=self._device,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            self._chunks.clear()
            self._tail = b""
        self.speaking.clear()
        # No callback will run again, so nothing else will ever set this. A
        # waiter blocked in `wait()` at shutdown would otherwise sit there for
        # its whole timeout while the audio it is waiting for no longer exists.
        self._drained.set()

    def __enter__(self) -> Player:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- the realtime path -------------------------------------------------

    def _callback(self, outdata, frames: int, time_info, status) -> None:  # noqa: ANN001, ARG002
        """Fill one block. Runs on the audio thread -- keep it trivial."""
        wanted = frames * 2  # int16 mono
        buf = self._tail
        with self._lock:
            while len(buf) < wanted and self._chunks:
                buf += self._chunks.popleft()
        if len(buf) >= wanted:
            outdata[:] = buf[:wanted]
            self._tail = buf[wanted:]
        else:
            # Underrun, or the end of the utterance. Silence is the only safe
            # thing to emit; anything else is a click.
            outdata[:len(buf)] = buf
            outdata[len(buf):] = b"\x00" * (wanted - len(buf))
            self._tail = b""
            if not buf:
                self.speaking.clear()
                self._drained.set()

    # -- the caller's path -------------------------------------------------

    def feed(self, pcm: bytes) -> None:
        """Queue PCM for playback. Returns immediately."""
        if not pcm:
            return
        with self._lock:
            self._chunks.append(pcm)
        self._drained.clear()
        self.speaking.set()

    def stop(self) -> None:
        """Cut speech now.

        Drops everything queued and the partial block in hand. Bounded by one
        device block -- 1024 frames at 24 kHz is ~43 ms, comfortably inside the
        300 ms the spec allows.
        """
        with self._lock:
            self._chunks.clear()
            self._tail = b""
        self.speaking.clear()
        self._drained.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the queue drains. Returns False on timeout."""
        return self._drained.wait(timeout)

    @property
    def queued_bytes(self) -> int:
        with self._lock:
            return sum(len(c) for c in self._chunks) + len(self._tail)


class NullPlayer(Player):
    """A player that swallows audio. For tests and headless runs.

    It must stay *drained*: with no audio thread nothing would ever clear the
    queue, so a caller that waits for playback to finish would wait forever.
    A sink that discards has, by definition, already finished.
    """

    def open(self) -> None:
        return

    def close(self) -> None:
        self.speaking.clear()

    def feed(self, pcm: bytes) -> None:
        if pcm:
            self.speaking.set()
            self.speaking.clear()
            self._drained.set()
