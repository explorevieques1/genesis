# Spec: Genesis Markdown/60-UI/Terminal.md · 30-MCP/MCP Gateway.md
"""Calling a tool by hand — the same door Genesis uses.

The read route in :mod:`genesis.server.reads` reports the *declared* catalogue
from config: names, capabilities, trust, tier. That is enough to render a menu
and deliberately cheap, because a page load must never open a session.

It is not enough to *call* anything. Argument shapes come from the live MCP
handshake — a server is authoritative about the shape of its own arguments and
nothing else (``mcp/discovery.py``) — so a form that asks for the right fields
needs a connected gateway.

**So the gateway is built on first use, not at start-up.** Connecting to
seventeen servers takes tens of seconds; paying that when the daemon boots
would make `genesis serve` feel broken, and paying it on a page load would make
a read the most expensive thing in the system. Opening a tool panel is the
honest moment to pay it: a person asked for one specific tool, and waiting is
what they expect.

**The operator is an agent.** Calls are attributed to ``operator``, which has
its own allow-list in ``mcp/build.py``. That is the whole point of this module:
a person driving the terminal by hand reaches exactly what the orchestrator
reaches, through exactly the same chokepoint — allow-list, SSRF guard, cache,
rate limit, fence, audit line. Nothing here re-implements a check, and nothing
here skips one. If this file ever grows a branch that bypasses
:meth:`Gateway.call`, the boundary has become two boundaries.

**Reads only.** A mutating tool is refused here even when the allow-list would
permit it. A command line whose muscle memory is "type, Enter" is precisely
where an accidental write happens, and Biological Design is explicit that
efferent paths need idempotency keys, authorisation and ordering — none of
which a search bar has. Writes come back behind the approval gate, as a
separate decision.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from genesis.server.reads import jsonable

__all__ = ["GATEWAY", "OPERATOR", "tool_routes"]

log = logging.getLogger(__name__)

#: Who the audit log records for a hand-driven call. Not "orchestrator" — the
#: grants are deliberately identical, but the *caller* is not, and a log that
#: cannot tell a person from a model is a log that cannot answer "who did
#: this?" on the one day it matters.
OPERATOR = "operator"

#: How long one hand-driven call may take. Above any single tool's own timeout,
#: because the gateway's per-tool timeout is the real limit; this only stops a
#: wedged socket from holding an HTTP worker forever.
CALL_TIMEOUT_SEC = 120.0


class _Holder:
    """The live gateway, built once, lazily, under a lock.

    The lock is not paranoia: opening two tool panels at once fires two
    requests, and building twice would spawn a second copy of every server
    subprocess. It is held across the whole build — a slow build makes the
    second caller wait for the first, which is correct, because the thing it
    would otherwise do is start its own.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gateway: Any = None
        self._failed: dict[str, str] = {}
        self._error: str | None = None

    def get(self) -> tuple[Any, str | None]:
        """``(gateway, error)``. Exactly one of them is set."""
        with self._lock:
            if self._gateway is None and self._error is None:
                try:
                    from genesis.mcp.build import build_gateway

                    build = build_gateway()
                    self._gateway = build.gateway
                    self._failed = dict(build.failed)
                    log.info("tool gateway ready · %s", build.summary())
                except Exception as exc:  # noqa: BLE001 - reported, never fatal
                    log.exception("tool gateway did not build")
                    self._error = f"{type(exc).__name__}: {exc}"
            return self._gateway, self._error

    @property
    def failed(self) -> dict[str, str]:
        return dict(self._failed)


#: One gateway per process, shared by every caller that needs one.
#:
#: Module level rather than per-route because there is now a second consumer --
#: the orchestrator's answer ladder (`server/analyst.py`) -- and building twice
#: would spawn a second copy of every MCP server subprocess. Seventeen servers
#: is not a thing to have two of by accident.
GATEWAY = _Holder()


def tool_routes() -> list[Route]:
    """One schema read and one call. Nothing else acts."""
    holder = GATEWAY

    async def _gateway() -> tuple[Any, str | None]:
        # Building spawns subprocesses and performs handshakes -- blocking, and
        # never on the event loop, or the socket stops serving every other
        # client while seventeen servers start.
        return await asyncio.get_running_loop().run_in_executor(None, holder.get)

    async def tool_schema(request: Request) -> JSONResponse:
        """One tool, as the *server* describes it: arguments included.

        This is what turns a catalogue row into a usable panel. The declared
        surface knows a tool is called ``get_company_facts``; only the server
        knows it wants a CIK and not a ticker.
        """
        tool_id = request.path_params["tool_id"]
        gateway, error = await _gateway()
        if gateway is None:
            return JSONResponse({
                "available": False,
                "reason": f"the MCP gateway did not build — {error}",
                "spec": "30-MCP/MCP Gateway.md",
            })

        spec = gateway.registry.find(tool_id) or gateway.registry.for_capability(tool_id)
        if spec is None:
            # An honest 200. The gateway is fine; this tool is not in it --
            # usually because its server failed to start, and saying which is
            # the difference between "broken" and "plug the drive back in".
            why = holder.failed.get(tool_id.partition(".")[0])
            return JSONResponse({
                "available": False,
                "reason": (
                    f"{tool_id} is not in the live catalogue"
                    + (f" — its server did not start: {why}" if why else
                       " — it is declared in config but the server registered no such tool")
                ),
                "spec": "30-MCP/MCP Server Catalog.md",
            })

        granted = tool_id in set(gateway.tools_for(OPERATOR)) or spec.id in set(
            gateway.tools_for(OPERATOR)
        )
        return JSONResponse(jsonable({
            "available": True,
            "tool": {
                "id": spec.id,
                "server": spec.server,
                "name": spec.name,
                "capability": spec.capability,
                "description": spec.description,
                "input_schema": spec.input_schema or {},
                "mutating": spec.mutating,
                "trust": spec.trust.value,
                "tier": spec.tier,
                "timeout_sec": spec.timeout_sec,
                # Both reasons a Run button must be disabled, reported
                # separately, because they are different problems with
                # different fixes.
                "callable": granted and not spec.mutating,
                "refusal": (
                    "this tool writes — hand-driven calls are read-only"
                    if spec.mutating
                    else "" if granted else
                    "the operator allow-list does not grant this capability"
                ),
            },
        }))

    async def tool_call(request: Request) -> JSONResponse:
        """Run one tool. Everything load-bearing happens inside ``Gateway.call``."""
        body = await request.json()
        tool_id = str(body.get("tool", "")).strip()
        args = body.get("args") or {}
        if not tool_id:
            return JSONResponse({"ok": False, "reason": "no tool named"}, status_code=400)
        if not isinstance(args, dict):
            return JSONResponse({"ok": False, "reason": "args must be an object"}, status_code=400)

        gateway, error = await _gateway()
        if gateway is None:
            return JSONResponse({"ok": False, "reason": f"no gateway — {error}"})

        spec = gateway.registry.find(tool_id) or gateway.registry.for_capability(tool_id)
        if spec is None:
            return JSONResponse({"ok": False, "reason": f"{tool_id} is not in the catalogue"})
        # The refusal that is a rule rather than a check. Stated here AND
        # enforced by the operator allow-list holding no write patterns, so
        # deleting this line does not open the path -- which is the property a
        # safety rule should have.
        if spec.mutating:
            return JSONResponse({
                "ok": False,
                "tool": spec.id,
                "reason": (
                    f"{spec.id} writes. Hand-driven calls are read-only until the "
                    "approval gate covers them."
                ),
            })

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: gateway.call(OPERATOR, spec.id, args)
                ),
                timeout=CALL_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            return JSONResponse({
                "ok": False, "tool": spec.id,
                "reason": f"no answer in {CALL_TIMEOUT_SEC:.0f}s",
            })
        except Exception as exc:  # noqa: BLE001 - a typed failure is the answer
            reason = getattr(exc, "reason", None) or f"{type(exc).__name__}: {exc}"
            return JSONResponse({"ok": False, "tool": spec.id, "reason": str(reason)})

        return JSONResponse(jsonable({
            "ok": True,
            "tool": spec.id,
            "capability": spec.capability,
            "content": result.content,
            "structured": result.structured,
            "latency_ms": round(result.latency_ms, 1),
            # Present means the payload was wrapped on the way out. The panel
            # says so: a person reading fenced third-party text should know
            # that is what they are reading.
            "fenced": result.fence is not None,
            "trust": spec.trust.value,
        }))

    return [
        Route("/v1/mcp/tool/{tool_id}", tool_schema),
        Route("/v1/mcp/call", tool_call, methods=["POST"]),
    ]
