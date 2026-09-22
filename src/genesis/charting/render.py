# Spec: Genesis Markdown/10-Architecture/Charting Engine.md
"""The server-side renderer: bars + Markup Spec -> PNG.

One renderer, one output, and the acceptance criterion is unusually strict for
a drawing: *"same spec plus same bars must produce a byte-identical image."*
Three things depend on that and each breaks quietly if it slips --
vision-model interpretations are cached against the spec id, journal charts must
reproduce years later, and visual regression tests need a stable baseline.

Determinism is bought here in four places, none of them optional:

1. **Agg backend, chosen before pyplot is imported.** An interactive backend
   picked up from a DISPLAY variable renders differently and, on a headless
   3am daemon, not at all.
2. **The bundled font.** ``DejaVu Sans`` ships with matplotlib. A system font
   stack resolves to a different face on a different machine, and different
   glyph metrics are different pixels.
3. **No timestamp in the PNG metadata.** matplotlib writes a ``Software`` tEXt
   chunk by default; two identical charts would then differ by a version
   string. Suppressed explicitly.
4. **No randomness in layout.** Label collision avoidance is a deterministic
   sweep, never a jitter.

Everything drawn comes from the spec. The renderer computes nothing about the
market: if a price is on the chart, an annotation put it there, and that
annotation traces to a tool result. A renderer that derived its own levels would
be a second, unaudited level computer -- and the chart in a journal entry would
no longer be provably the one the agent reasoned about.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")  # before pyplot, always

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection, PolyCollection  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from genesis.charting.bars import Bars  # noqa: E402
from genesis.charting.spec import (  # noqa: E402
    Fib,
    Level,
    Line,
    Marker,
    MarkupSpec,
    Projection,
    RenderRef,
    TextNote,
    TradePlan,
    Zone,
)
from genesis.charting.theme import DARK, Theme, level_color, zone_color  # noqa: E402
from genesis.charting.timeframes import resolve  # noqa: E402

__all__ = ["RenderResult", "render", "render_composite", "render_png"]

#: Pixels reserved on the right for the level label chips. Labels sit *outside*
#: the price action rather than on top of it -- a chip over the last twenty
#: candles hides the only part of the chart anyone is looking at.
#:
#: Pixels rather than a fraction of the axes, which is what this was. A fraction
#: is right for one chart and wrong the moment the same drawing code runs in a
#: composite, where the main panel is two-thirds as wide: the same 8.5% is then
#: 60 fewer pixels and every chip overflows the frame.
GUTTER_PX = 152.0

#: Bounds on that reservation as a fraction of the axes, so a very narrow panel
#: does not hand its whole width to labels.
GUTTER_MIN, GUTTER_MAX = 0.06, 0.30


@dataclass(frozen=True)
class RenderResult:
    """What a render produced, and the hash that proves it is reproducible."""

    path: Path | None
    png: bytes
    render_hash: str
    width: int
    height: int

    def ref(self, theme: Theme = DARK) -> RenderRef:
        return RenderRef(
            theme=theme.name,
            size=(self.width, self.height),
            output=str(self.path) if self.path else None,
            rendered_at=datetime.now(UTC).isoformat(),
            render_hash=self.render_hash,
        )


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------


def render(
    bars: Bars,
    spec: MarkupSpec,
    *,
    path: str | Path | None = None,
    theme: Theme = DARK,
    show_volume: bool = True,
) -> RenderResult:
    """One spec, one chart. Returns the bytes and, if asked, writes the file."""
    fig = _figure(theme)
    if show_volume and float(bars.volume.sum()) > 0:
        price_ax, volume_ax = fig.subplots(
            2, 1, sharex=True, height_ratios=[4.2, 1.0],
            gridspec_kw={"hspace": 0.04},
        )
    else:
        price_ax = fig.subplots(1, 1)
        volume_ax = None

    # Margins first: the label gutter is measured from the axes' final pixel
    # width, so laying out afterwards would size every chip against a geometry
    # the figure never has.
    fig.subplots_adjust(left=0.045, right=0.985, top=0.865, bottom=0.075)

    _draw_price(price_ax, bars, spec, theme)
    if volume_ax is not None:
        _draw_volume(volume_ax, bars, theme)
        _style_axis(volume_ax, theme, bottom=True)
        _style_axis(price_ax, theme, bottom=False)
        _date_axis(volume_ax, bars, theme)
    else:
        _style_axis(price_ax, theme, bottom=True)
        _date_axis(price_ax, bars, theme)

    _header(fig, bars, spec, theme)
    _footer(fig, bars, spec, theme)
    return _finish(fig, theme, path)


def render_composite(
    panels: Sequence[tuple[Bars, MarkupSpec]],
    *,
    path: str | Path | None = None,
    theme: Theme = DARK,
    title: str | None = None,
    subtitle: str | None = None,
) -> RenderResult:
    """Several timeframes, one image — the Multi Timeframe agent's output.

    Layout is the note's: higher timeframes small down the left, the trading
    timeframe large on the right. The asymmetry is the message. A grid of four
    equal charts says *"here are four charts"*; this says *"here is the chart,
    and here is the context it sits inside"*, which is the judgement the agent
    exists to make.
    """
    if not panels:
        raise ValueError("render_composite needs at least one panel")
    fig = _figure(theme)
    context, (main_bars, main_spec) = list(panels[:-1]), panels[-1]

    if context:
        grid = fig.add_gridspec(
            len(context), 2, width_ratios=[1.0, 2.4],
            hspace=0.28, wspace=0.10,
            left=0.045, right=0.985, top=0.855, bottom=0.075,
        )
        for row, (bars, spec) in enumerate(context):
            ax = fig.add_subplot(grid[row, 0])
            _draw_price(ax, bars, spec, theme, compact=True)
            _style_axis(ax, theme, bottom=False, compact=True)
            ax.set_xticks([])
            ax.text(
                0.02, 0.93, f"{bars.symbol} {bars.timeframe}",
                transform=ax.transAxes, color=theme.ink_secondary,
                fontsize=theme.label_size, fontweight="bold", va="top",
            )
            ax.text(
                0.02, 0.06, spec.structure.trend.upper(),
                transform=ax.transAxes,
                color=_trend_color(theme, spec.structure.trend),
                fontsize=theme.label_size - 1, fontweight="bold",
            )
        main_ax = fig.add_subplot(grid[:, 1])
    else:
        main_ax = fig.subplots(1, 1)
        fig.subplots_adjust(left=0.045, right=0.985, top=0.865, bottom=0.075)

    _draw_price(main_ax, main_bars, main_spec, theme)
    _style_axis(main_ax, theme, bottom=True)
    _date_axis(main_ax, main_bars, theme)
    _header(
        fig, main_bars, main_spec, theme,
        title=title or f"{main_bars.symbol} — multi-timeframe",
        subtitle=subtitle,
    )
    _footer(fig, main_bars, main_spec, theme)
    return _finish(fig, theme, path)


def render_png(fig: Figure, theme: Theme, path: str | Path | None) -> RenderResult:
    """Save a figure a caller laid out itself (the analytics renderer).

    Deliberately does not touch the layout. It used to call ``subplots_adjust``
    with the price chart's margins, which silently overrode the analytics
    renderer's label gutter and clipped every category name -- the sort of bug
    that survives review because both halves look correct in isolation.
    """
    return _finish(fig, theme, path)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def _figure(theme: Theme) -> Figure:
    fig = plt.figure(figsize=theme.figsize, dpi=theme.dpi, facecolor=theme.surface)
    fig.patch.set_facecolor(theme.surface)
    return fig


def _gutter(ax: Any) -> float:
    """The label gutter as a fraction of this axes' own x range.

    Derived from the axes' width in pixels so a chip is the same physical size
    on a full-width chart and on a composite's main panel.
    """
    figure = ax.get_figure()
    width_px = ax.get_position().width * figure.get_size_inches()[0] * figure.dpi
    if width_px <= 0:
        return GUTTER_MIN
    return float(min(GUTTER_MAX, max(GUTTER_MIN, GUTTER_PX / width_px)))


def _draw_price(ax: Any, bars: Bars, spec: MarkupSpec, theme: Theme, *, compact: bool = False) -> None:
    x = mdates.date2num(bars.times)
    ax.set_facecolor(theme.surface)

    # Room on the right for the label gutter, and a little headroom so the
    # header never crowds the top candle.
    gutter = _gutter(ax)
    span = x[-1] - x[0] if len(x) > 1 else 1.0
    ax.set_xlim(x[0] - span * 0.01, x[-1] + span * (gutter + 0.02))

    # The view is fixed *before* anything is drawn into it. Several draw steps
    # need to clamp against the frame -- a projected trendline, a label chip --
    # and matplotlib's autoscaled limits during drawing are not the limits the
    # figure ends up with, so clamping against them silently misses.
    _set_view(ax, bars, spec)

    _draw_zones(ax, bars, spec, theme, x)
    _draw_candles(ax, bars, theme, x, compact=compact)
    _draw_lines(ax, bars, spec, theme)
    _draw_fibs(ax, bars, spec, theme, x)
    _draw_trade_plans(ax, bars, spec, theme, x)
    _draw_markers(ax, bars, spec, theme)

    view_low, view_high = ax.get_ylim()
    _draw_levels(ax, bars, spec, theme, view_low, view_high, labels=not compact)


def _set_view(ax: Any, bars: Bars, spec: MarkupSpec) -> None:
    """The y range: the price action, plus any annotation close enough to matter.

    A level far off-screen would otherwise flatten every candle into a line, so
    the view is clamped to the bars' own range plus a margin. A level outside
    that is reported in words rather than drawn at the cost of the whole chart --
    which is the right trade: the chart exists to show the decision, and a level
    six ATR away is not part of it.
    """
    lows, highs = bars.low, bars.high
    prices = [p for p in spec.prices() if np.isfinite(p)]
    low = min([float(lows.min())] + prices) if prices else float(lows.min())
    high = max([float(highs.max())] + prices) if prices else float(highs.max())
    body_low, body_high = float(lows.min()), float(highs.max())
    body = body_high - body_low or 1.0
    low = max(low, body_low - body * 0.45)
    high = min(high, body_high + body * 0.45)
    pad = (high - low) * 0.06
    ax.set_ylim(low - pad, high + pad)


def _draw_candles(ax: Any, bars: Bars, theme: Theme, x: np.ndarray, *, compact: bool) -> None:
    """Hollow up, filled down — direction encoded twice, colour and fill.

    The double encoding is deliberate: teal-versus-red separates cleanly for
    normal vision but sits in the warn band under protanopia, and the fill is
    the secondary channel that makes the palette legal there. It is also simply
    easier to read at 300 candles.
    """
    if len(x) > 1:
        width = float(np.median(np.diff(x))) * 0.68
    else:
        width = 0.5
    up = bars.close >= bars.open

    wicks = [
        [(x[i], bars.low[i]), (x[i], bars.high[i])] for i in range(len(bars))
    ]
    ax.add_collection(
        LineCollection(
            wicks,
            colors=[theme.up if u else theme.down for u in up],
            linewidths=1.0 if not compact else 0.7,
            zorder=2,
        )
    )

    bodies, facecolors, edgecolors = [], [], []
    for i in range(len(bars)):
        top = max(bars.open[i], bars.close[i])
        bottom = min(bars.open[i], bars.close[i])
        # A doji has zero body and would vanish; give it a hairline so the bar
        # is still visibly there.
        if top - bottom < 1e-9:
            top = bottom + (bars.high[i] - bars.low[i]) * 0.02 or bottom + 1e-6
        half = width / 2
        bodies.append(
            [
                (x[i] - half, bottom), (x[i] + half, bottom),
                (x[i] + half, top), (x[i] - half, top),
            ]
        )
        colour = theme.up if up[i] else theme.down
        facecolors.append(theme.surface if up[i] else colour)
        edgecolors.append(colour)

    ax.add_collection(
        PolyCollection(
            bodies,
            facecolors=facecolors,
            edgecolors=edgecolors,
            linewidths=0.9 if not compact else 0.6,
            zorder=3,
        )
    )


def _draw_volume(ax: Any, bars: Bars, theme: Theme) -> None:
    x = mdates.date2num(bars.times)
    width = float(np.median(np.diff(x))) * 0.68 if len(x) > 1 else 0.5
    up = bars.close >= bars.open
    ax.set_facecolor(theme.surface)
    ax.bar(
        x, bars.volume, width=width,
        color=[theme.volume_up if u else theme.volume_down for u in up],
        linewidth=0, zorder=2,
    )
    ax.set_ylim(0, float(bars.volume.max()) * 1.15)
    span = x[-1] - x[0] if len(x) > 1 else 1.0
    ax.set_xlim(x[0] - span * 0.01, x[-1] + span * (_gutter(ax) + 0.02))
    ax.set_yticks([])
    ax.text(
        0.004, 0.78, "VOL", transform=ax.transAxes,
        color=theme.ink_muted, fontsize=theme.label_size - 2, fontweight="bold",
    )


def _draw_levels(
    ax: Any, bars: Bars, spec: MarkupSpec, theme: Theme,
    view_low: float, view_high: float, *, labels: bool = True,
) -> None:
    """Horizontal levels, each labelled with its type and price in the gutter.

    *"Every level labelled with its price and its type ('PDH 122.10')"* --
    stated as a rendering rule because it is what makes a vision model's reading
    checkable. A model that names a level it can read is verifiable; one
    inferring a price from pixel position is not.
    """
    levels = [a for a in spec.annotations if isinstance(a, Level)]
    if not levels:
        return
    x0, x1 = ax.get_xlim()
    gutter_x = x1 - (x1 - x0) * _gutter(ax)

    placed: list[float] = []
    minimum_gap = (view_high - view_low) * 0.028
    for level in sorted(levels, key=lambda a: -a.price):
        if not (view_low <= level.price <= view_high):
            continue
        colour = level_color(theme, level.type)
        ax.plot(
            [x0, gutter_x], [level.price, level.price],
            color=colour, linewidth=1.4, zorder=4,
            alpha=0.55 + 0.45 * level.strength,
        )
        if not labels:
            continue
        # Deterministic collision avoidance: levels are drawn top-down, so a
        # chip sits at its true price unless the one above is too close, in
        # which case it drops to exactly one gap below it.
        #
        # Written as a single subtraction rather than a "walk down until it
        # clears" loop, which is what this was and which hangs: after
        # ``y = above - gap`` floating-point rounding can leave ``y - above``
        # fractionally *under* ``gap``, the condition stays true, the next
        # iteration recomputes the identical y, and the render never returns.
        y = level.price
        if placed:
            y = min(y, placed[-1] - minimum_gap)
        placed.append(y)
        ax.text(
            gutter_x + (x1 - x0) * 0.006, y,
            f"{level.label}  {level.price:,.2f}",
            color=theme.surface, fontsize=theme.label_size - 0.5,
            fontweight="bold", va="center", ha="left", zorder=6,
            bbox={
                "facecolor": colour, "edgecolor": "none",
                "boxstyle": "round,pad=0.28", "alpha": 0.95,
            },
        )


def _draw_zones(ax: Any, bars: Bars, spec: MarkupSpec, theme: Theme, x: np.ndarray) -> None:
    x0, x1 = float(x[0]), float(x[-1])
    for zone in (a for a in spec.annotations if isinstance(a, Zone)):
        colour = zone_color(theme, zone.subtype)
        ax.add_patch(
            Rectangle(
                (x0, zone.from_price), x1 - x0, zone.to_price - zone.from_price,
                facecolor=colour, alpha=0.13, edgecolor=colour,
                linewidth=0.8, linestyle=(0, (4, 3)), zorder=1,
            )
        )
        ax.text(
            x0 + (x1 - x0) * 0.006, zone.to_price,
            zone.label.upper(), color=colour, fontsize=theme.label_size - 2,
            fontweight="bold", va="bottom", zorder=5,
        )


def _draw_lines(ax: Any, bars: Bars, spec: MarkupSpec, theme: Theme) -> None:
    """Trendlines drawn solid between their anchors, dashed onward to the edge.

    The extension is not decoration. A trendline that stops at its last touch
    describes history; the part that matters is where it *is now*, because that
    is the price the next bar has to deal with. Drawing the extension dashed
    keeps the distinction the renderer never blurs elsewhere: solid is what
    happened, dashed is what is projected.
    """
    x0, x1 = ax.get_xlim()
    edge = x1 - (x1 - x0) * _gutter(ax)
    for line in (a for a in spec.annotations if isinstance(a, (Line, Projection))):
        times = [_as_datetime(p[0]) for p in line.points]
        prices = [p[1] for p in line.points]
        projection = isinstance(line, Projection)
        colour = theme.projection if projection else theme.trendline
        xs = mdates.date2num(times)
        ax.plot(
            xs, prices, color=colour, linewidth=1.5,
            linestyle=(0, (5, 4)) if projection else "-", zorder=4, alpha=0.9,
        )

        label_x, label_y = float(xs[-1]), float(prices[-1])
        if not projection and len(xs) >= 2 and xs[-1] < edge and xs[-1] != xs[-2]:
            slope = (prices[-1] - prices[-2]) / (xs[-1] - xs[-2])
            label_y = float(prices[-1] + slope * (edge - xs[-1]))
            label_x = float(edge)
            ax.plot(
                [xs[-1], edge], [prices[-1], label_y], color=colour,
                linewidth=1.2, linestyle=(0, (4, 4)), zorder=4, alpha=0.65,
                clip_on=True,
            )
        # A steep trendline's extension leaves the view, and an unclamped label
        # is then drawn *outside* the axes, on top of the header. Clamp into the
        # frame and flip the anchor so the text reads inward.
        y_low, y_high = ax.get_ylim()
        inset = (y_high - y_low) * 0.03
        clamped = min(max(label_y, y_low + inset), y_high - inset)
        outside = clamped != label_y
        ax.text(
            label_x, clamped,
            f"{line.label} " if outside else f" {line.label}",
            color=colour, fontsize=theme.label_size - 2, va="center",
            ha="right" if outside else "left", zorder=5, clip_on=False,
        )


def _draw_fibs(ax: Any, bars: Bars, spec: MarkupSpec, theme: Theme, x: np.ndarray) -> None:
    x0, x1 = float(x[0]), float(x[-1])
    for fib in (a for a in spec.annotations if isinstance(a, Fib)):
        for ratio, price in fib.prices().items():
            ax.plot(
                [x0, x1 - (x1 - x0) * _gutter(ax)], [price, price],
                color=theme.ink_muted, linewidth=0.8, alpha=0.5,
                linestyle=(0, (1, 3)), zorder=3,
            )
            ax.text(
                x0, price, f"{ratio:.3f} ",
                color=theme.ink_muted, fontsize=theme.label_size - 3,
                va="center", ha="right", zorder=4,
            )


def _draw_trade_plans(ax: Any, bars: Bars, spec: MarkupSpec, theme: Theme, x: np.ndarray) -> None:
    """Entry, stop and targets as a two-colour risk-reward box.

    Risk below, reward above (inverted for a short). The area of the two boxes
    *is* the R:R -- which is the point of drawing it rather than printing a
    number, and the reason a plan whose reward box is visibly smaller than its
    risk box is one nobody has to compute anything to reject.
    """
    if len(x) < 2:
        return
    start = float(x[int(len(x) * 0.72)])
    end = float(x[-1])
    for plan in (a for a in spec.annotations if isinstance(a, TradePlan)):
        ax.add_patch(
            Rectangle(
                (start, min(plan.entry, plan.stop)), end - start, abs(plan.entry - plan.stop),
                facecolor=theme.risk, alpha=0.16, edgecolor=theme.risk,
                linewidth=1.0, zorder=4,
            )
        )
        if plan.targets:
            target = plan.targets[-1]
            ax.add_patch(
                Rectangle(
                    (start, min(plan.entry, target)), end - start, abs(target - plan.entry),
                    facecolor=theme.reward, alpha=0.16, edgecolor=theme.reward,
                    linewidth=1.0, zorder=4,
                )
            )
        ax.plot([start, end], [plan.entry, plan.entry], color=theme.ink,
                linewidth=1.6, zorder=5)
        rr = plan.computed_rr
        ax.text(
            start, plan.entry,
            f" {plan.side.upper()} {plan.entry:,.2f}" + (f"  {rr:.1f}R" if rr else ""),
            color=theme.ink, fontsize=theme.label_size - 1, fontweight="bold",
            va="bottom", zorder=6,
        )


def _draw_markers(ax: Any, bars: Bars, spec: MarkupSpec, theme: Theme) -> None:
    for marker in (a for a in spec.annotations if isinstance(a, Marker)):
        when = mdates.date2num(_as_datetime(marker.time))
        ax.plot(
            when, marker.price, marker="o", markersize=9,
            markerfacecolor=theme.vwap, markeredgecolor=theme.surface,
            markeredgewidth=1.6, zorder=6, linestyle="none",
        )
        ax.text(
            when, marker.price, f"  {marker.label}",
            color=theme.ink_secondary, fontsize=theme.label_size - 2,
            va="center", zorder=6,
        )
    for note in (a for a in spec.annotations if isinstance(a, TextNote)):
        if note.position is None:
            continue
        ax.text(
            mdates.date2num(_as_datetime(note.position[0])), note.position[1],
            note.content, color=theme.ink_secondary,
            fontsize=theme.label_size - 1, zorder=6,
        )


# --------------------------------------------------------------------------
# Chrome
# --------------------------------------------------------------------------


def _style_axis(ax: Any, theme: Theme, *, bottom: bool, compact: bool = False) -> None:
    ax.set_facecolor(theme.surface)
    ax.grid(True, axis="y", color=theme.grid, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme.axis)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(
        colors=theme.ink_muted,
        labelsize=theme.label_size - (2 if compact else 0.5),
        length=0, pad=6,
    )
    if compact:
        ax.set_yticks([])
    if not bottom:
        ax.tick_params(labelbottom=False)


def _date_axis(ax: Any, bars: Bars, theme: Theme) -> None:
    """Tick density and format chosen by timeframe, not by matplotlib's guess.

    The automatic locator produces "Jan 2026" on an intraday chart and a wall of
    overlapping dates on a five-year weekly. Both are legible failures for a
    person and comprehension failures for a vision model, which reads the axis
    to place the annotations in time.
    """
    tf = resolve(bars.timeframe)
    if tf.minutes < 60:
        locator, fmt = mdates.AutoDateLocator(minticks=6, maxticks=10), "%H:%M"
    elif tf.minutes < 1440:
        locator, fmt = mdates.AutoDateLocator(minticks=5, maxticks=9), "%d %b %H:%M"
    elif tf.minutes < 10080:
        locator, fmt = mdates.AutoDateLocator(minticks=5, maxticks=9), "%d %b %y"
    else:
        locator, fmt = mdates.AutoDateLocator(minticks=4, maxticks=8), "%b %Y"
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))


def _header(
    fig: Figure, bars: Bars, spec: MarkupSpec, theme: Theme,
    *, title: str | None = None, subtitle: str | None = None,
) -> None:
    fig.text(
        0.045, 0.955, title or f"{spec.symbol}  {spec.timeframe}",
        color=theme.ink, fontsize=theme.title_size, fontweight="bold", va="top",
    )
    change = ""
    if len(bars) > 1:
        delta = (bars.close[-1] / bars.close[0] - 1) * 100
        change = f"   {delta:+.1f}% over the window"
    fig.text(
        0.045, 0.913,
        subtitle
        or (
            f"{bars.first_time.date().isoformat()} → {bars.last_time.date().isoformat()}"
            f"   last {bars.last:,.2f}{change}"
        ),
        color=theme.ink_secondary, fontsize=theme.font_size, va="top",
    )
    structure = spec.structure
    if structure.trend:
        fig.text(
            0.985, 0.955,
            f"{structure.trend.upper()}  {structure.swing}",
            color=_trend_color(theme, structure.trend),
            fontsize=theme.font_size + 1, fontweight="bold", va="top", ha="right",
        )
    if structure.atr14:
        fig.text(
            0.985, 0.915, f"ATR14 {structure.atr14:,.2f}",
            color=theme.ink_muted, fontsize=theme.label_size, va="top", ha="right",
        )


def _footer(fig: Figure, bars: Bars, spec: MarkupSpec, theme: Theme) -> None:
    """Date, timeframe, source and spec id burned in.

    *"A chart with no date is useless in a journal six months later."* The spec
    id is here for the same reason one level down: it is what turns a PNG found
    in the vault back into the object that produced it.
    """
    stamp = spec.as_of.strftime("%Y-%m-%d %H:%M UTC")
    left = f"{spec.symbol} · {spec.timeframe} · as of {stamp} · {spec.id}"
    fig.text(0.045, 0.022, left, color=theme.ink_muted, fontsize=theme.label_size - 1)
    right = f"source {bars.source} · tier {bars.tier}"
    if spec.degraded:
        right = "DEGRADED · " + right
    fig.text(
        0.985, 0.022, right,
        color=theme.risk if spec.degraded else theme.ink_muted,
        fontsize=theme.label_size - 1, ha="right",
        fontweight="bold" if spec.degraded else "normal",
    )


def _trend_color(theme: Theme, trend: str) -> str:
    return {"up": theme.up, "down": theme.down}.get(trend, theme.ink_muted)


def _finish(fig: Figure, theme: Theme, path: str | Path | None) -> RenderResult:
    """Save, hash, and close. The one place PNG bytes come into existence."""
    # A stat tile is figure-level text with no axes at all -- that is the point
    # of it, and it is a legitimate chart. The guard is against an empty figure,
    # not against an axis-free one.
    if not fig.get_axes() and not fig.texts:
        raise ValueError("nothing was drawn")
    buffer = io.BytesIO()
    fig.savefig(
        buffer, format="png", facecolor=theme.surface, dpi=theme.dpi,
        # Suppressing Software is what makes two renders on two machines
        # byte-identical instead of differing by a version string.
        metadata={"Software": None},
    )
    plt.close(fig)
    png = buffer.getvalue()
    digest = "sha256:" + hashlib.sha256(png).hexdigest()

    written: Path | None = None
    if path is not None:
        written = Path(path).expanduser()
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(png)
    return RenderResult(
        path=written, png=png, render_hash=digest,
        width=theme.size[0], height=theme.size[1],
    )


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
