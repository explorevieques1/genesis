# Spec: Genesis Markdown/60-UI/Notebook.md · 60-UI/Nodes.md
"""The notebook surface: the vault, its links, and the writes that edit it.

Kept apart from ``reads.py`` for the reason ``canvas_routes`` is: these
**act**. Afferent and efferent are structurally different paths (Biological
Design §2), and a module where a listing and a mutation sit in one list is one
where the next mutation gets added without anyone noticing it was a mutation.

Everything here is one door, and that is the parity rule ([[Operating Model]]
§1): the panel calls these routes, the command line calls these routes, and an
agent writing a note calls these routes. There is no private channel for
Genesis. It also means the safety argument only has to hold in one place --
:meth:`Vault.resolve`, which every path below passes through.

Nothing here reaches an order path. It imports no execution code at all.
"""

from __future__ import annotations

import logging
from typing import Any

from genesis.errors import GenesisError

__all__ = ["notebook_routes"]

log = logging.getLogger(__name__)


def _open(name: str | None = None):
    """The active vault, or a named one. Paths from config, like every store."""
    from genesis.notebook.vault import registry

    return registry().open(name)


def _index(vault):  # noqa: ANN001, ANN202
    from genesis.notebook.links import LinkIndex

    return LinkIndex(vault)


def notebook_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def _guard(fn):  # noqa: ANN001, ANN202
        """A typed failure becomes a reported one. Never a 500, never silence."""
        async def wrapped(request: Request) -> Any:
            try:
                return JSONResponse(await fn(request))
            except FileNotFoundError as exc:
                # A vault that is not there is a *fact about the system*, not a
                # failed request — the path is the whole of what the operator
                # needs to fix it.
                return JSONResponse({"available": False,
                                     "reason": f"no vault at {exc}"})
            except GenesisError as exc:
                return JSONResponse({"ok": False, "available": False,
                                     "reason": exc.reason}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                log.exception("notebook route failed: %s", fn.__name__)
                return JSONResponse(
                    {"ok": False, "available": False,
                     "reason": f"{type(exc).__name__}: {exc}"},
                    status_code=500,
                )

        wrapped.__name__ = fn.__name__
        return wrapped

    def _vault(request: Request):  # noqa: ANN202
        return _open(request.query_params.get("vault"))

    # -- afferent ----------------------------------------------------------

    @_guard
    async def vaults(request: Request) -> dict[str, Any]:
        from genesis.notebook.vault import registry

        reg = registry()
        return {
            "available": True,
            "vaults": [v.to_dict() for v in reg.list()],
            "active": reg.active().name,
        }

    @_guard
    async def tree(request: Request) -> dict[str, Any]:
        """One level of the folder tree. Never the whole vault."""
        vault = _vault(request)
        path = request.query_params.get("path", "")
        return {
            "available": True, "vault": vault.name, "root": str(vault.root),
            "path": path, "entries": [e.to_dict() for e in vault.tree(path)],
        }

    @_guard
    async def note(request: Request) -> dict[str, Any]:
        """One note, its links resolved, and what links back to it."""
        from genesis.notebook.links import parse_links

        vault = _vault(request)
        rel = request.query_params.get("path", "")
        record = vault.read(rel)
        index = _index(vault)
        links = []
        for ref in parse_links(record.body):
            hit = index.resolve(ref.target, source=record.path)
            links.append({**ref.to_dict(), "resolved": hit.path,
                          "candidates": list(hit.candidates)})
        return {
            "available": True, "vault": vault.name, "note": record.to_dict(),
            "links": links, "backlinks": index.backlinks(record.path),
        }

    @_guard
    async def search(request: Request) -> dict[str, Any]:
        vault = _vault(request)
        query = request.query_params.get("q", "")
        return {"available": True, "vault": vault.name,
                "results": vault.search(query)}

    @_guard
    async def graph(request: Request) -> dict[str, Any]:
        """[[Nodes]]. Derived from the files every time, stored nowhere."""
        vault = _vault(request)
        params = request.query_params

        def flag(name: str, default: bool) -> bool:
            raw = params.get(name)
            return default if raw is None else raw not in ("0", "false", "no")

        index = _index(vault)
        data = index.graph(
            tags=flag("tags", False),
            attachments=flag("attachments", False),
            unresolved=flag("unresolved", True),
            orphans=flag("orphans", True),
            focus=params.get("focus") or None,
            depth=int(params.get("depth", 1) or 1),
        )
        return {"available": True, "vault": vault.name,
                "notes": len(index.notes), **data}

    @_guard
    async def rename_preview(request: Request) -> dict[str, Any]:
        """What a rename would rewrite. Shown before anything is written."""
        vault = _vault(request)
        return {"available": True, "changes": _index(vault).rename_preview(
            request.query_params.get("from", ""), request.query_params.get("to", ""),
        )}

    # -- efferent ----------------------------------------------------------

    @_guard
    async def save(request: Request) -> dict[str, Any]:
        body = await request.json()
        vault = _open(body.get("vault"))
        record = vault.write(str(body["path"]), str(body.get("body", "")),
                             by=str(body.get("by") or "operator"))
        return {"ok": True, "note": record.to_dict()}

    @_guard
    async def create(request: Request) -> dict[str, Any]:
        """What clicking an unresolved ``[[link]]`` calls."""
        body = await request.json()
        vault = _open(body.get("vault"))
        record = vault.create(str(body["path"]), str(body.get("body", "")))
        return {"ok": True, "note": record.to_dict()}

    @_guard
    async def append(request: Request) -> dict[str, Any]:
        """`note that ...` — appends to a note, creating it if absent."""
        body = await request.json()
        vault = _open(body.get("vault"))
        path = str(body.get("path") or vault.daily_path())
        record = vault.append(path, str(body["text"]))
        return {"ok": True, "note": record.to_dict()}

    @_guard
    async def folder(request: Request) -> dict[str, Any]:
        body = await request.json()
        vault = _open(body.get("vault"))
        return {"ok": True, "entry": vault.mkdir(str(body["path"])).to_dict()}

    @_guard
    async def rename(request: Request) -> dict[str, Any]:
        """Move the file, then repoint the links — in that order.

        The index is built *before* the move so it still sees the old path, and
        the rewrite runs after so a failed move never leaves links pointing at a
        note that was not renamed. ``rewrite`` is the caller's decision because
        the preview is what they were shown.
        """
        body = await request.json()
        vault = _open(body.get("vault"))
        src, dst = str(body["from"]), str(body["to"])
        index = _index(vault) if body.get("rewrite", True) else None
        moved = vault.move(src, dst)
        rewritten = index.rewrite_links(src, moved) if index else 0
        return {"ok": True, "path": moved, "rewritten": rewritten}

    @_guard
    async def delete(request: Request) -> dict[str, Any]:
        body = await request.json()
        vault = _open(body.get("vault"))
        return {"ok": True, "path": vault.delete(str(body["path"]))}

    @_guard
    async def add_vault(request: Request) -> dict[str, Any]:
        from pathlib import Path

        from genesis.notebook.vault import registry

        body = await request.json()
        ref = registry().add(str(body["name"]), Path(str(body["path"])))
        return {"ok": True, "vault": ref.to_dict()}

    @_guard
    async def select_vault(request: Request) -> dict[str, Any]:
        from genesis.notebook.vault import registry

        body = await request.json()
        return {"ok": True, "vault": registry().select(str(body["name"])).to_dict()}

    @_guard
    async def forget_vault(request: Request) -> dict[str, Any]:
        """Forget the path. Deletes nothing on disk, ever."""
        from genesis.notebook.vault import registry

        body = await request.json()
        registry().forget(str(body["name"]))
        return {"ok": True}

    return [
        Route("/v1/notebook/vaults", vaults),
        Route("/v1/notebook/tree", tree),
        Route("/v1/notebook/note", note),
        Route("/v1/notebook/search", search),
        Route("/v1/notebook/graph", graph),
        Route("/v1/notebook/rename/preview", rename_preview),
        Route("/v1/notebook/save", save, methods=["POST"]),
        Route("/v1/notebook/create", create, methods=["POST"]),
        Route("/v1/notebook/append", append, methods=["POST"]),
        Route("/v1/notebook/folder", folder, methods=["POST"]),
        Route("/v1/notebook/rename", rename, methods=["POST"]),
        Route("/v1/notebook/delete", delete, methods=["POST"]),
        Route("/v1/notebook/vaults/add", add_vault, methods=["POST"]),
        Route("/v1/notebook/vaults/select", select_vault, methods=["POST"]),
        Route("/v1/notebook/vaults/forget", forget_vault, methods=["POST"]),
    ]
