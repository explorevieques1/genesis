# Spec: Genesis Markdown/30-MCP/genesis-tradingview-mcp.md
"""Speaking Chrome DevTools Protocol to the TradingView Desktop app.

The note records the spike result and the transport decision, both verified
2026-08-30 against TradingView Desktop 3.3.0 / Electron 38.2.2:

    Retrieve the websocket URL over HTTP, then open the socket directly.
    No browser automation framework.

**Playwright is the obvious client and the wrong one.**
``connect_over_cdp`` retrieves the websocket URL, connects, and then hangs to
its 180-second launch timeout — its browser-attach handshake disagrees with
Electron's target model. Raw CDP against the *same* endpoint succeeds in
milliseconds. Recorded in the note so nobody spends an afternoon rediscovering
it; recorded here so nobody adds the dependency back.

**Why the WebSocket client is hand-written.**
Roughly a hundred lines that would otherwise be a dependency. The trade is
worth making in exactly this situation and would not be in most: the peer is
Chromium on ``127.0.0.1``, so there is no TLS, no proxy, no compression
negotiation and no hostile framing — the three hard parts of a general client
are all absent. What is gained is that the frame codec is a pure function that
can be tested exhaustively with no TradingView, no Electron and no network,
which matters more than usual here because *everything else in this module can
only be tested against a running GUI.*

**Nothing here can reach a broker.** Hard rule 1 of the note: TradingView
Desktop has broker integration, and an automation client that can click is one
that can click Buy. The defence is structural rather than promised — see
:data:`DENIED_PATTERNS` and :meth:`CDPSession.evaluate`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse

from genesis.errors import DegradedError, FatalError

__all__ = [
    "DEFAULT_PORT",
    "CDPSession",
    "CDPUnavailable",
    "ForbiddenSurface",
    "Target",
    "launch_desktop",
    "targets",
    "version",
]

DEFAULT_PORT = 9222
#: The app takes ~4 seconds to open the port, measured in the spike. This is
#: the ceiling on waiting for it, not an expectation.
LAUNCH_TIMEOUT_SEC = 20.0


class CDPUnavailable(DegradedError):
    """TradingView is closed, updating, or not listening.

    Hard rule 4: *degrade, never block*. This is a ``DegradedError`` and not a
    fatal one because nothing in the autonomous loop may hard-depend on a GUI
    being open — an agent that cannot reach the chart proceeds without it and
    labels what it produced, which at 3am with no GUI running is the normal
    case rather than an error.
    """


class ForbiddenSurface(FatalError):
    """An action resolved into a part of the app that is off limits.

    Fatal, and deliberately not degraded: this is not a capability being
    unavailable, it is an attempt to touch the order path. Hard rule 1 says
    such an action *aborts and logs*, and something that aborts must not be
    retried into eventually working.
    """

    def __init__(self, matched: str) -> None:
        super().__init__(
            f"refused: the expression reaches {matched!r}, which is the trade "
            f"surface. Orders go through genesis-execution-mcp. Only.",
            spoken_summary="I refused a chart action that reached the trade panel.",
        )
        self.matched = matched


#: Surfaces that mean an expression is reaching for the order path.
#:
#: Matched against a **normalised** form of the expression — lowercased with
#: every non-alphanumeric character removed — so ``trade panel``,
#: ``trade-panel``, ``trade_panel``, ``tradePanel`` and ``TRADE.PANEL`` are one
#: pattern rather than five. Writing them out separately is how a list like
#: this develops a hole: the first version of this file had ``trade panel`` and
#: ``trading-panel`` and missed ``trade-panel``, which is the spelling
#: TradingView actually uses.
#:
#: This is a reflex in the Biological Design sense: deterministic, cheap, and
#: incapable of being talked out of firing. It is also, like every reflex made
#: of a list, only as good as its list — which is why it is the *second* line
#: of defence. The first is that no tool in this server takes an order, a size
#: or a side as an argument, so there is no legitimate call that would ever
#: construct such an expression.
DENIED_PATTERNS: tuple[str, ...] = (
    "tradepanel",
    "tradingpanel",
    "orderpanel",
    "orderticket",
    "orderform",
    "placeorder",
    "submitorder",
    "sendorder",
    "createorder",
    "jsorder",
    "buybutton",
    "sellbutton",
    "brokerbutton",
    "brokerpanel",
    "closeposition",
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalise(expression: str) -> str:
    return _NON_ALNUM.sub("", expression.lower())


def _denied(expression: str) -> str | None:
    """The pattern that fired, if any."""
    flattened = _normalise(expression)
    for pattern in DENIED_PATTERNS:
        if pattern in flattened:
            return pattern
    return None


# --------------------------------------------------------------------------
# Discovery over HTTP
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One debuggable page inside the app. The spike enumerated eleven."""

    id: str
    type: str
    title: str
    url: str
    websocket_url: str

    @property
    def is_chart(self) -> bool:
        return "tradingview.com/chart" in self.url


def _get_json(port: int, path: str, timeout: float = 3.0) -> Any:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as fh:
            return json.load(fh)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        raise CDPUnavailable(
            f"TradingView Desktop is not answering on 127.0.0.1:{port} ({exc}). "
            f"Launch it with --remote-debugging-port={port}."
        ) from exc


def version(port: int = DEFAULT_PORT) -> dict[str, Any]:
    """``/json/version`` — the browser-level endpoint and a liveness check."""
    return _get_json(port, "/json/version")


def targets(port: int = DEFAULT_PORT) -> tuple[Target, ...]:
    """Every debuggable target, chart pages included."""
    return tuple(
        Target(
            id=str(item.get("id", "")),
            type=str(item.get("type", "")),
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            websocket_url=str(item.get("webSocketDebuggerUrl", "")),
        )
        for item in _get_json(port, "/json/list")
        if item.get("webSocketDebuggerUrl")
    )


def chart_target(port: int = DEFAULT_PORT) -> Target:
    """The chart page, which is what every tool here actually wants."""
    found = [t for t in targets(port) if t.is_chart]
    if not found:
        raise CDPUnavailable(
            "TradingView is running but has no chart page open. Open a chart."
        )
    return found[0]


# --------------------------------------------------------------------------
# Launching
# --------------------------------------------------------------------------


def launch_desktop(
    port: int = DEFAULT_PORT,
    *,
    binary: str = "tradingview",
    timeout: float = LAUNCH_TIMEOUT_SEC,
) -> subprocess.Popen[bytes]:
    """Start the app with the debugging port open, and wait for it.

    ``ELECTRON_RUN_AS_NODE`` is stripped from the child environment
    unconditionally. The note flags this as a danger for a specific reason:
    with it set — and it *is* set in a VS Code extension-host shell, and in
    anything that inherits from one — the Electron binary runs as plain Node,
    rejects ``--remote-debugging-port`` as an unknown Node option, and gives
    you a REPL where a chart should be. The failure message is
    ``bad option: --remote-debugging-port=9222``, which is indistinguishable at
    a glance from Electron having disabled remote debugging: it looks exactly
    like the NO answer that would kill this whole server.

    Stripping rather than checking, because the variable being absent from
    *this* process is not the same as it being absent from the child's, and the
    note says so in as many words: do not merely rely on it being absent.
    """
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    process = subprocess.Popen(  # noqa: S603 - fixed binary, no shell
        [binary, f"--remote-debugging-port={port}"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CDPUnavailable(
                f"{binary} exited immediately with code {process.returncode}. "
                f"If the message was 'bad option: --remote-debugging-port', "
                f"ELECTRON_RUN_AS_NODE reached the child environment."
            )
        try:
            version(port)
            return process
        except CDPUnavailable:
            time.sleep(0.25)
    process.terminate()
    raise CDPUnavailable(
        f"{binary} started but never opened port {port} within {timeout:.0f}s"
    )


# --------------------------------------------------------------------------
# The WebSocket frame codec — a pure function, tested without a browser
# --------------------------------------------------------------------------

_OP_TEXT = 0x1
_OP_BINARY = 0x2
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


def encode_frame(payload: bytes, opcode: int = _OP_TEXT) -> bytes:
    """One masked client frame. Clients MUST mask; servers MUST NOT.

    Chromium closes the connection on an unmasked client frame rather than
    tolerating it, which is the correct reading of RFC 6455 and also the
    reason this is not a detail worth being casual about.
    """
    mask = secrets.token_bytes(4)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", length)
    return bytes(header) + mask + masked


class _FrameReader:
    """Reassembles frames from a byte stream.

    Continuation frames are handled because CDP screenshots are megabytes of
    base64 and Chromium does fragment them. A reader that assumed one frame per
    message would work perfectly against every small response and fail on the
    single tool whose whole purpose is a large one.
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buffer = bytearray()

    def _read_exactly(self, count: int) -> bytes:
        while len(self._buffer) < count:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise CDPUnavailable("the CDP socket closed mid-frame")
            self._buffer += chunk
        out = bytes(self._buffer[:count])
        del self._buffer[:count]
        return out

    def read_message(self) -> tuple[int, bytes]:
        """One complete message: its opcode and its reassembled payload."""
        opcode: int | None = None
        payload = bytearray()
        while True:
            first, second = self._read_exactly(2)
            final = bool(first & 0x80)
            frame_op = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exactly(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exactly(8))[0]
            # A server frame is never masked; if one were, this would be the
            # wrong length and everything after it garbage — so read the mask
            # rather than assuming, and let the framing stay correct.
            mask = self._read_exactly(4) if second & 0x80 else b""
            chunk = self._read_exactly(length)
            if mask:
                chunk = bytes(b ^ mask[i % 4] for i, b in enumerate(chunk))
            if opcode is None and frame_op != 0:
                opcode = frame_op
            payload += chunk
            if final:
                return opcode or _OP_TEXT, bytes(payload)


# --------------------------------------------------------------------------
# The session
# --------------------------------------------------------------------------


class CDPSession:
    """One socket to one target, speaking CDP.

    Synchronous and serialized by a lock, which matches the rest of Genesis:
    the fleet is threaded, the gateway's async is confined to one file, and a
    second event loop for a GUI client would be a second concurrency model to
    reason about for no gain — CDP calls here are user-facing actions measured
    in tens per minute, not a data feed.
    """

    def __init__(self, websocket_url: str, *, timeout: float = 15.0) -> None:
        self.websocket_url = websocket_url
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._reader: _FrameReader | None = None
        self._id = 0
        self._lock = threading.Lock()

    # -- connection ---------------------------------------------------

    def connect(self) -> CDPSession:
        parsed = urlparse(self.websocket_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or DEFAULT_PORT
        path = parsed.path or "/"
        key = base64.b64encode(secrets.token_bytes(16)).decode()

        try:
            sock = socket.create_connection((host, port), timeout=self.timeout)
        except OSError as exc:
            raise CDPUnavailable(f"cannot open the CDP socket: {exc}") from exc
        sock.settimeout(self.timeout)

        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        ).encode()
        sock.sendall(handshake)

        reader = _FrameReader(sock)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise CDPUnavailable("the app closed the socket during handshake")
            response += chunk
        head, _, rest = bytes(response).partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise CDPUnavailable(
                f"CDP refused the upgrade: {head.splitlines()[0].decode(errors='replace')}"
            )
        # Anything the server sent after the handshake in the same packet is
        # already a frame. Dropping it would lose the first response of a fast
        # session — rare, and rare bugs in transports are the expensive kind.
        reader._buffer += rest
        self._sock, self._reader = sock, reader
        return self

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.sendall(encode_frame(b"", _OP_CLOSE))
                except OSError:
                    pass
                self._sock.close()
            self._sock, self._reader = None, None

    def __enter__(self) -> CDPSession:
        return self.connect()

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- protocol -----------------------------------------------------

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One CDP command, and its matching reply.

        Events arriving between the command and its reply are skipped rather
        than queued. This client issues commands and reads answers; it does not
        subscribe to anything, and a growing queue of ``Network.*`` events
        nobody reads is a leak in a process that stays up all day.
        """
        if self._sock is None or self._reader is None:
            raise CDPUnavailable("not connected")
        with self._lock:
            self._id += 1
            message_id = self._id
            payload = json.dumps(
                {"id": message_id, "method": method, "params": params or {}}
            ).encode()
            try:
                self._sock.sendall(encode_frame(payload))
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    opcode, raw = self._reader.read_message()
                    if opcode == _OP_PING:
                        self._sock.sendall(encode_frame(raw, _OP_PONG))
                        continue
                    if opcode == _OP_CLOSE:
                        raise CDPUnavailable("the app closed the CDP socket")
                    if opcode not in (_OP_TEXT, _OP_BINARY):
                        continue
                    message = json.loads(raw.decode("utf-8", "replace"))
                    if message.get("id") == message_id:
                        if "error" in message:
                            raise CDPUnavailable(
                                f"{method} failed: {message['error'].get('message')}"
                            )
                        return message.get("result", {})
            except (OSError, ValueError) as exc:
                raise CDPUnavailable(f"{method} failed on the CDP socket: {exc}") from exc
        raise CDPUnavailable(f"{method} timed out after {self.timeout:.0f}s")

    # -- the two operations everything is built from ------------------

    def evaluate(self, expression: str) -> Any:
        """Run JavaScript in the page and return its value.

        The denied-surface check runs **before** the expression is sent, not
        after it returns. Hard rule 1 is about what may be *reached*, and a
        check on the result would already have let the click happen.
        """
        matched = _denied(expression)
        if matched is not None:
            raise ForbiddenSurface(matched)

        result = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                # The app's own UI is not a user gesture we are entitled to
                # fake. Anything needing one is a click, and clicks are how an
                # automation client ends up on the Buy button.
                "userGesture": False,
            },
        )
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            raise CDPUnavailable(
                f"the page raised: {detail.get('text')} "
                f"{detail.get('exception', {}).get('description', '')}".strip()
            )
        return result.get("result", {}).get("value")

    def screenshot(self) -> bytes:
        """A PNG of the current viewport.

        Hard rule 2: *verify every mutation by reading back*. The app is a
        black box; act, screenshot, confirm. A tool that reports success
        without this is reporting an intention.
        """
        result = self.send("Page.captureScreenshot", {"format": "png"})
        data = result.get("data")
        if not data:
            raise CDPUnavailable("the app returned an empty screenshot")
        return base64.b64decode(data)


def open_chart(port: int = DEFAULT_PORT, *, timeout: float = 15.0) -> CDPSession:
    """Connect to the chart page. The entry point for every tool here."""
    return CDPSession(chart_target(port).websocket_url, timeout=timeout).connect()
