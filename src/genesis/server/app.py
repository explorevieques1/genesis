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
                # The field names are `types/fleet.ts`'s `SafetyFloor` exactly.
                # They were not, and the mismatch was invisible from both ends:
                # the socket accepted the envelope, the store wrote `undefined`
                # into `portfolioHeat`, and `money()` threw inside the safety
                # floor -- blanking the whole surface. The floor is the one
                # component that must survive everything else failing, so its
                # contract is pinned by a test rather than by agreement.
                #
                # Em dashes, not zeroes. There is no broker and no position, so
                # heat is *unknown*, and "0.00%" is a claim this system is not
                # entitled to make.
                "safety": {
                    "approvalMode": "confirm",  # Safety Invariants §5
                    "portfolioHeat": "—",
                    "heatLimit": "—",
                    "dailyLossHeadroom": "—",
                    "openPositions": 0,
                    "halted": False,
                    "haltTrigger": None,
                    "asOf": 0,
                },
                # Likewise `SystemHealth` -- the keys the health bar reads.
                "health": {
                    "daemon": "ok",
                    "memory": "ok",
                    "risk": "unknown",
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
        # A `conversation` key -- even an empty string -- means the caller is
        # the Ask Genesis panel and wants the exchange saved. An empty value is
        # a new conversation and the store mints the id; a real id appends to
        # it. Voice and Cmd-K send no key at all and are not persisted, because
        # they belong to no conversation.
        conversation = body.get("conversation")
        reply = await _run(bus, text, heard_via="text", conversation=conversation)
        if conversation is not None:
            try:
                from genesis.server.conversation_routes import conversation_store

                reply = {
                    **reply,
                    "conversation": conversation_store().append(
                        str(conversation) or None, operator_text=text, reply=reply
                    ),
                }
            except Exception:  # noqa: BLE001 - scrollback is a convenience, never fail the command over it
                log.exception("could not persist conversation turn")
        return JSONResponse(reply)

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
    from genesis.server.automation_routes import automation_routes
    from genesis.server.backtest_routes import backtest_routes
    from genesis.server.broker_routes import broker_routes
    from genesis.server.execution_routes import execution_routes
    from genesis.server.symbol_routes import symbol_routes
    from genesis.server.canvas_routes import canvas_routes
    from genesis.server.conversation_routes import conversation_routes
    from genesis.server.journal_routes import journal_routes
    from genesis.server.news_routes import news_routes
    from genesis.server.notebook_routes import notebook_routes
    from genesis.server.drawing_routes import drawing_routes
    from genesis.server.range_routes import range_routes
    from genesis.server.reads import read_routes
    from genesis.server.tool_routes import tool_routes
    from genesis.server.voice_routes import voice_routes
    from genesis.server.watchlist_routes import watchlist_routes

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: Any):
        """Hold the IBKR session open while the server runs, if IBKR is enabled.

        The session lives on its own thread; the bus belongs to this loop, so
        its events are handed over with `call_soon_threadsafe`.
        """
        from genesis.config import LiveConfig, load_config
        from genesis.marketdata import ibkr_live

        loop = asyncio.get_running_loop()
        try:
            ibkr_live.start(
                load_config(),
                lambda event, data: loop.call_soon_threadsafe(
                    lambda: bus.emit(event, data=data, source="ibkr")
                ),
            )
        except Exception:  # noqa: BLE001 - the UI must come up without a broker
            log.exception("could not start the IBKR live session")
        # The order path: its own thread and IBKR connection, plus the kill
        # switch as a separate, detached process so it outlives this one.
        from genesis.execution import order_manager

        try:
            config = load_config()
            if config.execution.enabled:
                _spawn_killswitch(config.execution.killswitch_port, config.execution.state_dir)
            order_manager.start(
                config,
                lambda event, data: loop.call_soon_threadsafe(
                    lambda: bus.emit(event, data=data, source="execution")
                ),
                # The risk envelope re-reads ~/.genesis/config.yaml per
                # proposal, so tightening a limit mid-session takes effect on
                # the next order instead of on the next restart. A broken file
                # keeps the limits already in force.
                live_config=LiveConfig(on_error=lambda exc: log.error("config reload refused: %s", exc)),
            )
        except Exception:  # noqa: BLE001 - the UI must come up without an order path
            log.exception("could not start the order manager")
        try:
            yield
        finally:
            order_manager.stop()
            ibkr_live.stop()

    return Starlette(
        lifespan=lifespan,
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
            # Hand-driven tool calls. Read-only, attributed to `operator`, and
            # through the same `Gateway.call` the orchestrator uses -- the
            # symmetry is the point, and it is why this adds no check of its
            # own. See `60-UI/Terminal.md`.
            *tool_routes(),
            # The research canvas. It writes -- membership, position, and edges
            # asserted by hand -- which is why it is not in `reads.py`. Nothing
            # it writes can reach an order path; it imports no execution code.
            *canvas_routes(),
            # Workflows: versions appended, runs recorded, roster synced on the
            # daemon's thread. No execution import; steps hold a read-only grant.
            *automation_routes(),
            # Saved Ask Genesis conversations: list, read, delete. The turns
            # are written by `command` above; this only reads them back and
            # lets the trader throw a thread away.
            *conversation_routes(),
            # The notebook and its graph. A vault is a directory of markdown,
            # so these write real files -- through one door, `Vault.resolve`,
            # which is where the containment check lives. No order path.
            *notebook_routes(),
            # The trader's watchlists: named lists of symbols, in sections,
            # theirs to edit. Small single-fact writes, no order path, no
            # execution import -- the conversation-store pattern. The one read
            # here (`/v1/market/quotes`) is a public tier-3 feed.
            *watchlist_routes(),
            *news_routes(),
            # Run a journal agent by hand, through the daemon's Task Bus.
            *journal_routes(),
            # Candle ranges: a named window of price, downloaded once and
            # kept for study. Writes a scrapbook, not the bar store --
            # `marketdata.ranges` says why they are separate.
            *range_routes(),
            # What the trader drew: boxes, levels, fibs, a position
            # sketch. The schema's own vocabulary, minus the `why` an
            # agent owes -- `charting.drawings` says why that differs.
            *drawing_routes(),
            # Synthesis. The reply text already came back from the command
            # route; this is what makes it audible.
            *voice_routes(bus),
            # Connect a data provider: IBKR login, gateway container, feed, and
            # a layered test. Writes files a person could edit by hand; no
            # order path, and Read-Only API has no off switch here.
            *broker_routes(),
            # The chart's symbol bar: IBKR contract search, and loading a
            # series into the bar store on demand.
            *symbol_routes(),
            # The order path: propose, place an approval, manage, flatten.
            # Efferent; every order passes the risk engine. See the module.
            *execution_routes(),
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


def _spawn_killswitch(port: int, state_dir: Any) -> None:
    """Start the kill switch unless one already answers on its port.

    Detached (its own session), so stopping or wedging the server leaves it
    running -- Kill Switch §Design constraints 1.
    """
    import socket
    import subprocess
    import sys
    from pathlib import Path

    with socket.socket() as s:
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return
    logs = Path(state_dir)
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "killswitch.log", "ab") as out:
        subprocess.Popen(  # noqa: S603 — our own module, fixed argv
            [sys.executable, "-m", "genesis.execution.killswitch"],
            stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
        )
    log.info("kill switch process started on port %s", port)


async def _run(
    bus: EventBus, text: str, *, heard_via: str, conversation: str | None = None
) -> dict[str, Any]:
    """Dispatch one utterance and narrate it onto the bus.

    The events are what make the UI stop being a diagram: `voice.state_changed`
    drives the core sigil, and the task pair drives the graph. They are emitted
    around real work rather than on a timer.
    """
    trace = str(uuid.uuid4())[:8]
    task_id = str(uuid.uuid4())[:12]
    hit = match_command(text)
    # A screening thread in Ask Genesis keeps the screener on the line: "only
    # tech" or "loosen the P/E" match nothing in the table, and must edit the
    # last scan rather than reach the analyst cold. Any other table command
    # ("chart NVDA") still wins and ends the thread.
    screen_history = _screen_history(conversation) if not hit or hit.command.name == "screen" else []
    if hit is None and screen_history:
        hit = match_command("scr")  # the screen command, for naming and routing only
    # "analyst", not "unmatched". The table declining is not a failure any
    # more -- it is the boundary between the fast path and the slow one, and
    # the trace should say which one ran rather than what did not.
    name = hit.command.name if hit else "analyst"

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
    #
    # An unmatched sentence is NOT an error and must not end here. The
    # deterministic table is the fast path, not the whole surface: past it sits
    # the same answer ladder the spoken path uses, and stopping at the table is
    # what made a microphone a capability (Operating Model §2). The table still
    # goes first -- "chart NVDA" must never cost a model call.
    if hit is not None and hit.command.name == "screen":
        from genesis.screener.chat import respond

        result: CommandResult = await loop.run_in_executor(None, respond, text, screen_history)
        if result.command == "screen.not_screen":
            result = await loop.run_in_executor(None, _ask_the_analyst, text)
    elif hit is not None:
        result = await loop.run_in_executor(None, dispatch, text)
    else:
        result = await loop.run_in_executor(None, _ask_the_analyst, text)
    elapsed = int((time.monotonic() - started) * 1000)
    if "screen" in (result.data or {}):
        # A ping, not the rows: the SCR panel re-reads `/v1/screener`, so every
        # door that ran a scan updates it the same way.
        bus.emit("screen.updated", data={"command": result.command}, trace=trace)
    if "watchlist" in (result.data or {}):
        bus.emit("watchlist.updated", data={"id": result.data["watchlist"]}, trace=trace)

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


def _screen_history(conversation: str | None) -> list[tuple[str, dict[str, Any]]]:
    """The screening exchanges this conversation is in the middle of, if any."""
    if not conversation:
        return []
    try:
        from genesis.screener.chat import history_from
        from genesis.server.conversation_routes import conversation_store

        found = conversation_store().get(conversation)
        return history_from(found["turns"]) if found else []
    except Exception:  # noqa: BLE001 - lost context is a fresh scan, not a failed command
        log.exception("could not read screening history")
        return []


def _ask_the_analyst(text: str) -> CommandResult:
    """Hand a sentence the command table declined to the answer ladder.

    Blocking, and slow the first time -- building the ladder starts the MCP
    gateway. The task is already on the bus by the time this is called, so the
    wait shows up in the UI as work in flight rather than as a hang.

    ``command`` carries the rung that answered (``analyst.reasoned``,
    ``analyst.trivial``, …) rather than a flat label, because that is what
    tells you afterwards whether a question cost a hosted round trip -- and it
    is what a test asserts on to prove the typed and spoken paths took the same
    rung.
    """
    from genesis.server.analyst import ANALYST

    rung = ANALYST.answer(text)
    return CommandResult(
        rung.reached,
        f"analyst.{rung.path}",
        rung.answer.text,
        None,
        {"source": rung.answer.source, **{k: str(v) for k, v in rung.fields.items()}},
    )


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
    import signal
    import sys

    import uvicorn

    # Uvicorn drains on SIGTERM, then restores the previous handler and
    # re-raises the signal. With the default handler that kills the process
    # outright, skipping the caller's fleet shutdown and every atexit hook --
    # orphaning MCP servers each time the dev watcher restarts us. Exiting
    # through SystemExit lets `finally` blocks and atexit run.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    uvicorn.run(build_app(), host=host, port=port, log_level="info")
