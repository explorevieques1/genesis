# Spec: Genesis Markdown/30-MCP/genesis-tradingview-mcp.md
"""genesis-tradingview-mcp — the MCP server that drives the desktop app.

A thin adapter over :mod:`genesis.tradingview.surface`. It owns the tool
surface, the session lifecycle, and nothing else; every behaviour worth testing
lives one module down where it can be tested without a GUI.

What this server exposes, and what it deliberately does not
----------------------------------------------------------
The note lists three groups of tools. All three are here.

**Navigation and Read — built.** ``open_symbol``, ``set_timeframe``, ``quote``,
``ohlcv``, ``watchlist``, ``screenshot``, plus ``self_test`` and ``status``.
``quote`` is one page evaluation, not three: it is the call a person waits on,
and three socket round trips for symbol, timeframe and last price was three
times the latency for the same information.

**Scripts — built.** ``write_pine``, ``add_to_chart``, ``read_pine``. Same
editor and same read-back as the markup path; what differs is only whether the
Pine came from ``compile_pine`` or from words. Pine has a door to a broker the
Trade panel rule never covered — a ``strategy()`` script can be connected to a
broker integration and traded — so ``surface.refuse_strategy`` fires on the
source before it reaches the socket. Genesis draws indicators.

**Markup — built, on top of the read half.** ``apply_markup`` and
``clear_markup`` compile a Markup Spec to Pine with
:mod:`genesis.charting.pine` -- the *one* compiler, shared with
genesis-charting-mcp rather than reimplemented here -- load it through the
editor, and then **read the chart's legend back** to confirm it compiled. A
write that cannot be perceived returns ``degraded``, never ``ok``.

That ordering was not a compromise and it paid off literally: *proprioception
before ambition*. The sense built first is the sense that now verifies the
actuator.

**No tool touches the Trade panel.** Hard rule 1, enforced three ways: no tool
here takes a side, a size or an order as an argument; every expression is
checked against the denied-surface list in :mod:`genesis.tradingview.cdp`
before it is sent; and ``userGesture`` is never set, so nothing can synthesise
the click a broker widget requires. A test enumerates the tool surface and
fails if an order-shaped tool appears.

Run it: ``genesis-tradingview-mcp`` (stdio). It is registered in the gateway
catalogue as ``genesis-tradingview``, disabled by default — it needs the app
running with a debugging port, which is a desk-hours condition, not a daemon
one.
"""

from __future__ import annotations

import base64
import functools
from typing import Any

from genesis.tradingview.cdp import (
    DEFAULT_PORT,
    CDPSession,
    CDPUnavailable,
    ForbiddenSurface,
    chart_target,
    version,
)
from genesis.tradingview.surface import ChartSurface, load_selectors

__all__ = ["build_server", "main"]


class _Connection:
    """One lazily-opened CDP session, reopened when the app comes back.

    Lazy because the server must start with TradingView closed. Hard rule 4 is
    *degrade, never block*: a server that refused to start without a GUI would
    make every allow-listed agent fail at boot rather than proceed without a
    chart, which is the opposite of what the rule asks for.

    Reopened rather than held forever because a person closes and reopens
    TradingView during a day, and a session that only worked until the first
    restart would be a server that appears to break at lunchtime.
    """

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self._session: CDPSession | None = None
        self._selectors = load_selectors()

    def surface(self) -> ChartSurface:
        if self._session is None:
            self._session = CDPSession(chart_target(self.port).websocket_url).connect()
        return ChartSurface(self._session, self._selectors)

    def drop(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None


def _unavailable(exc: CDPUnavailable) -> dict[str, Any]:
    """The shape every tool returns when the app is not there.

    ``unavailable`` rather than an error, because the note says so: the tool
    returns unavailable and *the agent proceeds without it*. An exception here
    would travel up as a task failure and stop work that had nothing to do with
    the chart.
    """
    return {
        "ok": False,
        "unavailable": True,
        "degraded": True,
        "detail": str(exc),
        "hint": (
            "TradingView Desktop is closed or was started without "
            f"--remote-debugging-port={DEFAULT_PORT}."
        ),
    }


def build_server(connection: _Connection | None = None) -> Any:
    """Assemble the MCP server. Separated from :func:`main` so it is testable.

    The tool surface can then be enumerated in a unit test — which is how the
    acceptance criterion *"no defined tool can reach an order path, asserted by
    a test that enumerates the tool surface"* is actually met, rather than
    asserted in prose.
    """
    from mcp.server.mcpserver import MCPServer

    conn = connection or _Connection()
    server = MCPServer(
        name="genesis-tradingview",
        instructions=(
            "Drives the TradingView Desktop app and reads the live subscription "
            "already running in it. Prices read here are tier 2: fine for "
            "answering questions, never for sizing a position or setting a "
            "stop. No tool here can reach the Trade panel."
        ),
    )

    def _guarded(fn):
        """Every tool degrades on an absent app, and none swallow a refusal.

        ``ForbiddenSurface`` is re-raised on purpose. It means something tried
        to reach the order path; turning that into a polite ``{"ok": false}``
        would make the most important refusal in the server look like a chart
        being closed.
        """

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return fn(*args, **kwargs)
            except ForbiddenSurface:
                raise
            except CDPUnavailable:
                # A held session dies silently when the app restarts, and the
                # first call afterwards used to spend itself discovering that
                # -- the person asked once, got "unavailable", asked again,
                # got an answer. Dropping and retrying once turns that into a
                # reconnect nobody sees. Retried once only: if the app really
                # is closed, the second attempt fails on the HTTP probe in
                # milliseconds rather than hanging.
                conn.drop()
            try:
                return fn(*args, **kwargs)
            except ForbiddenSurface:
                raise
            except CDPUnavailable as exc:
                conn.drop()
                return _unavailable(exc)

        return wrapper

    # -- Navigation ----------------------------------------------------

    @server.tool()
    @_guarded
    def open_symbol(symbol: str) -> dict[str, Any]:
        """Switch the active chart to a symbol, and confirm it took effect."""
        return conn.surface().set_symbol(symbol).as_dict()

    @server.tool()
    @_guarded
    def set_timeframe(timeframe: str) -> dict[str, Any]:
        """Set the chart's timeframe (1m … 1M), and confirm it took effect."""
        return conn.surface().set_timeframe(timeframe).as_dict()

    # -- Read ----------------------------------------------------------

    @server.tool()
    @_guarded
    def quote() -> dict[str, Any]:
        """Last price and session values for the charted symbol.

        Tier 2 — the live subscription you already pay for. Hard rule 3: never
        the risk engine's price source. A quote scraped from a GUI answers
        "what's the high of day"; it does not size a position.
        """
        seen = conn.surface().snapshot() or {}
        return {
            "ok": True,
            "tier": 2,
            "source": "tradingview-desktop",
            "never_for": "sizing, stops, or any pre-trade check",
            "symbol": seen.get("symbol"),
            "timeframe": seen.get("timeframe"),
            "quote": seen.get("quote"),
        }

    @server.tool()
    @_guarded
    def watchlist() -> dict[str, Any]:
        """The symbols in your watchlist."""
        return {"ok": True, "symbols": conn.surface().watchlist()}

    @server.tool()
    @_guarded
    def ohlcv(bars: int = 500) -> dict[str, Any]:
        """Bars for the charted symbol, out of the live subscription.

        The second reason this server exists: real-time data is the cost
        bottleneck, and a subscription is already running. Computing a level
        from these bars is milliseconds; buying the same tick twice is not.

        Tier 2. Hard rule 3: never the risk engine\'s price source.
        """
        frame = conn.surface().ohlcv(bars) or {}
        return {
            "ok": bool(frame.get("bars")),
            "tier": 2,
            "source": "tradingview-desktop",
            "never_for": "sizing, stops, or any pre-trade check",
            **frame,
        }

    @server.tool()
    @_guarded
    def screenshot() -> dict[str, Any]:
        """A PNG of the current chart, base64-encoded.

        Read-back verification and vision input. This is the *sense* half of
        the server, and the reason the markup tools can be built safely later:
        an actuator whose effect can be seen is one whose failures are visible.
        """
        png = conn.surface().screenshot()
        return {
            "ok": True,
            "mime_type": "image/png",
            "bytes": len(png),
            "base64": base64.b64encode(png).decode(),
        }

    # -- Markup ---------------------------------------------------------
    #
    # Compile, don't click. No expression in this path converts a price into a
    # screen coordinate, which is what makes it incapable of drawing a level at
    # the wrong price. And no tool here takes a side, a size or a quantity --
    # a markup is a drawing, and hard rule 1 holds by argument shape.

    @server.tool()
    @_guarded
    def apply_markup(spec_id: str, align_chart: bool = True) -> dict[str, Any]:
        """Put a stored markup spec on the desktop chart as Genesis's indicator.

        Replaces the source of the one script Genesis owns, so nothing you drew
        by hand is touched. Reports ``degraded`` if the indicator does not appear
        in the chart legend -- sending the command is not evidence it worked.
        """
        from genesis.charting.store import SpecStore
        from genesis.tradingview.markup import MarkupSurface

        spec = SpecStore(_spec_db()).get(spec_id)
        if spec is None:
            return {"ok": False, "error": f"no markup spec {spec_id!r}"}
        return MarkupSurface(conn.surface()).apply(spec, align_chart=align_chart).as_dict()

    @server.tool()
    @_guarded
    def clear_markup() -> dict[str, Any]:
        """Remove Genesis's overlay, and only Genesis's overlay."""
        from genesis.tradingview.markup import MarkupSurface

        return MarkupSurface(conn.surface()).clear().as_dict()

    # -- Scripts --------------------------------------------------------
    #
    # The general-purpose half of "compile, don't click": `apply_markup`
    # writes a script Genesis compiled from a spec, these write one Genesis
    # composed from words. Same editor, same keystrokes, same read-back --
    # the note's "one mechanism, both requests".
    #
    # What is new here is that the text arrives from a model rather than from
    # `compile_pine`, and Pine has a second door to a broker that the Trade
    # panel rule never covered: a `strategy()` script can be connected to a
    # broker integration and traded. `surface.refuse_strategy` is the reflex
    # that closes it, on the source, before it reaches the socket. Genesis
    # draws indicators.

    @server.tool()
    @_guarded
    def write_pine(name: str, source: str, save: bool = True) -> dict[str, Any]:
        """Put a named Pine indicator in the editor, apply it, and confirm it drew.

        Refuses a `strategy()` script: those can be connected to a broker and
        traded, which is a path around the pre-trade risk engine. Indicators
        only.

        Returns ``degraded`` -- never ``ok`` -- if the script does not appear
        in the chart legend, which is the chart's own word that it compiled.
        """
        from genesis.tradingview.markup import wait_for_legend

        surface = conn.surface()
        if not surface.open_pine_editor():
            return {"ok": False, "degraded": True, "detail": "could not open the Pine editor"}
        if not surface.write_pine_source(source):
            return {"ok": False, "degraded": True, "detail": "could not write the script source"}
        if not surface.apply_pine():
            return {"ok": False, "degraded": True, "detail": "could not apply the script"}
        saved = surface.save_pine(name) if save else None
        seen = wait_for_legend(surface, name)
        if seen is None:
            return {
                "ok": False,
                "degraded": True,
                "saved": saved,
                "detail": (
                    f"{name!r} was sent but never appeared in the chart legend -- "
                    f"it most likely failed to compile. Read it back with read_pine."
                ),
            }
        return {"ok": True, "name": name, "saved": saved, "legend": seen}

    @server.tool()
    @_guarded
    def add_to_chart(name: str) -> dict[str, Any]:
        """Apply a script you already saved, by name, and confirm it drew."""
        from genesis.tradingview.markup import wait_for_legend

        surface = conn.surface()
        if not surface.add_saved_pine(name):
            return {
                "ok": False,
                "degraded": True,
                "detail": f"no saved script matching {name!r} in the indicators dialog",
            }
        seen = wait_for_legend(surface, name)
        if seen is None:
            return {
                "ok": False,
                "degraded": True,
                "detail": f"{name!r} was selected but did not appear in the chart legend",
            }
        return {"ok": True, "name": name, "legend": seen}

    @server.tool()
    @_guarded
    def read_pine() -> dict[str, Any]:
        """The source currently in the Pine editor, so Genesis can iterate on it.

        The sense that makes the script tools usable rather than blind: a
        compile error is something the chart knows and Genesis does not, and
        the only way back from one is to read what is actually there.
        """
        surface = conn.surface()
        surface.open_pine_editor()
        source = surface.read_pine_source()
        return {"ok": source is not None, "source": source}

    # -- Health --------------------------------------------------------

    @server.tool()
    @_guarded
    def self_test() -> dict[str, Any]:
        """Exercise every selector and report which no longer resolve.

        The fragility budget: this server automates somebody else's UI and will
        break on their updates. Agent — Watchdog runs this on a schedule and
        after any TradingView update, so a breakage arrives as a health report
        rather than as an agent quietly returning nothing.
        """
        return conn.surface().self_test()

    @server.tool()
    @_guarded
    def status() -> dict[str, Any]:
        """Is the app reachable, and what is it?"""
        info = version(conn.port)
        target = chart_target(conn.port)
        return {
            "ok": True,
            "browser": info.get("Browser"),
            "protocol_version": info.get("Protocol-Version"),
            "chart_url": target.url,
            "chart_title": target.title,
        }

    return server


def _spec_db() -> str:
    """Where markup specs live.

    Read from config rather than hardcoded so a test, a second install and the
    daemon all agree -- a markup path pointing at a different database than the
    agent that wrote the spec fails with "no such spec", which is a confusing
    way to say "wrong file".
    """
    try:
        from genesis.config import load_config

        return str(load_config().memory.db_path.parent / "charting.db")
    except Exception:  # noqa: BLE001 - a missing config must not break the server
        return "~/.genesis/memory/charting.db"


def main() -> None:
    """Entry point for ``genesis-tradingview-mcp``."""
    build_server().run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
