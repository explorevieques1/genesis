# Spec: Genesis Markdown/60-UI/UI Stack.md §7 Transport
"""The local HTTP + WebSocket surface the UI talks to. Loopback only."""

from __future__ import annotations

__all__ = ["build_app", "serve"]


def __getattr__(name: str):  # noqa: ANN202
    if name in ("build_app", "serve", "EventBus"):
        from genesis.server import app as _app

        return getattr(_app, name)
    raise AttributeError(name)
