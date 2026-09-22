# Spec: Genesis Markdown/10-Architecture/Charting Engine.md
"""The visual design system. One place, so every render is the same render.

Charting Engine.md sets the rules -- *"dark theme, high contrast, no gridline
clutter"*, every level labelled with its price and type, zones translucent,
projections dashed, timestamp burned into the corner, fixed output size -- and
adds the reason they are rules rather than preferences: **a chart is read by two
audiences, a person and a vision model, and the vision model's interpretation is
cached against the spec id.** A render that drifts silently invalidates that
cache without anyone noticing.

So the palette is fixed, validated, and stated once here.

Colour choices worth the words
------------------------------
**Candles are teal and red, not green and red.** Green/red is the classic
red-green confusion, and it is the single most common palette in this industry.
Teal-up/red-down is the same message with a measured separation that survives
protanopia (normal-vision ΔE 27.5), and it is what the platform this system
feeds -- TradingView -- ships as its own default, so the two screens agree.
Direction is *also* encoded geometrically: up candles are hollow, down candles
filled. Colour is never the only channel.

**Level colours are roles, not a series palette.** Resistance, support, VWAP,
POC and moving averages get fixed hues, and every level is drawn with its price
and type in a label chip regardless. Identity is carried by the text; the colour
only speeds up the reading. The seven role hues were validated as a categorical
set against this surface -- all six checks pass, worst adjacent CVD ΔE 8.4.

**Grid is nearly invisible on purpose.** The data is candles and horizontal
lines; a visible grid competes with the level lines for exactly the same visual
channel, which is the one thing on the chart that must be unambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["DARK", "Theme", "level_color", "zone_color"]


@dataclass(frozen=True)
class Theme:
    """Every colour and metric a renderer is allowed to use."""

    name: str

    # -- surfaces and ink --------------------------------------------------
    surface: str
    panel: str
    ink: str
    ink_secondary: str
    ink_muted: str
    grid: str
    axis: str
    border: str

    # -- price marks -------------------------------------------------------
    up: str
    down: str
    volume_up: str
    volume_down: str

    # -- annotation roles --------------------------------------------------
    resistance: str
    support: str
    pivot: str
    vwap: str
    poc: str
    ma: str
    trendline: str
    projection: str

    # -- trade plan --------------------------------------------------------
    risk: str
    reward: str

    # -- categorical series, for the analytics renderer --------------------
    series: tuple[str, ...]

    # -- sequential and diverging ------------------------------------------
    sequential: tuple[str, ...]
    diverging_low: str
    diverging_mid: str
    diverging_high: str

    # -- metrics -----------------------------------------------------------
    size: tuple[int, int] = (1600, 900)
    dpi: int = 100
    #: matplotlib's bundled face. Chosen over the system sans deliberately:
    #: Charting Engine.md requires byte-identical renders, and a system font
    #: stack resolves differently on two machines, which changes glyph metrics,
    #: which changes pixels. Determinism beats typographic preference here.
    font: str = "DejaVu Sans"
    font_size: float = 11.0
    title_size: float = 17.0
    label_size: float = 10.0

    @property
    def figsize(self) -> tuple[float, float]:
        return (self.size[0] / self.dpi, self.size[1] / self.dpi)

    def sized(self, width: int, height: int) -> Theme:
        from dataclasses import replace

        return replace(self, size=(width, height))


DARK = Theme(
    name="dark",
    surface="#12130f",
    panel="#1a1a19",
    ink="#ffffff",
    ink_secondary="#c3c2b7",
    ink_muted="#898781",
    grid="#22231f",
    axis="#383835",
    border="#2c2c2a",
    up="#199e70",
    down="#e66767",
    volume_up="#17624a",
    volume_down="#8a4444",
    resistance="#d95926",
    support="#3987e5",
    pivot="#898781",
    vwap="#c98500",
    poc="#9085e9",
    ma="#d55181",
    trendline="#c3c2b7",
    projection="#898781",
    risk="#d03b3b",
    reward="#0ca30c",
    # The validated dark categorical order. Assigned by slot, never cycled --
    # a ninth series folds into "Other" rather than reusing slot 1.
    series=(
        "#3987e5", "#d95926", "#199e70", "#c98500",
        "#d55181", "#008300", "#9085e9", "#e66767",
    ),
    sequential=(
        "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5",
        "#256abf", "#184f95", "#0d366b",
    ),
    diverging_low="#e66767",
    diverging_mid="#383835",
    diverging_high="#3987e5",
)


#: Annotation type -> theme attribute. A dict rather than a chain of ifs so an
#: unknown type falls through to a single obvious default instead of silently
#: inheriting whichever branch happened to be last.
_LEVEL_ROLES = {
    "resistance": "resistance",
    "support": "support",
    "pivot": "pivot",
    "vwap": "vwap",
    "poc": "poc",
    "value_area": "poc",
    "ma": "ma",
}

_ZONE_ROLES = {
    "fvg": "support",
    "demand": "support",
    "supply": "resistance",
    "value_area": "poc",
    "order_block": "ma",
    "orb": "vwap",
}


def level_color(theme: Theme, level_type: str) -> str:
    return getattr(theme, _LEVEL_ROLES.get(level_type, "pivot"))


def zone_color(theme: Theme, subtype: str) -> str:
    return getattr(theme, _ZONE_ROLES.get(subtype, "pivot"))
