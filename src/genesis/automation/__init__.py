# Spec: Genesis Markdown/60-UI/Automation.md
"""Workflows: authored on a canvas, compiled to cadences, run by the one daemon."""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["attach", "attached", "open_store"]

#: The daemon and gateway in this process, if one is running. Set by the CLI
#: after the fleet builds; read by the HTTP routes to apply a save immediately.
_ATTACHED: dict[str, Any] = {}


def attach(daemon: Any, gateway: Any = None) -> None:
    _ATTACHED.update(daemon=daemon, gateway=gateway)


def attached() -> tuple[Any, Any]:
    return _ATTACHED.get("daemon"), _ATTACHED.get("gateway")


def open_store(config: Any = None):  # noqa: ANN201
    """The workflow store, beside every other store -- path from config."""
    from genesis.automation.store import WorkflowStore
    from genesis.config import load_config

    config = config or load_config()
    return WorkflowStore(Path(config.memory.db_path).expanduser().parent / "workflows.db")
