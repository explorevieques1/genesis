# Spec: Genesis Markdown/10-Architecture/Web Access.md §The presentation surface
"""Frames pushed by Chromium, on a socket of their own.

The first version of this panel took a `Page.captureScreenshot` on a timer.
Measured on this machine, 2026-09-20:

    example.com             54 ms a capture  -> 18 fps ceiling
    tradingview.com/chart  115 ms a capture  ->  8.7 fps ceiling, 123 KB a frame

`captureScreenshot` is the expensive path on purpose: it forces a full
compositor frame, reads it back, and encodes it, every call, whether or not a
single pixel changed. `Page.startScreencast` hooks the compositor instead and
pushes a frame *when the page paints one*, already encoded. An idle page costs
nothing and a busy one arrives as fast as it repaints.

**Two sockets, and that is the other half of the fix.** `CDPSession` serialises
everything behind one lock, so a click queued behind an in-flight capture waited
up to 115 ms before it was even sent — on top of the POST and the wait for the
next frame. Frames now have their own connection, so the command socket is idle
when a click arrives and answers in ~3 ms.

**Why this is not `CDPSession`.** That client documents, in as many words, that
it does not subscribe to events and that a queue of events nobody reads is a
leak in a process that stays up all day. That is the right design for a client
issuing a dozen commands a minute, and the wrong one for a frame pump. So this
is a reader thread that consumes events and drops commands' replies on the
floor — the inverse trade — and the two share the part worth sharing: the
websocket frame codec, which is a pure function with exhaustive tests behind it.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from typing import Any

# Private by name, shared by intent: the codec and the handshake are the tested,
# fiddly part of talking CDP, and a second copy of them is a second place for a
# continuation-frame bug to hide.
from genesis.tradingview.cdp import CDPSession, CDPUnavailable, _OP_CLOSE, _OP_PING, _OP_PONG, _OP_TEXT, encode_frame

log = logging.getLogger(__name__)

__all__ = ["Screencast"]

#: Take every other painted frame.
#:
#: Measured on a TradingView chart, 2026-09-20: at 1 the page delivers ~43 fps
#: and the daemon spends **49% of a core** doing nothing but decoding and
#: re-chunking them — on a process that also runs the fleet. At 2 it is ~21 fps,
#: which is above the rate a person can tell apart from smooth, for half of
#: everything: half the encode in Chromium (dropped frames are never encoded at
#: all), half the daemon, half the decode in the shell.
#:
#: This is the knob to turn if the panel ever looks choppy, and the one to turn
#: the other way if the UI around it does.
EVERY_NTH = 2


class Screencast:
    """A live JPEG feed of one page, newest frame always available.

    Readers ask for anything newer than the sequence number they last saw, so a
    slow reader skips frames instead of falling behind — which for video is the
    only correct backpressure.
    """

    def __init__(self, websocket_url: str, *, quality: int = 60) -> None:
        self.websocket_url = websocket_url
        self.quality = quality
        self._socket = CDPSession(websocket_url, timeout=10.0)
        self._send_lock = threading.Lock()
        self._new = threading.Condition()
        self._frame: bytes | None = None
        self._seq = 0
        self._id = 10_000  # far from the command socket's ids; they are separate anyway
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle ----------------------------------------------------

    def start(self, width: int, height: int) -> Screencast:
        self._socket.connect()
        self._thread = threading.Thread(target=self._read, name="screencast", daemon=True)
        self._thread.start()
        self._command("Page.enable")
        self.resize(width, height)
        return self

    def resize(self, width: int, height: int) -> None:
        """Restart the cast at a new size.

        `maxWidth`/`maxHeight` are a bounding box Chromium fits the viewport
        into, so they must match the viewport `Emulation` was overridden to or
        the frames come back letterboxed and every click lands off by the
        margin.
        """
        self._command("Page.stopScreencast")
        self._command(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": self.quality,
                "maxWidth": int(width),
                "maxHeight": int(height),
                "everyNthFrame": EVERY_NTH,
            },
        )

    def stop(self) -> None:
        self._stop.set()
        try:
            self._command("Page.stopScreencast")
        except CDPUnavailable:
            pass
        self._socket.close()
        with self._new:
            self._new.notify_all()

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    # -- the wire -----------------------------------------------------

    def _command(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Fire a command. The reply lands in the reader thread and is dropped.

        Nothing sent on this socket has an answer worth reading: starting,
        stopping and acknowledging all fail visibly as an absence of frames,
        which is the only symptom that matters and the one a reader already
        handles.
        """
        sock = self._socket._sock
        if sock is None:
            raise CDPUnavailable("screencast socket is closed")
        with self._send_lock:
            self._id += 1
            payload = json.dumps({"id": self._id, "method": method, "params": params or {}}).encode()
            try:
                sock.sendall(encode_frame(payload))
            except OSError as exc:
                raise CDPUnavailable(f"{method} failed on the screencast socket: {exc}") from exc

    def _read(self) -> None:
        reader = self._socket._reader
        sock = self._socket._sock
        if reader is None or sock is None:
            return
        while not self._stop.is_set():
            try:
                opcode, raw = reader.read_message()
            except (CDPUnavailable, OSError, ValueError) as exc:
                log.info("screencast socket ended: %s", exc)
                break
            if opcode == _OP_PING:
                with self._send_lock:
                    sock.sendall(encode_frame(raw, _OP_PONG))
                continue
            if opcode == _OP_CLOSE:
                break
            if opcode != _OP_TEXT:
                continue
            try:
                message = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if message.get("method") != "Page.screencastFrame":
                continue  # a command reply, or an event nobody asked for
            params = message.get("params", {})
            # The ack is not optional: Chromium sends at most one unacknowledged
            # frame, so a cast that stops acking stops after exactly one frame.
            # That failure looks like a frozen page, not like a protocol bug.
            session_id = params.get("sessionId")
            if session_id is not None:
                try:
                    self._command("Page.screencastFrameAck", {"sessionId": session_id})
                except CDPUnavailable:
                    break
            data = params.get("data")
            if not data:
                continue
            with self._new:
                self._frame = base64.b64decode(data)
                self._seq += 1
                self._new.notify_all()
        self._stop.set()
        with self._new:
            self._new.notify_all()

    # -- what a reader asks for ---------------------------------------

    def next_frame(self, since: int, timeout: float = 1.0) -> tuple[int, bytes] | None:
        """The newest frame, if it is newer than `since`. `None` on timeout.

        A timeout is not a failure — it is a page that has not repainted, which
        is the normal state of a page being read. It exists so the caller gets
        control back often enough to notice its own client has gone.
        """
        with self._new:
            if self._seq <= since:
                self._new.wait(timeout)
            if self._seq <= since or self._frame is None:
                return None
            return self._seq, self._frame
