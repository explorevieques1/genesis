# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Speech to text: ElevenLabs Scribe, falling back to local Whisper.

Voice Stack's degradation table: *"ElevenLabs STT down -> fall back to local
Whisper; log degraded; keep working."* Because the wake gate already runs a
local transcriber to decide whether it was addressed, that fallback costs
nothing extra -- the transcript exists before the cloud is ever called.

That ordering is worth stating plainly, because it inverts the usual one:

1. The **local** transcript is produced first, by the wake gate.
2. Scribe is called to *improve* it, not to produce it.
3. If Scribe is unavailable, slow, or unauthorised, the local transcript is
   already in hand and the loop continues on it, labelled degraded.

So there is no state in which the microphone works, the machine works, and
Genesis cannot hear you because a vendor is down.
"""

from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass
from typing import Protocol

from genesis.errors import DegradedError

__all__ = ["ScribeSTT", "Transcript", "STTBackend", "wav_bytes"]

_API_ROOT = "https://api.elevenlabs.io/v1"


@dataclass(frozen=True)
class Transcript:
    text: str
    source: str
    """``scribe`` or ``local`` -- so the caller can label degraded output."""
    latency_ms: float = 0.0
    language: str | None = None


class STTBackend(Protocol):
    def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript: ...


def wav_bytes(pcm: bytes, sample_rate: int = 16_000, channels: int = 1) -> bytes:
    """Wrap raw int16 PCM in a WAV container.

    Hand-rolled rather than via :mod:`wave` because this runs per utterance on
    the latency path and a 44-byte header does not justify a temp file.
    """
    byte_rate = sample_rate * channels * 2
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, channels * 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm


class ScribeSTT:
    """ElevenLabs Scribe.

    Called only with audio the wake gate has already released -- there is no
    constructor argument that would let it read the ring buffer itself.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_id: str = "scribe_v1",
        timeout: float = 10.0,
    ) -> None:
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise DegradedError("ELEVENLABS_API_KEY is not set; cloud STT unavailable")
        self._key = key
        self.model_id = model_id
        self._timeout = timeout
        self._client = None

    def _http(self):
        import httpx

        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                headers={"xi-api-key": self._key},
                limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=300.0),
            )
        return self._client

    def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> Transcript:
        import time

        start = time.monotonic()
        payload = wav_bytes(pcm, sample_rate)
        try:
            response = self._http().post(
                f"{_API_ROOT}/speech-to-text",
                files={"file": ("utterance.wav", io.BytesIO(payload), "audio/wav")},
                data={"model_id": self.model_id},
            )
        except Exception as exc:  # noqa: BLE001
            raise DegradedError(f"Scribe unreachable: {exc}") from exc
        if response.status_code != 200:
            raise DegradedError(f"Scribe failed ({response.status_code}): {response.text[:200]}")
        body = response.json()
        return Transcript(
            text=body.get("text", "").strip(),
            source="scribe",
            latency_ms=(time.monotonic() - start) * 1000,
            language=body.get("language_code"),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
