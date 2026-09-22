# Spec: Genesis Markdown/30-MCP/genesis-tradingview-mcp.md
"""The transport, and the one refusal that must not depend on a GUI to test."""

from __future__ import annotations

import json
import struct

import pytest

from genesis.errors import DegradedError, FatalError
from genesis.tradingview.cdp import (
    CDPSession,
    CDPUnavailable,
    ForbiddenSurface,
    _FrameReader,
    encode_frame,
)


class FakeSocket:
    """A socket that hands back frames somebody already encoded."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def recv(self, _n: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


def server_frame(payload: bytes, opcode: int = 0x1, final: bool = True) -> bytes:
    """A *server* frame: same as a client frame, unmasked."""
    header = bytearray([(0x80 if final else 0x00) | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header += struct.pack(">H", length)
    else:
        header.append(127)
        header += struct.pack(">Q", length)
    return bytes(header) + payload


# ----------------------------------------------------------------------
# Framing — the part that can be tested exhaustively with no Electron
# ----------------------------------------------------------------------


def test_client_frames_are_masked() -> None:
    """Chromium closes the connection on an unmasked client frame.

    RFC 6455 requires it, and Chromium enforces it rather than tolerating it —
    so this is not pedantry, it is the difference between a session and a
    disconnect.
    """
    frame = encode_frame(b"hello")
    assert frame[1] & 0x80, "the mask bit must be set"
    mask = frame[2:6]
    unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(frame[6:]))
    assert unmasked == b"hello"


@pytest.mark.parametrize("size", [0, 1, 125, 126, 127, 65535, 65536, 200_000])
def test_every_length_encoding_round_trips(size: int) -> None:
    """The three length forms, including both boundaries.

    125/126 and 65535/65536 are where a hand-written codec goes wrong, and a
    screenshot is comfortably into the third form.
    """
    payload = b"x" * size
    frame = encode_frame(payload)
    mask = frame[-size - 4 : len(frame) - size] if size else frame[-4:]
    body = frame[len(frame) - size :] if size else b""
    unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(body))
    assert unmasked == payload


def test_a_fragmented_message_is_reassembled() -> None:
    """A screenshot is megabytes of base64, and Chromium does fragment it.

    A reader that assumed one frame per message would pass every small test
    and fail on the single tool whose whole purpose is a large payload.
    """
    reader = _FrameReader(
        FakeSocket(
            [
                server_frame(b"{\"a\":", opcode=0x1, final=False),
                server_frame(b"1}", opcode=0x0, final=True),
            ]
        )
    )
    opcode, payload = reader.read_message()
    assert opcode == 0x1
    assert json.loads(payload) == {"a": 1}


def test_a_socket_closing_mid_frame_is_degraded_not_a_crash() -> None:
    reader = _FrameReader(FakeSocket([server_frame(b"partial")[:3]]))
    with pytest.raises(CDPUnavailable):
        reader.read_message()


# ----------------------------------------------------------------------
# Hard rule 1 — nothing here can reach a broker
# ----------------------------------------------------------------------


class _Refuser(CDPSession):
    """A session whose socket would fail if anything actually reached it."""

    def __init__(self) -> None:
        super().__init__("ws://127.0.0.1:9222/x")
        self.sent: list[str] = []

    def send(self, method, params=None):  # type: ignore[override]
        self.sent.append(method)
        raise AssertionError("this expression must never have been sent")


@pytest.mark.parametrize(
    "expression",
    [
        "document.querySelector('.js-order-button').click()",
        "document.querySelector('[data-name=\"trade-panel\"]')",
        "window.placeOrder({side:'buy'})",
        "document.querySelector('#orderTicket')",
        "DOCUMENT.QUERYSELECTOR('.BuyButton')",
    ],
)
def test_an_expression_reaching_the_trade_surface_is_refused_before_dispatch(
    expression: str,
) -> None:
    """Refused *before* the socket, because a check on the result is too late.

    Hard rule 1 is about what may be reached. By the time a result exists, the
    click has happened.
    """
    session = _Refuser()
    with pytest.raises(ForbiddenSurface):
        session.evaluate(expression)
    assert session.sent == []


def test_the_refusal_is_fatal_and_the_absence_is_degraded() -> None:
    """Two failures that must never be confused for one another.

    ``CDPUnavailable`` means the chart is closed — proceed without it, which
    at 3am is the normal case. ``ForbiddenSurface`` means something tried to
    reach the order path, and something that aborts must not be retried into
    eventually working.
    """
    assert issubclass(CDPUnavailable, DegradedError)
    assert issubclass(ForbiddenSurface, FatalError)


def test_an_innocent_expression_is_not_caught() -> None:
    """A tripwire that fires on innocent input is one somebody switches off."""
    session = _Refuser()
    with pytest.raises(AssertionError):  # got past the guard, reached the socket
        session.evaluate("window.TradingViewApi.activeChart().symbol()")
