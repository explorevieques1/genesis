# Spec: Genesis Markdown/30-MCP/genesis-tradingview-mcp.md
"""Control of the TradingView Desktop app, and a read path into its live feed.

Three modules, deliberately layered so that only the top one needs a GUI:

``cdp``
    Raw Chrome DevTools Protocol over a hand-written WebSocket client. Owns the
    denied-surface reflex that keeps every expression away from the Trade panel.
``surface``
    The chart as a handful of operations, each write verified by a read-back.
    Testable against a fake session — no Electron, no network.
``server``
    The MCP server process. A thin adapter, run as ``genesis-tradingview-mcp``.
"""

from genesis.tradingview.cdp import CDPUnavailable, ForbiddenSurface

__all__ = ["CDPUnavailable", "ForbiddenSurface"]
