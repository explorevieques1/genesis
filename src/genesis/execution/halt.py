# Spec: Genesis Markdown/50-Risk/Kill Switch.md
"""The halt flag, as a file both processes can read.

The kill switch is a separate process with no bus (Kill Switch §Design
constraints), so the flag it raises has to live somewhere the daemon reads
without asking it: ``<execution.state_dir>/halt.json``, replaced atomically.

Stdlib only. The kill switch imports this and must not drag the daemon in.

**Unreadable is engaged.** A corrupt or unreadable flag file means nobody can
say whether trading was halted, and the risk engine fails closed (Safety
Invariants §3) -- so :func:`read` raises and callers treat that as halted.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["HaltUnreadable", "clear", "engage", "path_for", "read"]


class HaltUnreadable(Exception):
    """The flag exists but cannot be read. Treat as halted."""


def path_for(state_dir: Path) -> Path:
    return Path(state_dir).expanduser() / "halt.json"


def read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"engaged": False, "history": []}
    try:
        doc = json.loads(path.read_text())
        if not isinstance(doc, dict) or not isinstance(doc.get("engaged"), bool):
            raise ValueError("no boolean `engaged`")
        return doc
    except (OSError, ValueError) as exc:
        raise HaltUnreadable(f"{path}: {exc}") from exc


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, path)


def engage(path: Path, *, level: str, trigger: str, detail: str = "") -> dict[str, Any]:
    """Raise the flag. Idempotent: an engaged halt keeps its id; a flatten
    request on top of a halt upgrades the level."""
    try:
        doc = read(path)
    except HaltUnreadable:
        doc = {"engaged": False, "history": []}
    now = datetime.now(UTC).isoformat()
    if doc.get("engaged"):
        if level == "flatten" and doc.get("level") != "flatten":
            doc["level"] = "flatten"
            doc.setdefault("history", []).append({"at": now, "event": "upgraded", "trigger": trigger})
            _write(path, doc)
        return doc
    doc.update({
        "engaged": True, "id": f"halt_{secrets.token_hex(6)}", "level": level,
        "trigger": trigger, "detail": detail, "at": now,
    })
    doc.setdefault("history", []).append({"at": now, "event": "engaged", "level": level, "trigger": trigger})
    _write(path, doc)
    return doc


def clear(path: Path, *, by: str, resolution: str) -> dict[str, Any]:
    """Lower the flag. Dashboard-only (Kill Switch §Recovery); the caller checks that."""
    doc = read(path)
    now = datetime.now(UTC).isoformat()
    doc.setdefault("history", []).append({"at": now, "event": "cleared", "by": by, "resolution": resolution})
    doc.update({"engaged": False, "cleared_at": now})
    _write(path, doc)
    return doc
