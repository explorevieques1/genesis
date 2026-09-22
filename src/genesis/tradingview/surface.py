# Spec: Genesis Markdown/30-MCP/genesis-tradingview-mcp.md
"""The chart, as a small set of operations. No MCP, no process, no I/O policy.

Split from :mod:`genesis.tradingview.server` so the behaviour that matters —
read back after every mutation, degrade rather than block, never construct an
expression that reaches the trade panel — is testable against a fake CDP
session. The MCP server on top of this is a thin adapter, which is where the
thinness should be: an MCP server that also holds the logic is a piece of logic
that can only be tested by spawning a subprocess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from genesis.tradingview.cdp import CDPUnavailable, ForbiddenSurface

__all__ = [
    "ChartSurface",
    "Selectors",
    "Verified",
    "load_selectors",
    "refuse_strategy",
]

_SELECTORS_PATH = Path(__file__).with_name("selectors.yaml")


class SessionLike(Protocol):
    """The slice of :class:`~genesis.tradingview.cdp.CDPSession` used here."""

    def evaluate(self, expression: str) -> Any: ...
    def screenshot(self) -> bytes: ...


@dataclass(frozen=True)
class Selectors:
    """Every page expression, loaded from one file. The fragility budget."""

    entries: dict[str, dict[str, str]]

    def expression(self, name: str, kind: str, value: Any = None) -> str:
        entry = self.entries.get(name)
        if entry is None or kind not in entry:
            raise KeyError(
                f"selectors.yaml has no {kind!r} expression for {name!r} — "
                f"the file is the whole surface, so add it there"
            )
        template = entry[kind]
        if value is None:
            return template
        # JSON, not string interpolation. The value reaches a JavaScript
        # evaluator, and a symbol is a user-supplied string: `json.dumps` is
        # what makes `"; doSomething(); "` a symbol nobody can find rather
        # than an expression.
        return template.replace("{value}", json.dumps(value))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.entries))


def load_selectors(path: Path | None = None) -> Selectors:
    raw = yaml.safe_load((path or _SELECTORS_PATH).read_text(encoding="utf-8")) or {}
    return Selectors(entries={k: dict(v) for k, v in raw.items()})


@dataclass(frozen=True)
class Verified:
    """The result of an action, and whether the app agreed it happened.

    ``degraded`` is set when the write returned without error and the read-back
    did not match. Hard rule 2: *a mismatch reports degraded; it never reports
    success.* The distinction is the whole point of the class — an actuator
    that cannot perceive its own effect is the configuration Biological Design
    calls dangerous, and "I sent the command" is not perception.
    """

    ok: bool
    value: Any = None
    degraded: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "degraded": self.degraded,
            "detail": self.detail,
        }


class ChartSurface:
    """Read and drive the chart. Everything a tool needs, and nothing more."""

    def __init__(self, session: SessionLike, selectors: Selectors | None = None) -> None:
        self._session = session
        self._selectors = selectors or load_selectors()

    # -- reads ---------------------------------------------------------

    def read(self, name: str) -> Any:
        return self._session.evaluate(self._selectors.expression(name, "read"))

    def symbol(self) -> Any:
        return self.read("symbol")

    def timeframe(self) -> Any:
        return self.read("timeframe")

    def quote(self) -> Any:
        return self.read("quote")

    def snapshot(self) -> Any:
        """Symbol, timeframe and quote in one round trip.

        The same three values the caller used to pay three socket round trips
        for. This is the read that runs most often and the one a person is
        sitting in front of waiting for, so it is the one worth collapsing.
        """
        return self.read("snapshot")

    def ohlcv(self, bars: int = 500) -> Any:
        """Bars the chart already holds, out of the live subscription.

        Tier 2, like every read here: fine for computing a level, never the
        risk engine's price source (hard rule 3). The point is cost, not
        compute -- the app is already paying for this feed.
        """
        return self._session.evaluate(
            self._selectors.expression("ohlcv", "read", max(1, int(bars)))
        )

    def watchlist(self) -> Any:
        return self.read("watchlist")

    def screenshot(self) -> bytes:
        return self._session.screenshot()

    # -- writes, each verified by a read -------------------------------

    def set_symbol(self, symbol: str) -> Verified:
        return self._write_and_verify("symbol", symbol, _same_symbol)

    def set_timeframe(self, timeframe: str) -> Verified:
        return self._write_and_verify("timeframe", timeframe, _same_timeframe)

    def _write_and_verify(self, name: str, value: str, same) -> Verified:
        """Act, then read back. The read-back is not optional and not deferred.

        A failure to *reach* the app is degraded, not fatal — hard rule 4 says
        TradingView being closed means the agent proceeds without it. A refusal
        because the expression touched the trade surface is neither: cdp.py
        raises ``ForbiddenSurface``, which is fatal, and this deliberately does
        not catch it.
        """
        try:
            applied = self._session.evaluate(
                self._selectors.expression(name, "write", value)
            )
        except CDPUnavailable as exc:
            return Verified(ok=False, degraded=True, detail=str(exc))

        if not applied:
            return Verified(
                ok=False,
                degraded=True,
                detail=(
                    f"the chart API did not accept a new {name}. The app may be "
                    f"on a version where TradingViewApi is not exposed — see "
                    f"selectors.yaml"
                ),
            )

        try:
            observed = self.read(name)
        except CDPUnavailable as exc:
            return Verified(
                ok=False,
                value=None,
                degraded=True,
                detail=f"set {name} but could not read it back: {exc}",
            )

        if not same(observed, value):
            return Verified(
                ok=False,
                value=observed,
                degraded=True,
                detail=(
                    f"asked for {value!r}, the chart shows {observed!r}. "
                    f"Reported degraded rather than done — the app is a black box "
                    f"and the command completing is not evidence it took effect."
                ),
            )
        return Verified(ok=True, value=observed)

    # -- the Pine editor, the one keystroke surface ---------------------
    #
    # markup.py and the general-purpose script tools both drive the editor,
    # and they must drive it the same way: one set of methods here rather than
    # two callers reaching into the session. Text and keystrokes only -- no
    # expression in this path turns a price into a pixel, which is what makes
    # it incapable of putting a level at the wrong price.

    def open_pine_editor(self) -> bool:
        return bool(self._session.evaluate(
            self._selectors.expression("pine_editor", "write")
        ))

    def read_pine_source(self) -> Any:
        return self.read("pine_source")

    def write_pine_source(self, source: str) -> bool:
        """Replace the editor's contents. Every script Genesis writes comes through here.

        The strategy check is here and not in the callers for the usual
        reason: a guard in the shared function is one guard, a guard in every
        caller is one hole away from useless.
        """
        refuse_strategy(source)
        return bool(self._session.evaluate(
            self._selectors.expression("pine_source", "write", source)
        ))

    def apply_pine(self) -> bool:
        return bool(self._session.evaluate(
            self._selectors.expression("pine_apply", "write")
        ))

    def save_pine(self, name: str) -> bool:
        return bool(self._session.evaluate(
            self._selectors.expression("pine_save", "write", name)
        ))

    def add_saved_pine(self, name: str) -> bool:
        return bool(self._session.evaluate(
            self._selectors.expression("pine_add_saved", "write", name)
        ))

    def legend(self) -> Any:
        """The titles the chart says it is drawing. The read-back for a script."""
        return self.read("pine_indicator")

    # -- health --------------------------------------------------------

    def self_test(self) -> dict[str, Any]:
        """Exercise every probe and report what broke.

        The acceptance criterion is that this *detects a deliberately renamed
        selector*, so it must report per-surface rather than pass/fail: "the
        chart is broken" sends a person to read all of selectors.yaml, whereas
        "watchlist no longer resolves" sends them to one line of it.
        """
        results: dict[str, Any] = {}
        for name in self._selectors.names():
            entry = self._selectors.entries[name]
            if "probe" not in entry:
                continue
            try:
                results[name] = bool(self._session.evaluate(entry["probe"]))
            except CDPUnavailable as exc:
                results[name] = f"unreachable: {exc}"
        broken = [k for k, v in results.items() if v is not True]
        return {
            "probes": results,
            "broken": broken,
            "ok": not broken,
            "detail": (
                "every surface resolved"
                if not broken
                else f"{len(broken)} surface(s) no longer resolve: {', '.join(broken)}"
            ),
        }


def _same_symbol(observed: Any, wanted: str) -> bool:
    """TradingView answers ``NASDAQ:AAPL`` when asked for ``AAPL``.

    An exact comparison would report degraded on every successful call, which
    would make the degraded flag noise — and a flag that is always on is a flag
    nobody reads, which costs exactly the safety property it was added for.
    """
    if not isinstance(observed, str):
        return False
    left = observed.strip().upper().rpartition(":")[2]
    right = wanted.strip().upper().rpartition(":")[2]
    return left == right


def _same_timeframe(observed: Any, wanted: str) -> bool:
    """``1D``/``D``/``1d`` are one timeframe spelled three ways."""
    if not isinstance(observed, str):
        return False
    return _tf(observed) == _tf(wanted)


def _tf(value: str) -> str:
    text = value.strip().upper()
    return text if text[:1].isdigit() else f"1{text}"


#: Pine that can reach a broker.
#:
#: A ``strategy()`` script is not a drawing. TradingView connects strategies to
#: broker integrations and trades them, which is a path around
#: Pre-Trade Risk Engine -- Safety Invariants §1, and hard rule 1 of this
#: server's note, which only ever talked about the Trade *panel* because until
#: the script tools existed the panel was the only way in. Writing a script is
#: the other way in, and it arrives as text a model composed.
#:
#: So this is a reflex, in the Biological Design sense: deterministic, matched
#: on the source before it reaches the socket, and incapable of being talked
#: out of firing by a script that explains why it needs ``strategy.entry``.
#: Genesis draws indicators. Orders go through genesis-execution-mcp. Only.
_STRATEGY = re.compile(
    r"\bstrategy\s*\(|\bstrategy\s*\.\s*"
    r"(entry|order|exit|close|close_all|cancel|cancel_all)\b",
    re.I,
)


def refuse_strategy(source: str) -> None:
    """Raise :class:`ForbiddenSurface` if this Pine source is an auto-trader."""
    hit = _STRATEGY.search(source or "")
    if hit is not None:
        raise ForbiddenSurface(hit.group(0).strip())
