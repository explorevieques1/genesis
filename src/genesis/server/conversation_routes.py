# Spec: Genesis Markdown/60-UI/Ask Genesis.md
"""Saved conversations for the Ask Genesis panel.

Reads plus one write -- delete. It sits beside ``canvas_routes`` rather than in
``reads.py`` for the same reason that module does: a listing and a deletion in
one file is a file where the next deletion gets added without anyone noticing
it was a deletion.

The write here is as small and as safe as a write gets -- it removes the
trader's own chat scrollback and nothing else. This module imports no execution
code; there is no order path to route around.

The turns themselves are written by ``app._run`` as a side effect of a command
that carried a ``conversation`` id, not here -- a conversation grows only
through the command layer, so there is exactly one place a turn is minted.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

__all__ = ["conversation_routes", "conversation_store"]

log = logging.getLogger(__name__)


def conversation_store():  # noqa: ANN201 - concrete type is an impl detail
    """Path from config, like every other store -- see ``reads._memory_db``."""
    from genesis.config import load_config
    from genesis.memory.conversations import ConversationStore

    memory = Path(load_config().memory.db_path).expanduser().parent
    return ConversationStore(path=memory / "conversations.db")


def conversation_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def _guard(fn):  # noqa: ANN001, ANN202
        async def wrapped(request: Request) -> Any:
            try:
                return JSONResponse(await fn(request))
            except Exception as exc:  # noqa: BLE001
                log.exception("conversation route failed: %s", fn.__name__)
                return JSONResponse(
                    {"available": False, "reason": f"{type(exc).__name__}: {exc}"},
                    status_code=500,
                )

        wrapped.__name__ = fn.__name__
        return wrapped

    @_guard
    async def conversations(request: Request) -> dict[str, Any]:
        return {"available": True, "conversations": conversation_store().list()}

    @_guard
    async def conversation(request: Request) -> dict[str, Any]:
        found = conversation_store().get(request.path_params["conversation_id"])
        if found is None:
            return {"available": True, "conversation": None}
        return {"available": True, "conversation": found}

    @_guard
    async def delete_conversation(request: Request) -> dict[str, Any]:
        removed = conversation_store().delete(request.path_params["conversation_id"])
        return {"ok": removed}

    return [
        Route("/v1/conversations", conversations),
        Route("/v1/conversations/{conversation_id}", conversation),
        Route("/v1/conversations/{conversation_id}/delete", delete_conversation, methods=["POST"]),
    ]
