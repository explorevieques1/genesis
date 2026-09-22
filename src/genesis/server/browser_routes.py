# Spec: Genesis Markdown/10-Architecture/Web Access.md §The presentation surface
"""The `WEB` panel's five doors into the browser beside the daemon.

    GET  /v1/browser/state              -> where it is, and what back/forward would do
    GET  /v1/browser/stream?w=&h=       -> multipart JPEG, straight into an <img>
    POST /v1/browser/navigate           -> {url} | {action: back|forward|reload}
    POST /v1/browser/input              -> one mouse, wheel, text or key event
    POST /v1/browser/close              -> shut the browser down

**The stream is an `<img>`, not a socket.** `multipart/x-mixed-replace` is
thirty years old and every browser renders it natively, which means the panel
holds no decode loop, no frame buffer and no reconnect logic — the three places
a hand-rolled video path goes wrong. [[UI Stack]] §7 says live state arrives on
the WebSocket and never by polling; this is neither. It is one long-lived
response carrying pixels, and the rule it is under is the one about not
inventing a second transport for something the platform already does.

**No agent may call any of this.** [[Web Access]] §Wiring puts presentation
outside the tool list on purpose, and its acceptance criteria say an agent
declaring `display.*` fails at boot. These are HTTP routes for the panel, with
no MCP server, no capability and no orchestrator verb behind them — so the only
thing that can drive this browser is a person clicking in the panel. That is
also the whole of the answer to the obvious worry: a browser can reach a broker
portal, and [[Safety Invariants]] §1 says nothing reaches a broker without the
risk engine. It holds here because Genesis is not the one clicking. **Wiring an
agent to `/v1/browser/input` would break that invariant**, and is the one change
to this file that needs the note reopened first.
"""

from __future__ import annotations

import logging
from typing import Any

from genesis.browser import session as browser_session
from genesis.browser.session import BrowserUnavailable
from genesis.browser.session import close as browser_close

log = logging.getLogger(__name__)

#: How long a reader waits for the page to repaint before checking whether its
#: own client is still there. Not a frame rate — frames are pushed, and an idle
#: page correctly sends none at all.
IDLE_CHECK_SEC = 1.0

BOUNDARY = "genesisframe"


def browser_routes() -> list[Any]:
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route

    async def state_route(request: Request) -> JSONResponse:
        try:
            state = await run_in_threadpool(lambda: browser_session().state())
        except BrowserUnavailable as exc:
            return JSONResponse({"available": False, "reason": exc.reason})
        except Exception as exc:  # noqa: BLE001 — a browser that will not start is an answer
            log.warning("browser state failed: %s", exc)
            return JSONResponse({"available": False, "reason": f"{type(exc).__name__}: {exc}"})
        return JSONResponse({"available": True, **state})

    async def stream_route(request: Request) -> Any:
        width = _int(request.query_params.get("w"), 1440)
        height = _int(request.query_params.get("h"), 900)
        try:
            session = await run_in_threadpool(browser_session)
            await run_in_threadpool(session.resize, width, height)
            cast = await run_in_threadpool(session.screencast)
        except BrowserUnavailable as exc:
            return JSONResponse({"available": False, "reason": exc.reason})
        except Exception as exc:  # noqa: BLE001
            log.warning("browser stream failed to start: %s", exc)
            return JSONResponse({"available": False, "reason": f"{type(exc).__name__}: {exc}"})

        async def frames():
            seq = 0
            while True:
                # The panel closing is the normal end of this loop, and the
                # only one: without this check a closed panel leaves a reader
                # attached for as long as the daemon lives, and a day of
                # opening panels is a day of leaking them.
                if await request.is_disconnected():
                    return
                if not cast.alive:
                    log.info("browser stream ended: the screencast stopped")
                    return
                got = await run_in_threadpool(cast.next_frame, seq, IDLE_CHECK_SEC)
                if got is None:
                    continue  # the page has not repainted; nothing to send
                seq, jpeg = got
                yield (
                    f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode() + jpeg + b"\r\n"

        return StreamingResponse(
            frames(),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def navigate_route(request: Request) -> JSONResponse:
        data = await _json(request)
        if data is None:
            return JSONResponse({"ok": False, "reason": "content-type must be application/json"}, 415)
        action = str(data.get("action", "")).strip()
        try:
            session = await run_in_threadpool(browser_session)
            url = ""
            if action == "back":
                await run_in_threadpool(session.history, -1)
            elif action == "forward":
                await run_in_threadpool(session.history, 1)
            elif action == "reload":
                await run_in_threadpool(session.reload)
            elif action:
                return JSONResponse({"ok": False, "reason": f"unknown action {action!r}"}, 400)
            else:
                url = await run_in_threadpool(session.navigate, str(data.get("url", "")))
        except BrowserUnavailable as exc:
            return JSONResponse({"ok": False, "reason": exc.reason}, 503)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "reason": f"{type(exc).__name__}: {exc}"}, 400)
        # Deliberately no state read here. For the ~200ms a navigation is in
        # flight the page target is detaching and `Page.getNavigationHistory`
        # answers *"Not attached to an active page"* — so a route that read
        # back immediately would report a failure on every successful
        # navigation. The panel asks for state on its own clock instead.
        log.info("operator: browser -> %s", url or action)
        return JSONResponse({"ok": True, "url": url})

    async def input_route(request: Request) -> JSONResponse:
        data = await _json(request)
        if data is None:
            return JSONResponse({"ok": False, "reason": "content-type must be application/json"}, 415)
        kind = str(data.get("kind", ""))
        try:
            session = await run_in_threadpool(browser_session)
            if kind == "text":
                await run_in_threadpool(session.text, str(data.get("value", "")))
            elif kind == "key":
                await run_in_threadpool(
                    lambda: session.key(str(data.get("name", "")), modifiers=_int(data.get("modifiers"), 0))
                )
            elif kind in ("move", "down", "up", "wheel"):
                await run_in_threadpool(
                    lambda: session.mouse(
                        kind,
                        float(data.get("x", 0)),
                        float(data.get("y", 0)),
                        button=str(data.get("button", "left")),
                        clicks=_int(data.get("clicks"), 1),
                        dx=float(data.get("dx", 0)),
                        dy=float(data.get("dy", 0)),
                        modifiers=_int(data.get("modifiers"), 0),
                    )
                )
            else:
                return JSONResponse({"ok": False, "reason": f"unknown input {kind!r}"}, 400)
        except BrowserUnavailable as exc:
            return JSONResponse({"ok": False, "reason": exc.reason}, 503)
        except (ValueError, TypeError) as exc:
            return JSONResponse({"ok": False, "reason": str(exc)}, 400)
        return JSONResponse({"ok": True})

    async def close_route(request: Request) -> JSONResponse:
        await run_in_threadpool(browser_close)
        log.info("operator: browser closed")
        return JSONResponse({"ok": True})

    return [
        Route("/v1/browser/state", state_route),
        Route("/v1/browser/stream", stream_route),
        Route("/v1/browser/navigate", navigate_route, methods=["POST"]),
        Route("/v1/browser/input", input_route, methods=["POST"]),
        Route("/v1/browser/close", close_route, methods=["POST"]),
    ]


async def _json(request: Any) -> dict[str, Any] | None:
    if not request.headers.get("content-type", "").startswith("application/json"):
        return None
    try:
        data = await request.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
