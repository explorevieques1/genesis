# Spec: Genesis Markdown/10-Architecture/Voice Stack.md · 60-UI/Voice UX.md
"""Synthesis: text in, audio out.

The voice loop was only half wired. Audio went *in* — recorded in the browser,
transcribed locally, dispatched — and the answer came back as a **string**,
which the UI printed. `voice.state_changed → speaking` was emitted on the event
bus and the Genesis Core rendered its `speaking` state, so the surface said
Genesis was talking while the room stayed silent.

Everything needed already existed: `voice/tts.py` has the ElevenLabs and Piper
backends, `voice/speaker.py` builds the fallback chain. Nothing called them.

**Why the browser plays it, and not the daemon.** `voice/player.py` plays to
the machine's own speakers, which is right for the CLI loop and wrong here, for
two reasons:

1. `Genesis Core` is specified to pulse to the TTS envelope. Only the tab doing
   the playing can measure that envelope, so daemon-side playback leaves the
   Core animating to nothing — which is the fake-amplitude problem this project
   already fixed once.
2. Speech becomes a **separately failable step**. The command answers with its
   text whatever happens here; if synthesis fails the reply is still on screen,
   labelled as unspoken, rather than the whole turn failing because a vendor
   was slow.

So this returns bytes and the browser is the player.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import struct
from collections import OrderedDict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["voice_routes", "synthesise", "wav_bytes"]

#: Longest utterance we will synthesise. A reply is a sentence or two; anything
#: past this is a bug upstream, and paying a vendor per character for it is the
#: expensive way to find out.
MAX_CHARS = 800

#: Recently synthesised clips, keyed by (text, voice). Small, in memory, and
#: bounded.
#:
#: Replies repeat constantly — "I didn't hear anything", "I couldn't transcribe
#: that", the same status answer all afternoon — and each repeat is a paid API
#: call and a second of latency for audio we already have. Sixty-four entries is
#: a few megabytes and covers a session's worth of stock phrases.
_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_CACHE_MAX = 64


def wav_bytes(pcm: bytes, sample_rate: int, *, channels: int = 1, width: int = 2) -> bytes:
    """Wrap raw PCM in a WAV header.

    Both backends yield headerless 16-bit PCM, which no browser will play. A
    44-byte RIFF header is the whole difference between that and an ``<audio>``
    element, and it is cheaper than transcoding to a compressed container the
    daemon would need another dependency to produce.
    """
    header = io.BytesIO()
    header.write(b"RIFF")
    header.write(struct.pack("<I", 36 + len(pcm)))
    header.write(b"WAVEfmt ")
    header.write(struct.pack("<I", 16))          # PCM header size
    header.write(struct.pack("<H", 1))           # format: PCM
    header.write(struct.pack("<H", channels))
    header.write(struct.pack("<I", sample_rate))
    header.write(struct.pack("<I", sample_rate * channels * width))  # byte rate
    header.write(struct.pack("<H", channels * width))                # block align
    header.write(struct.pack("<H", width * 8))                       # bits/sample
    header.write(b"data")
    header.write(struct.pack("<I", len(pcm)))
    return header.getvalue() + pcm


def _backends() -> list[Any]:
    """The TTS fallback chain, from config and the secrets file.

    Built per request rather than held. Constructing a backend is cheap — it is
    a dataclass and an HTTP client — and rebuilding means a key added to
    `~/.genesis/.env` takes effect on the next utterance rather than on the next
    daemon restart.
    """
    from genesis.config import load_config, load_secrets
    from genesis.voice.speaker import default_backends

    config = load_config()
    secrets = load_secrets(Path("~/.genesis/.env"))
    return default_backends(
        config.identity.voice_id or "EXAVITQu4vr4xnSDxMaL",
        api_key=secrets.get("ELEVENLABS_API_KEY"),
        piper_model=None,
    )


def synthesise(text: str) -> tuple[bytes, str]:
    """``text`` → (WAV bytes, backend name). Blocking; call it in an executor.

    Walks the fallback chain and raises only when **every** backend failed, so
    a dead vendor degrades to the local one rather than to silence.
    """
    from genesis.errors import DegradedError

    backends = _backends()
    if not backends:
        raise DegradedError(
            "no TTS backend is available — set ELEVENLABS_API_KEY in "
            "~/.genesis/.env, or install piper for local synthesis"
        )

    failures: list[str] = []
    for backend in backends:
        try:
            pcm = b"".join(backend.stream(text))
            if not pcm:
                failures.append(f"{type(backend).__name__}: produced no audio")
                continue
            return wav_bytes(pcm, backend.sample_rate), type(backend).__name__
        except Exception as exc:  # noqa: BLE001
            # Recorded and stepped over. A vendor outage should cost the
            # sentence its preferred voice, not the sentence.
            failures.append(f"{type(backend).__name__}: {exc}")
            log.warning("TTS backend failed: %s", failures[-1])

    raise DegradedError("every TTS backend failed: " + "; ".join(failures))


def voice_routes(bus: Any = None) -> list[Any]:
    """The synthesis route.

    A POST, because it acts: it spends money at a vendor and takes real time.
    That is the same reasoning `UI Stack §7` gives for commands, and it is why
    this is not a GET despite looking like a lookup.
    """
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    async def say(request: Request) -> Response:
        from genesis.errors import DegradedError
        from genesis.voice.speech import speakable

        body = await request.json()
        text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"error": "no text"}, status_code=400)
        if len(text) > MAX_CHARS:
            return JSONResponse(
                {"error": f"{len(text)} characters exceeds the {MAX_CHARS} limit"},
                status_code=413,
            )

        # Spoken form, not written form: "NVDA long from 121.06" is said as
        # "N-V-D-A long from one twenty-one oh six". Synthesising the written
        # form gets a voice reading punctuation aloud.
        rendered = speakable(text)
        if not rendered.strip():
            return JSONResponse({"error": "nothing speakable in that text"}, status_code=400)

        key = hashlib.sha256(rendered.encode()).hexdigest()
        if (cached := _CACHE.get(key)) is not None:
            _CACHE.move_to_end(key)
            return Response(
                cached,
                media_type="audio/wav",
                headers={"x-genesis-tts": "cache", "cache-control": "no-store"},
            )

        loop = asyncio.get_running_loop()
        try:
            audio, backend = await loop.run_in_executor(None, synthesise, rendered)
        except DegradedError as exc:
            # 503 with a readable reason. The UI shows the reply text and says
            # it could not be spoken -- silence with no explanation is the one
            # outcome that leaves you wondering whether it heard you at all.
            return JSONResponse(
                {"error": str(exc), "kind": "tts_unavailable", "spoken_text": rendered},
                status_code=503,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("synthesis failed")
            return JSONResponse(
                {"error": f"{type(exc).__name__}: {exc}", "kind": "tts_failed"},
                status_code=500,
            )

        _CACHE[key] = audio
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)

        if bus is not None:
            bus.emit(
                "voice.spoken",
                data={"chars": len(rendered), "bytes": len(audio), "backend": backend},
            )
        return Response(
            audio,
            media_type="audio/wav",
            headers={"x-genesis-tts": backend, "cache-control": "no-store"},
        )

    async def voice_status(request: Request) -> JSONResponse:
        """Can this machine speak, and with what?

        Read by Settings, so the voice panel can say *"no TTS backend
        configured"* instead of a mute button that looks fine.
        """
        try:
            backends = _backends()
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"available": False, "reason": str(exc)})
        return JSONResponse({
            "available": bool(backends),
            "backends": [type(b).__name__ for b in backends],
            "reason": None if backends else (
                "no TTS backend — set ELEVENLABS_API_KEY in ~/.genesis/.env, "
                "or install piper for local synthesis"
            ),
            "cached_clips": len(_CACHE),
        })

    return [
        Route("/v1/voice/say", say, methods=["POST"]),
        Route("/v1/voice/status", voice_status),
    ]
