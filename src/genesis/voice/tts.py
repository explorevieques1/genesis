# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Text to speech: ElevenLabs streaming, with a local fallback.

Voice Stack's latency budget allows **400 ms to the first spoken chunk**, and
its degradation table says an ElevenLabs outage falls back to local TTS --
*"voice changes, system doesn't stop"*. Both shape this module:

* **Streaming, not batch.** The ``/stream`` endpoint returns audio while it is
  still being generated. Measured against this account, first byte lands in
  ~300 ms; the non-streaming endpoint returns nothing until the whole clip
  exists and blows the budget on any sentence worth saying.
* **PCM, not MP3.** ``pcm_24000`` needs no decoder, so bytes off the socket go
  straight to the device. (``pcm_44100`` is a Pro-plan format and 403s below
  it -- 24 kHz is the right default regardless, being plenty for speech.)
* **Failure is degraded, never fatal.** Any transport error raises
  :class:`~genesis.errors.DegradedError` so the caller falls back rather than
  taking the daemon down with it.

The text is passed through :func:`~genesis.voice.speech.speakable` before it
reaches the wire, so no path to the speakers can skip the number and ticker
conventions.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from genesis.errors import DegradedError
from genesis.voice.speech import speakable

__all__ = ["ElevenLabsTTS", "PiperTTS", "TTSBackend", "TTSVoice"]

_API_ROOT = "https://api.elevenlabs.io/v1"

#: Flash is the low-latency model. Voice Stack cares about time-to-first-chunk
#: far more than about the marginal naturalness of ``multilingual_v2``, and on
#: a spoken price the difference is inaudible while the latency is not.
_DEFAULT_MODEL = "eleven_flash_v2_5"

#: A premade voice, usable on every plan including free. The configured
#: ``identity.voice_id`` may be a library or cloned voice, which ElevenLabs
#: restricts to paid accounts -- when that call 402s the speaker falls back
#: here so development is never blocked on billing.
FALLBACK_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"


class TTSBackend(Protocol):
    """Anything that can turn text into a stream of PCM chunks."""

    sample_rate: int

    def stream(self, text: str) -> Iterator[bytes]: ...


@dataclass(frozen=True)
class TTSVoice:
    """Resolved voice settings. Behaviour, not secrets."""

    voice_id: str
    model_id: str = _DEFAULT_MODEL
    stability: float = 0.5
    similarity_boost: float = 0.75
    speed: float = 1.0


class ElevenLabsTTS:
    """Streaming ElevenLabs TTS.

    The API key is read from the environment, never from :class:`Config` --
    ``Config`` has no field that can hold a secret, by construction.
    """

    def __init__(
        self,
        voice: TTSVoice,
        *,
        api_key: str | None = None,
        sample_rate: int = 24_000,
        timeout: float = 10.0,
    ) -> None:
        key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise DegradedError(
                "ELEVENLABS_API_KEY is not set; cloud TTS unavailable",
                spoken_summary="Cloud voice is not configured.",
            )
        self._key = key
        self.voice = voice
        self.sample_rate = sample_rate
        self._timeout = timeout
        # One client for the life of the process. Voice Stack budgets 400 ms to
        # the first chunk; a fresh TLS handshake costs ~400 ms of that on its
        # own, so a client-per-utterance cannot meet the budget no matter how
        # fast the API is. Measured here: 741 ms cold, ~310 ms warm.
        self._client = None

    def _http(self):
        import httpx

        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                headers={"xi-api-key": self._key, "Content-Type": "application/json"},
                limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=300.0),
            )
        return self._client

    def warm(self) -> None:
        """Open the TLS connection before it is needed.

        Called at daemon start so the first thing you ask Genesis is not the
        request that pays for the handshake.
        """
        try:
            self._http().get(f"{_API_ROOT}/models", timeout=5.0)
        except Exception:  # noqa: BLE001 - warming is best-effort by definition
            pass

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def output_format(self) -> str:
        return f"pcm_{self.sample_rate}"

    def stream(self, text: str) -> Iterator[bytes]:
        """Yield PCM chunks as they arrive.

        Raises :class:`DegradedError` on any transport or API failure -- the
        caller's job is to fall back, not to crash.
        """
        spoken = speakable(text)
        url = f"{_API_ROOT}/text-to-speech/{self.voice.voice_id}/stream"
        payload = {
            "text": spoken,
            "model_id": self.voice.model_id,
            "voice_settings": {
                "stability": self.voice.stability,
                "similarity_boost": self.voice.similarity_boost,
                "speed": self.voice.speed,
            },
        }
        try:
            with self._http().stream(
                "POST",
                url,
                params={"output_format": self.output_format},
                json=payload,
            ) as response:
                if response.status_code != 200:
                    response.read()
                    raise _api_error(response.status_code, response.text)
                yield from response.iter_bytes()
        except DegradedError:
            raise
        except Exception as exc:  # httpx transport errors, DNS, TLS, timeouts
            raise DegradedError(
                f"ElevenLabs TTS unreachable: {exc}",
                spoken_summary="Cloud voice is down.",
            ) from exc


def _api_error(status: int, body: str) -> DegradedError:
    """Translate an API rejection into a typed failure with a usable message.

    402 in particular is not a bug to debug -- it is a plan restriction, and
    saying so saves the operator reading a stack trace to learn it.
    """
    if status == 402:
        return DegradedError(
            f"ElevenLabs rejected the voice for billing reasons (402): {body[:200]}. "
            "Library and cloned voices need a paid plan; premade voices do not.",
            spoken_summary="That voice needs a paid plan.",
        )
    if status == 401:
        return DegradedError(
            f"ElevenLabs rejected the API key (401): {body[:200]}. "
            "Check the key's scopes include text_to_speech.",
            spoken_summary="Cloud voice is not authorised.",
        )
    if status == 429:
        return DegradedError(
            "ElevenLabs rate limit reached (429)",
            spoken_summary="Cloud voice is rate limited.",
        )
    return DegradedError(f"ElevenLabs TTS failed ({status}): {body[:200]}")


class PiperTTS:
    """Local fallback TTS via the ``piper`` binary.

    Deliberately a subprocess rather than a Python dependency: Piper ships as a
    static binary plus an ``.onnx`` voice file, and the daemon should not carry
    a torch-sized import for a path it takes only when the network is down.
    """

    def __init__(self, model_path: str, *, binary: str = "piper", sample_rate: int = 22_050) -> None:
        self.model_path = model_path
        self.binary = binary
        self.sample_rate = sample_rate

    def stream(self, text: str) -> Iterator[bytes]:
        import subprocess

        spoken = speakable(text)
        try:
            proc = subprocess.Popen(  # noqa: S603
                [self.binary, "--model", self.model_path, "--output_raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise DegradedError(
                f"local TTS binary {self.binary!r} not found",
                spoken_summary=None,
            ) from exc
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(spoken.encode())
            proc.stdin.close()
            while chunk := proc.stdout.read(4096):
                yield chunk
            if proc.wait(timeout=5) != 0:
                raise DegradedError(
                    f"local TTS {self.binary!r} exited {proc.returncode}"
                )
        finally:
            # Barge-in closes this generator mid-sentence -- that is the normal
            # case, not the exception -- and a generator abandoned without this
            # leaves a piper process holding the audio pipe. Do that a few
            # times in a session and the machine is full of them.
            if proc.poll() is None:
                proc.kill()
            for pipe in (proc.stdin, proc.stdout):
                if pipe is not None and not pipe.closed:
                    pipe.close()
            proc.wait(timeout=5)
