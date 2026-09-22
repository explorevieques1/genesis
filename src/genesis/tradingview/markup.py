# Spec: Genesis Markdown/30-MCP/genesis-tradingview-mcp.md
"""Putting a Markup Spec on the chart you actually look at.

The note's design, quoted because every line of this module follows from it:

> **Compile, don't click.** The Desktop renderer works by compiling the spec
> into a Pine indicator and loading it through the editor — not by simulating
> mouse drags on the chart.

What that buys, concretely:

**No price-to-pixel arithmetic anywhere.** Drag-based automation must convert a
price into a screen coordinate, which needs the chart's current scale, which
changes when you scroll. Every such conversion is a chance to draw a level at
the wrong price -- silently, and looking authoritative. Pine takes prices.

**Genesis owns exactly one indicator.** Applying a new markup replaces the
source of the same script. Nothing Genesis does can touch a line you drew, and
"remove the Genesis overlay" means one unambiguous thing.

**The actuator is verified.** *Proprioception before ambition*: every write
reads back. The read-back here is the chart's own legend reporting that a script
named ``Genesis Markup`` compiled and is drawing. A write that cannot be
perceived returns ``degraded``, never ``ok`` -- hard rule 2, and the reason the
read half of this server was built first.

**Nothing here can reach an order.** No expression names the trade panel;
:mod:`genesis.tradingview.cdp` refuses one that does before it is sent; and no
function in this file takes a side, a size, or a quantity.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from genesis.charting.pine import INDICATOR_NAME, compile_pine
from genesis.charting.spec import MarkupSpec
from genesis.tradingview.cdp import CDPUnavailable
from genesis.tradingview.surface import ChartSurface, Verified

__all__ = ["MarkupSurface", "wait_for_legend"]

#: Seconds to wait for Pine to compile before reading the legend back. The
#: compile is asynchronous and there is no event to hook, so this is a poll --
#: short, bounded, and it reports degraded rather than blocking if the script
#: never appears.
COMPILE_TIMEOUT_SEC = 8.0
_POLL_SEC = 0.25


@dataclass
class MarkupSurface:
    """Applies a compiled spec to the desktop chart, and confirms it landed."""

    surface: ChartSurface

    def apply(self, spec: MarkupSpec, *, align_chart: bool = True) -> Verified:
        """Compile the spec, load it into the editor, apply it, read it back.

        ``align_chart`` first points the chart at the spec's own symbol and
        timeframe. On by default because a markup applied to the wrong chart is
        the worst available outcome: every level is drawn, correctly, against a
        completely different instrument -- and it looks entirely plausible.
        """
        if align_chart:
            moved = self._align(spec)
            if moved is not None:
                return moved

        source = compile_pine(spec)
        try:
            if not self.surface.open_pine_editor():
                return Verified(
                    ok=False, degraded=True,
                    detail="could not open the Pine editor",
                )
            if not self.surface.write_pine_source(source):
                return Verified(
                    ok=False, degraded=True,
                    detail="could not write the indicator source",
                )
            if not self.surface.apply_pine():
                return Verified(
                    ok=False, degraded=True,
                    detail="could not apply the script to the chart",
                )
        except CDPUnavailable as exc:
            # The app is closed. Degraded, not fatal: hard rule 4 is that the
            # agent proceeds without the desktop chart, and the headless PNG
            # already exists either way.
            return Verified(ok=False, degraded=True, detail=str(exc))

        return self._confirm(spec)

    def clear(self) -> Verified:
        """Remove the Genesis overlay by compiling an empty indicator.

        Deliberately not "find the indicator and click remove". Replacing the
        source with an empty script uses the identical mechanism as applying
        one, so there is one code path that can fail rather than two -- and it
        cannot delete anything except the script Genesis owns.
        """
        empty = (
            "//@version=5\n"
            f'indicator("{INDICATOR_NAME}", overlay=true)\n'
            "// cleared by Genesis\n"
        )
        try:
            self.surface.open_pine_editor()
            wrote = self.surface.write_pine_source(empty)
            self.surface.apply_pine()
        except CDPUnavailable as exc:
            return Verified(ok=False, degraded=True, detail=str(exc))
        return Verified(ok=bool(wrote), value=INDICATOR_NAME)

    # -- internals ---------------------------------------------------------

    def _align(self, spec: MarkupSpec) -> Verified | None:
        """Point the chart at the spec's symbol and timeframe. ``None`` if fine."""
        moved = self.surface.set_symbol(spec.symbol)
        if not moved.ok:
            return Verified(
                ok=False, degraded=True,
                detail=f"could not switch the chart to {spec.symbol}: {moved.detail}",
            )
        moved = self.surface.set_timeframe(spec.timeframe)
        if not moved.ok:
            return Verified(
                ok=False, degraded=True,
                detail=f"could not set the timeframe to {spec.timeframe}: {moved.detail}",
            )
        return None

    def _confirm(self, spec: MarkupSpec) -> Verified:
        """Poll the legend until the indicator appears, or report degraded.

        This is the perception half. Without it, "I sent the command" would be
        reported as success -- and a system that can act but cannot verify it
        acted is the configuration Biological Design calls dangerous, whose
        failure mode is drift between believed and actual state.
        """
        try:
            seen = wait_for_legend(self.surface, INDICATOR_NAME)
        except CDPUnavailable as exc:
            return Verified(ok=False, degraded=True, detail=str(exc))

        if seen is not None:
            return Verified(
                ok=True,
                value={
                    "indicator": INDICATOR_NAME,
                    "spec": spec.id,
                    "symbol": spec.symbol,
                    "timeframe": spec.timeframe,
                    "annotations": len(spec.annotations),
                },
            )
        return Verified(
            ok=False,
            degraded=True,
            detail=(
                f"the script was sent but {INDICATOR_NAME!r} did not appear in the "
                f"chart legend within {COMPILE_TIMEOUT_SEC:.0f}s \u2014 it may have "
                f"failed to compile"
            ),
        )


def wait_for_legend(
    surface: ChartSurface,
    title: str,
    timeout: float = COMPILE_TIMEOUT_SEC,
) -> list[Any] | None:
    """Poll the chart's legend for a source with this title. ``None`` on timeout.

    The one read-back every script write is verified by, whether the script
    came from a Markup Spec or from words. Compiling is asynchronous and there
    is no event to hook, so it is a poll -- short, bounded, and it returns
    rather than blocking, because a caller that must report degraded cannot do
    so from inside a wait that never ends.
    """
    deadline = time.monotonic() + timeout
    while True:
        seen = surface.legend()
        if isinstance(seen, list) and any(
            title.lower() in str(entry).lower() for entry in seen
        ):
            return seen
        if time.monotonic() >= deadline:
            return None
        time.sleep(_POLL_SEC)
