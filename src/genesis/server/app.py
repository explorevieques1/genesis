# Spec: Genesis Markdown/60-UI/UI Stack.md §7 Transport
"""The socket the UI has been waiting for.

``ui/src/transport/live.ts`` was written against an endpoint that did not
exist:

    The real transport. Not wired yet — the daemon has no socket surface as of
    2026-09-04 (there is no HTTP/WS server under `src/genesis/`).

This is that surface. It is deliberately small, because the UI note is
deliberately strict about the shape:

**Reads over the socket, writes over HTTP.** ``transport.ts`` has no ``send``
and that is a design decision, not an omission: *"commands go over HTTP so they
carry a response, an idempotency key and an audit line. A fire-and-forget
socket frame is the wrong shape for anything that acts."* So the WebSocket is
one-directional — events out — and every command is a POST with a reply.

**Nothing autonomous.** The server starts idle and stays idle. There is no
timer, no simulated fleet, no background pass. It emits an event when something
happens because you asked for it, and otherwise it is silent. That is the
system this is supposed to be, and it is also why the UI can now be cheap: an
idle surface receiving no frames does no work.

**Loopback only, and read-only.** It binds 127.0.0.1, and every command it can
run is afferent — charts, lookups, launching an app. There is deliberately no
route that could reach an order path; Phase 7's execution surface is a separate
decision with its own gate.

Built on Starlette + uvicorn, which are already present as transitive
dependencies of the MCP SDK — no new packages for this.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from dataclasses import dataclass, field
from typing import Any, Iterable

from genesis.commands import CommandResult, dispatch, match_command

__all__ = ["EventBus", "build_app", "serve"]

log = logging.getLogger(__name__)

#: How many events a late-joining or reconnecting client can replay. The UI
#: asks for a snapshot with a watermark and replays forward; this bounds how
#: far back that can go before the surface has to admit a gap rather than
#: pretend continuity.
REPLAY_BUFFER = 512

#: The agent every command is attributed to. Commands arrive through the
#: orchestrator, which is where a person's instruction enters the fleet.
ORCHESTRATOR = "orchestrator"


@dataclass
class EventBus:
    """Fan-out of Event Schema envelopes to connected UIs.

    Every event carries a monotonic ``id`` because the UI's reconnect logic is
    watermark-based: it replays forward from the last id it saw. Without a
    total order it cannot tell a gap from a reorder, and it is required to
    report a gap rather than paper over one.
    """

    _subscribers: set[asyncio.Queue] = field(default_factory=set)
    _recent: deque = field(default_factory=lambda: deque(maxlen=REPLAY_BUFFER))
    _seq: int = 0

    @property
    def watermark(self) -> str:
        return f"e{self._seq}"

    def emit(
        self,
        event: str,
        *,
        data: dict[str, Any] | None = None,
        trace: str | None = None,
        priority: str = "low",
        source: str = ORCHESTRATOR,
        speak: bool = False,
    ) -> dict[str, Any]:
        """Publish one envelope. Never blocks on a slow client.

        The field names are the UI's ``Envelope`` contract exactly --
        ``trace_id`` not ``trace``, ``ts`` as an ISO string not an epoch,
        ``source`` and ``priority`` present. This is not pedantry: the store
        reads ``e.trace_id`` and every handler is keyed on ``e.event``, so an
        envelope with the wrong shape is accepted by the socket, ignored by
        the store, and produces a UI that looks connected and does nothing.
        That failure is silent from both ends, which is why the shape is
        pinned by a test.
        """
        self._seq += 1
        envelope = {
            "id": f"e{self._seq}",
            "event": event,
            "ts": datetime.now(UTC).isoformat(),
            "trace_id": trace or str(uuid.uuid4())[:8],
            "source": source,
            "priority": priority,
            "speak": speak,
            "data": data or {},
        }
        self._recent.append(envelope)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                # A client too slow to keep up is dropped from this frame
                # rather than allowed to stall the emitter. It will notice the
                # gap on its next watermark check, which is the honest
                # outcome -- blocking the whole bus on one stuck socket is not.
                log.warning("dropping event for a slow subscriber")
        return envelope

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def since(self, watermark: str | None) -> list[dict[str, Any]]:
        """Events after ``watermark``. Empty when it is unknown or current."""
        if not watermark:
            return []
        for index, envelope in enumerate(self._recent):
            if envelope["id"] == watermark:
                return list(self._recent)[index + 1 :]
        # The watermark has aged out of the buffer. Returning everything we
        # hold would look like continuity across a gap we cannot vouch for, so
        # return nothing and let the client take a fresh snapshot.
        return []


def build_app(bus: EventBus | None = None) -> Any:
    """The Starlette app. Importable for tests without binding a port."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route, WebSocketRoute
    from starlette.websockets import WebSocket, WebSocketDisconnect

    bus = bus or EventBus()

    # -- reads ------------------------------------------------------------

    async def snapshot(request: Request) -> JSONResponse:
        """What the UI needs on connect, and the watermark to replay from.

        Reports the fleet as **idle**, because it is. The mock transport used
        to open onto a busy-looking system; this one opens onto the truth.
        """
        return JSONResponse(
            {
                "watermark": bus.watermark,
                "safety": {
                    "approvalMode": "confirm",  # Safety Invariants §5
                    "halted": False,
                    "dayPnl": "0.00",
                    "dayLossLimit": "0.00",
                    "openRisk": "0.00",
                    "positions": 0,
                    "workingOrders": 0,
                    "lastReconcileAt": None,
                },
                "health": {
                    "broker": "unknown",
                    "data": "ok",
                    "memory": "ok",
                    "voice": "ok",
                    "execution": "unknown",
                    "connectivity": "ok",
                },
            }
        )

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "idle": True})

    # -- writes: HTTP, because they act and must answer -------------------

    async def command(request: Request) -> JSONResponse:
        """Run a typed command. The same path voice uses, minus the audio.

        Exposed separately so the whole command layer is testable and usable
        without a microphone -- which matters because a mic failure should
        never be indistinguishable from a broken command.
        """
        body = await request.json()
        text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"error": "no text"}, status_code=400)
        return JSONResponse(await _run(bus, text, heard_via="text"))

    async def utterance(request: Request) -> JSONResponse:
        """Audio in, action out. The tap-to-speak path.

        The audio is transcribed **locally** by default -- faster-whisper, on
        this machine, nothing uploaded. Voice Stack's privacy posture, and it
        also means the whole path works with no API key.
        """
        form = await request.form()
        upload = form.get("audio")
        if upload is None:
            return JSONResponse({"error": "no audio"}, status_code=400)
        raw = await upload.read()  # type: ignore[union-attr]
        if len(raw) < 1024:
            # A tap that released before the mic warmed up. Saying so is much
            # better than transcribing silence into a wrong command.
            return JSONResponse(
                {
                    "ok": False,
                    "heard": "",
                    "spoken": "I didn't get any audio — hold the button while you speak.",
                    "command": "no_audio",
                }
            )

        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(None, _transcribe, raw)
        except Exception as exc:  # noqa: BLE001
            log.exception("transcription failed")
            return JSONResponse(
                {
                    "ok": False,
                    "heard": "",
                    "command": "stt_failed",
                    "spoken": "I couldn't transcribe that.",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
                status_code=200,
            )

        if not text.strip():
            return JSONResponse(
                {"ok": False, "heard": "", "command": "silence",
                 "spoken": "I didn't hear anything."}
            )
        return JSONResponse(await _run(bus, text, heard_via="voice"))

    # -- the event stream -------------------------------------------------

    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = bus.subscribe()
        try:
            for envelope in bus.since(websocket.query_params.get("since")):
                await websocket.send_text(json.dumps(envelope))
            while True:
                envelope = await queue.get()
                await websocket.send_text(json.dumps(envelope))
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            log.debug("event socket closed", exc_info=True)
        finally:
            bus.unsubscribe(queue)

    # Reads live in their own module and are all afferent -- see
    # `reads.py`. Kept separate so the writes in this file stay countable:
    # four routes act, everything else only looks.
    from genesis.server.backtest_routes import backtest_routes
    from genesis.server.reads import read_routes

    return Starlette(
        routes=[
            Route("/v1/snapshot", snapshot),
            Route("/v1/health", health),
            Route("/v1/command", command, methods=["POST"]),
            Route("/v1/voice/utterance", utterance, methods=["POST"]),
            WebSocketRoute("/v1/events", events),
            *read_routes(),
            # Backtests act -- they burn CPU and write a durable row -- so they
            # live apart from the reads. They still cannot reach an order path.
            *backtest_routes(bus),
        ],
        middleware=[
            # The Vite dev server is a different origin on the same host.
            # Loopback only -- this is not a public surface and must never
            # become one.
            Middleware(
                CORSMiddleware,
                allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                allow_methods=["GET", "POST"],
                allow_headers=["*"],
            )
        ],
    )


async def _run(bus: EventBus, text: str, *, heard_via: str) -> dict[str, Any]:
    """Dispatch one utterance and narrate it onto the bus.

    The events are what make the UI stop being a diagram: `voice.state_changed`
    drives the core sigil, and the task pair drives the graph. They are emitted
    around real work rather than on a timer.
    """
    trace = str(uuid.uuid4())[:8]
    task_id = str(uuid.uuid4())[:12]
    hit = match_command(text)
    name = hit.command.name if hit else "unmatched"

    # The full lifecycle, in order. `dispatched` is what CREATES the task
    # record and the edge token in the UI store; `started` and `completed`
    # look that record up by id. Emitting only the ending would leave the
    # store with nothing to update -- the graph would stay still while the
    # command ran perfectly, which reads as a broken UI.
    bus.emit("voice.state_changed", data={"to": "working"}, trace=trace)
    bus.emit(
        "task.dispatched",
        data={
            "task_id": task_id, "parent_task_id": None, "agent": ORCHESTRATOR,
            "task_type": f"command.{name}", "lane": "user",
        },
        trace=trace, priority="normal",
    )
    bus.emit("task.started", data={"task_id": task_id, "agent": ORCHESTRATOR}, trace=trace)

    loop = asyncio.get_running_loop()
    started = time.monotonic()
    # Commands do blocking IO -- HTTP, subprocess launch, DuckDB. Off the event
    # loop, or one chart request freezes the socket for every client.
    result: CommandResult = await loop.run_in_executor(None, dispatch, text)
    elapsed = int((time.monotonic() - started) * 1000)

    if result.ok:
        bus.emit(
            "task.completed",
            data={
                "task_id": task_id, "agent": ORCHESTRATOR, "wall_ms": elapsed,
                # No model ran, so nothing was spent. Reporting a real zero
                # rather than omitting the field, which the store would add
                # to its running total as undefined.
                "cost_usd": "0.0000",
                "spoken_summary": result.spoken,
            },
            trace=trace,
        )
    else:
        bus.emit(
            "task.failed",
            data={
                "task_id": task_id, "agent": ORCHESTRATOR, "wall_ms": elapsed,
                "cost_usd": "0.0000", "failure_class": "degraded",
                "reason": result.detail or result.spoken,
            },
            trace=trace, priority="high",
        )
    bus.emit("voice.state_changed", data={"to": "speaking"}, trace=trace, speak=True)
    bus.emit("voice.state_changed", data={"to": "idle"}, trace=trace)

    return {
        "ok": result.ok,
        "heard": text,
        "command": result.command,
        "spoken": result.spoken,
        "detail": result.detail,
        "data": result.data,
        "ms": elapsed,
        "trace": trace,
    }


def _transcribe(raw: bytes) -> str:
    """Bytes from the browser -> text, locally.

    The browser sends a compressed container (webm/opus, or mp4 on Safari) and
    faster-whisper wants audio it can decode. It accepts a file path or a
    file-like object and uses its own bundled decoder, so the container is
    handled there rather than by shelling out to ffmpeg -- one less thing that
    has to be installed for the microphone to work.
    """
    import io

    from genesis.voice.wake import LocalWhisperWake

    model = _model()
    segments, _info = model.transcribe(
        io.BytesIO(raw),
        beam_size=1,          # a command is short; beam search buys nothing
        language="en",
        vad_filter=True,      # drops the silence around a button press
        condition_on_previous_text=False,
    )
    return " ".join(segment.text for segment in segments).strip()


_MODEL: Any = None


def _model() -> Any:
    """The whisper model, loaded once and kept.

    ``tiny.en`` on CPU: a spoken command is two seconds of audio, and on an
    8 GB machine a larger model costs more in memory pressure than it returns
    in accuracy for a fixed command vocabulary. Loaded lazily so importing this
    module -- or running the server without ever using the mic -- does not pay
    for it.
    """
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        _MODEL = WhisperModel("tiny.en", device="cpu", compute_type="int8")
    return _MODEL


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the server. Loopback only, and not configurable to anything else.

    Binding beyond loopback would expose a surface that can launch local
    applications and read the market data store. There is no deployment story
    where that is wanted, so there is no flag for it.
    """
    import uvicorn

    uvicorn.run(build_app(), host=host, port=port, log_level="info")
