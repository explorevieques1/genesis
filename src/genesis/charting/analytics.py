# Spec: Genesis Markdown/20-Agents/Charting/Agent — Data Viz.md
"""Non-price visualisation: ranked bars, macro series, comparisons, correlation.

The other half of "chart me something". *"Show me a bar chart of the top
performing sectors this past year"* and *"show me the fed funds rate over twenty
years"* are not markup questions -- there is no level to draw and no structure to
name -- and forcing them through the candle renderer would produce a candle chart
of a percentage.

The design rules here are not improvised. They come from the same place the
price renderer's do (fixed theme, fixed size, burned-in provenance) plus the
standard visualisation discipline, and four of them are load-bearing enough to
name:

**One axis, always.** No chart in this module can plot two measures on two
y-scales. The alignment between two such scales is arbitrary, so the chart
invents a relationship that is not in the data -- and this is a system whose
output a person acts on with money. Two measures means two panels, or both
indexed to 100 at t0.

**Colour by identity, in fixed slot order.** A series keeps its hue when a
filter removes its neighbours. Never a value-ramp over unordered categories:
colouring bars darker-where-bigger double-encodes the length and spends the
only free channel on information the chart already shows.

**Signed magnitude is polarity, and gets exactly two colours.** Sector returns
are the archetypal case: positive teal, negative red, a drawn zero baseline, and
the bar's own direction as the second encoding. Not eight hues -- eleven sectors
in eleven colours is a chart about the palette.

**A single number is a stat tile, not a one-bar chart.** :func:`stat` exists so
the answer to *"what is CPI"* is a number, large, with its date and source --
which is the honest form and the one a voice system can read aloud unchanged.

Everything is declared as an :class:`AnalyticsSpec` and rendered from it, for the
same reason the Markup Spec is an object: the chart in the vault six months from
now must be re-renderable, and the agent's *choice of form* is part of what it
decided and therefore part of what gets audited.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # noqa: E402

from genesis.charting.render import RenderResult, render_png  # noqa: E402
from genesis.charting.theme import DARK, Theme  # noqa: E402

__all__ = [
    "MAX_SERIES",
    "AnalyticsSpec",
    "Series",
    "render_analytics",
]

#: Past eight, a categorical hue is indistinguishable from one already used.
#: A ninth series folds into "Other" or becomes small multiples; it never gets
#: a generated colour.
MAX_SERIES = 8

#: Bars past this many are unreadable at 1600x900 and the chart should have been
#: a table. Enforced rather than advised, because the failure is silent: the
#: labels simply overlap into a grey smear that still looks like a chart.
MAX_BARS = 30


class Series(BaseModel):
    """One named line or one group of bars."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    values: tuple[float | None, ...]
    #: Per-point units where they differ from the chart's (rare). Mostly unused.
    unit: str | None = None

    @field_validator("values", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    def finite(self) -> np.ndarray:
        return np.array(
            [np.nan if v is None else float(v) for v in self.values], dtype=float
        )


class AnalyticsSpec(BaseModel):
    """A declarative chart: what form, what data, what it is for.

    ``why`` is required, exactly as it is on a markup annotation and for the
    same reason. A chart with no stated purpose is one nobody can evaluate later,
    and this system's whole premise is that its outputs are auditable months
    after the fact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    form: Literal["bar", "line", "area", "stacked_bar", "heatmap", "scatter", "stat"]
    title: str
    subtitle: str = ""
    why: str
    #: Category labels (bar, heatmap columns) — mutually exclusive with ``times``.
    categories: tuple[str, ...] = ()
    #: ISO dates for a time series.
    times: tuple[str, ...] = ()
    series: tuple[Series, ...] = ()
    #: Row labels for a heatmap. Columns come from ``categories``.
    rows: tuple[str, ...] = ()
    matrix: tuple[tuple[float, ...], ...] = ()
    unit: str = ""
    #: ``percent`` draws a zero baseline and splits colour on sign.
    #: ``percent`` is a *change* and prints signed (+2.4%); ``rate`` is a level
    #: and prints unsigned (4.1%). Conflating them puts a plus sign on the fed
    #: funds rate, which reads as a rise rather than a level.
    value_kind: Literal[
        "plain", "percent", "rate", "price", "ratio", "index"
    ] = "plain"
    #: One category or series name to emphasise; everything else recedes to grey.
    #: The answer to "eight hues when the story is one number".
    highlight: str | None = None
    #: Provenance, burned into the footer. Never optional in practice: an
    #: unattributed chart is one nobody can check.
    source: str = ""
    as_of: str = ""
    degraded: bool = False
    #: Free callouts drawn on the plot: ``{"x": <label or ISO date>, "text": ...}``
    notes: tuple[dict[str, str], ...] = ()

    @field_validator(
        "categories", "times", "series", "rows", "notes", mode="before"
    )
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @field_validator("matrix", mode="before")
    @classmethod
    def _matrix(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(tuple(row) for row in v)
        return v

    @model_validator(mode="after")
    def _coherent(self) -> AnalyticsSpec:
        if len(self.series) > MAX_SERIES:
            raise ValueError(
                f"{len(self.series)} series exceeds {MAX_SERIES}. Past eight, a "
                f"categorical colour is indistinguishable from one already used "
                f"— fold the tail into 'Other' or use small multiples"
            )
        if self.form in ("line", "area") and not self.times:
            raise ValueError(f"a {self.form} chart needs `times`")
        if self.form in ("bar", "stacked_bar") and not self.categories:
            raise ValueError(f"a {self.form} chart needs `categories`")
        if self.form == "heatmap" and not (self.matrix and self.rows and self.categories):
            raise ValueError("a heatmap needs `matrix`, `rows` and `categories`")
        if self.form == "bar" and len(self.categories) > MAX_BARS:
            raise ValueError(
                f"{len(self.categories)} bars will not be legible at this size; "
                f"take the top {MAX_BARS} or render a table"
            )
        for s in self.series:
            expected = len(self.times) if self.times else len(self.categories)
            if expected and len(s.values) != expected:
                raise ValueError(
                    f"series {s.name!r} has {len(s.values)} values for "
                    f"{expected} points"
                )
        return self


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render_analytics(
    spec: AnalyticsSpec, *, path: str | Path | None = None, theme: Theme = DARK
) -> RenderResult:
    """One spec, one chart, one PNG. The only entry point."""
    fig = plt.figure(figsize=theme.figsize, dpi=theme.dpi, facecolor=theme.surface)
    fig.patch.set_facecolor(theme.surface)

    if spec.form == "stat":
        _stat(fig, spec, theme)
    else:
        ax = fig.subplots(1, 1)
        ax.set_facecolor(theme.surface)
        {
            "bar": _bar,
            "stacked_bar": _stacked_bar,
            "line": _line,
            "area": _line,
            "heatmap": _heatmap,
            "scatter": _scatter,
        }[spec.form](ax, spec, theme)
        _chrome(ax, spec, theme)

    _titles(fig, spec, theme)
    _footer(fig, spec, theme)
    fig.subplots_adjust(
        left=_left_margin(spec), right=0.975, top=0.845, bottom=0.115
    )
    return render_png(fig, theme, path)


def _left_margin(spec: AnalyticsSpec) -> float:
    """Room for the category labels, sized to the longest one.

    A fixed margin clips "Consumer Discretionary" and wastes half the plot on
    "Q1". Horizontal bars and heatmaps carry their labels in the left gutter, so
    the gutter has to be measured rather than guessed -- a clipped category
    label is a chart that has lost the thing it is comparing.
    """
    if spec.form not in ("bar", "heatmap"):
        return 0.06
    labels = spec.rows if spec.form == "heatmap" else spec.categories
    longest = max((len(str(label)) for label in labels), default=8)
    return min(0.06 + longest * 0.0088, 0.26)


# -- forms -----------------------------------------------------------------


def _bar(ax: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    """A single measure across categories, sorted, direct-labelled.

    Sorted because a ranked bar chart is a ranking, and leaving the categories
    in arbitrary order makes the reader do the sort by eye. Direct-labelled
    because the value is the answer, and forcing a reader back to the axis for
    every bar is the tax that makes people ignore charts.
    """
    values = spec.series[0].finite()
    labels = list(spec.categories)
    order = np.argsort(np.nan_to_num(values, nan=-np.inf))[::-1]
    values, labels = values[order], [labels[i] for i in order]

    signed = spec.value_kind in ("percent", "ratio") and float(np.nanmin(values)) < 0
    colours = _bar_colours(spec, labels, values, signed, theme)

    y = np.arange(len(labels))[::-1]
    ax.barh(y, values, height=0.62, color=colours, linewidth=0, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, color=theme.ink_secondary, fontsize=theme.font_size)
    ax.set_xlabel("")

    if signed:
        ax.axvline(0, color=theme.axis, linewidth=1.2, zorder=4)

    span = float(np.nanmax(np.abs(values))) or 1.0
    for yi, value in zip(y, values):
        if not np.isfinite(value):
            continue
        offset = span * 0.015
        ax.text(
            value + (offset if value >= 0 else -offset), yi, _fmt(value, spec),
            color=theme.ink, fontsize=theme.font_size, va="center",
            ha="left" if value >= 0 else "right", fontweight="bold", zorder=5,
        )
    low = min(float(np.nanmin(values)), 0.0)
    ax.set_xlim(low - span * 0.14, float(np.nanmax(values)) + span * 0.16)
    ax.set_ylim(-0.7, len(labels) - 0.3)
    ax.grid(True, axis="x", color=theme.grid, linewidth=0.7, zorder=0)


def _bar_colours(
    spec: AnalyticsSpec, labels: list[str], values: np.ndarray,
    signed: bool, theme: Theme,
) -> list[str]:
    """Emphasis first, then polarity, then a single hue. Never a value ramp."""
    if spec.highlight:
        return [
            theme.series[0] if label == spec.highlight else theme.grid
            for label in labels
        ]
    if signed:
        # Polarity, two colours, with the bar's own direction as the second
        # encoding — colour is never carrying the sign alone.
        return [theme.up if v >= 0 else theme.down for v in values]
    return [theme.series[0]] * len(labels)


def _stacked_bar(ax: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    """Composition across categories. A 2px surface gap keeps segments distinct."""
    x = np.arange(len(spec.categories))
    bottom = np.zeros(len(spec.categories))
    for i, series in enumerate(spec.series):
        values = np.nan_to_num(series.finite())
        ax.bar(
            x, values, bottom=bottom, width=0.66, label=series.name,
            color=theme.series[i % len(theme.series)],
            edgecolor=theme.surface, linewidth=2.0, zorder=3,
        )
        bottom += values
    ax.set_xticks(x)
    ax.set_xticklabels(
        spec.categories, color=theme.ink_secondary, fontsize=theme.font_size,
        rotation=0 if max(len(c) for c in spec.categories) <= 6 else 30,
        ha="center" if max(len(c) for c in spec.categories) <= 6 else "right",
    )
    ax.grid(True, axis="y", color=theme.grid, linewidth=0.7, zorder=0)
    _legend(ax, spec, theme)


def _line(ax: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    """Change over time. Direct-labelled at the right end for up to four series.

    The right-end label is where a reader's eye already is on a time series --
    it answers "which line is which" without a round trip to a legend box. Past
    four series the labels collide, so the legend carries it alone.
    """
    times = [_as_date(t) for t in spec.times]
    x = mdates.date2num(times)
    direct = len(spec.series) <= 4

    for i, series in enumerate(spec.series):
        values = series.finite()
        emphasised = spec.highlight is None or series.name == spec.highlight
        colour = (
            theme.series[i % len(theme.series)] if emphasised else theme.ink_muted
        )
        ax.plot(
            x, values, color=colour, linewidth=2.0 if emphasised else 1.2,
            zorder=4 if emphasised else 3, alpha=1.0 if emphasised else 0.45,
            solid_capstyle="round",
        )
        if spec.form == "area" and len(spec.series) == 1:
            ax.fill_between(x, values, np.nanmin(values), color=colour, alpha=0.14, zorder=2)
        if direct and len(values):
            last = np.where(np.isfinite(values))[0]
            if len(last):
                j = int(last[-1])
                ax.text(
                    x[j] + (x[-1] - x[0]) * 0.008, values[j],
                    f" {series.name}  {_fmt(float(values[j]), spec)}",
                    color=colour, fontsize=theme.font_size,
                    fontweight="bold", va="center", zorder=5,
                )

    if spec.value_kind in ("percent", "ratio"):
        ax.axhline(0, color=theme.axis, linewidth=1.0, zorder=2)
    ax.set_xlim(x[0], x[-1] + (x[-1] - x[0]) * (0.14 if direct else 0.01))
    locator = mdates.AutoDateLocator(minticks=5, maxticks=10)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    # The right pad exists to hold the direct labels, not to extend the series.
    # Ticks drawn past the last observation imply data that is not there --
    # a chart of rates through 2026 whose axis says 2028 has told a small lie
    # about its own coverage.
    ax.set_xticks([t for t in ax.get_xticks() if x[0] <= t <= x[-1]])
    ax.grid(True, axis="y", color=theme.grid, linewidth=0.7, zorder=0)
    _annotations(ax, spec, theme, x, times)
    if not direct:
        _legend(ax, spec, theme)


def _heatmap(ax: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    """A matrix — correlation, mostly. Diverging around a neutral zero.

    Two hues that read as opposite with a neutral grey midpoint: the midpoint
    has to read as "nothing", which is exactly what zero correlation is. Every
    cell is also printed, so the colour never carries a value alone.
    """
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

    data = np.array(spec.matrix, dtype=float)
    cmap = LinearSegmentedColormap.from_list(
        "genesis-diverging",
        [theme.diverging_low, theme.diverging_mid, theme.diverging_high],
    )
    limit = float(np.nanmax(np.abs(data))) or 1.0
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)
    ax.imshow(data, cmap=cmap, norm=norm, aspect="auto", zorder=2)

    ax.set_xticks(np.arange(len(spec.categories)))
    ax.set_xticklabels(
        spec.categories, color=theme.ink_secondary, fontsize=theme.font_size - 1,
        rotation=30, ha="right",
    )
    ax.set_yticks(np.arange(len(spec.rows)))
    ax.set_yticklabels(spec.rows, color=theme.ink_secondary, fontsize=theme.font_size - 1)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            value = data[i, j]
            if not np.isfinite(value):
                continue
            ax.text(
                j, i, f"{value:.2f}", ha="center", va="center",
                color=theme.ink if abs(value) > limit * 0.45 else theme.ink_secondary,
                fontsize=theme.font_size - 1, fontweight="bold", zorder=3,
            )
    ax.grid(False)


def _scatter(ax: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    """Two measures against each other. Capped at three series, by the palette.

    An all-pairs colour comparison (every series against every other, not just
    neighbours) only clears the separation floors for three hues. A fourth would
    put two confusable colours on screen with no adjacency to protect them.
    """
    if len(spec.series) < 2:
        raise ValueError("a scatter needs an x series and at least one y series")
    x = spec.series[0].finite()
    for i, series in enumerate(spec.series[1:][:3]):
        ax.scatter(
            x, series.finite(), s=64, label=series.name,
            color=theme.series[i % 3], edgecolors=theme.surface, linewidths=1.5,
            zorder=3,
        )
    ax.set_xlabel(spec.series[0].name, color=theme.ink_secondary, fontsize=theme.font_size)
    ax.grid(True, color=theme.grid, linewidth=0.7, zorder=0)
    _legend(ax, spec, theme)


def _stat(fig: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    """The hero number. The right form when the answer is one value.

    A one-bar bar chart is the most common way a chart misses its own point;
    this is the alternative. The number is set large, its unit small beside it,
    and the change beneath it in the polarity colours.
    """
    values = spec.series[0].finite() if spec.series else np.array([np.nan])
    current = float(values[-1])
    fig.text(
        0.06, 0.52, _fmt(current, spec), color=theme.ink,
        fontsize=112, fontweight="bold", va="center",
    )
    if len(values) > 1 and np.isfinite(values[-2]):
        change = current - float(values[-2])
        fig.text(
            0.06, 0.30,
            f"{change:+,.2f}{'%' if spec.value_kind == 'percent' else ''} "
            f"from the prior reading",
            color=theme.up if change >= 0 else theme.down,
            fontsize=22, fontweight="bold", va="center",
        )


# -- chrome ----------------------------------------------------------------


def _chrome(ax: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme.axis)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(colors=theme.ink_muted, labelsize=theme.label_size, length=0, pad=7)
    if spec.form in ("line", "area", "stacked_bar", "scatter"):
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v, spec, tick=True)))
    if spec.form == "bar":
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt(v, spec, tick=True)))
    if spec.form == "heatmap":
        ax.tick_params(length=0)
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(False)


def _legend(ax: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    if len(spec.series) < 2:
        return  # one series: the title names it, a legend box is noise
    legend = ax.legend(
        loc="upper left", frameon=False, ncols=min(len(spec.series), 4),
        fontsize=theme.font_size, labelcolor=theme.ink_secondary,
        handlelength=1.4, columnspacing=1.6, borderaxespad=0.4,
    )
    legend.set_zorder(6)


def _annotations(ax: Any, spec: AnalyticsSpec, theme: Theme, x: np.ndarray, times: list) -> None:
    for note in spec.notes:
        where = note.get("x")
        text = note.get("text", "")
        if not where or not text:
            continue
        try:
            position = mdates.date2num(_as_date(where))
        except ValueError:
            continue
        ax.axvline(position, color=theme.ink_muted, linewidth=1.0,
                   linestyle=(0, (3, 4)), zorder=2, alpha=0.7)
        ax.text(
            position, ax.get_ylim()[1], f" {text}", color=theme.ink_muted,
            fontsize=theme.label_size - 1, va="top", zorder=5, rotation=90,
        )


def _titles(fig: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    fig.text(0.06, 0.955, spec.title, color=theme.ink,
             fontsize=theme.title_size + 3, fontweight="bold", va="top")
    if spec.subtitle:
        fig.text(0.06, 0.905, spec.subtitle, color=theme.ink_secondary,
                 fontsize=theme.font_size + 2, va="top")


def _footer(fig: Any, spec: AnalyticsSpec, theme: Theme) -> None:
    """Source and as-of, burned in. Same rule as the price chart, same reason."""
    left = " · ".join(p for p in (spec.source, spec.as_of) if p)
    if left:
        fig.text(0.06, 0.025, left, color=theme.ink_muted, fontsize=theme.label_size - 1)
    if spec.degraded:
        fig.text(0.975, 0.025, "DEGRADED — partial or stale data",
                 color=theme.risk, fontsize=theme.label_size - 1,
                 fontweight="bold", ha="right")


def _fmt(value: float, spec: AnalyticsSpec, *, tick: bool = False) -> str:
    if not np.isfinite(value):
        return "—"
    if spec.value_kind == "percent":
        return f"{value:+.1f}%" if not tick else f"{value:.0f}%"
    if spec.value_kind == "rate":
        return f"{value:.2f}%" if not tick else f"{value:.0f}%"
    if spec.value_kind == "price":
        return f"{value:,.2f}"
    if spec.value_kind == "ratio":
        return f"{value:,.2f}"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1e9:,.1f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1e6:,.1f}M"
    if abs(value) >= 10_000:
        return f"{value:,.0f}"
    unit = spec.unit if not tick else ""
    return f"{value:,.2f}{(' ' + unit) if unit else ''}"


def _as_date(value: str) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
