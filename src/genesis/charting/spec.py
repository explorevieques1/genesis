# Spec: Genesis Markdown/70-Schemas/Markup Spec Schema.md
"""The Markup Spec: what the system believes about a chart, as an object.

Markup Spec.md's argument in one line -- *an image can do none of these* --
becomes five properties this module has to actually hold, not merely describe:

**Immutable.** Every model here is ``frozen``. A re-mark is
:meth:`MarkupSpec.remark`, which returns a *new* spec with ``parent`` set. The
parent chain is the story of how a read of a symbol evolved, and it is only a
story if nobody edits the earlier chapters. Immutability is also what makes
`diff_spec` possible at all: re-rendering a three-month-old spec against today's
bars is only meaningful if the spec is provably the one the agent reasoned about.

**Every annotation carries a `why`.** Required by validator on every kind except
``text``. An unexplained line is noise, and the note is blunt about the reason:
six months later you will not remember what you meant.

**Every price traces to a tool result.** :meth:`MarkupSpec.prices` enumerates
every number an annotation asserts, and :func:`unsourced_prices` diffs that
against what the computation actually returned. This is the check behind Safety
Invariants' *no price in a spec may originate from an LLM* -- the model selects
and explains levels; it never types a number. Enforced by code because a prompt
instruction cannot be enforced at all.

**Capped.** ``MAX_ANNOTATIONS``. A chart with forty levels has none, and
restraint is the one skill this family is graded on.

**Renderable from itself.** ``bars_ref`` names the exact window and source the
spec was built from, so the render is reproducible years later from the spec
alone -- the acceptance criterion Charting Engine.md sets.

The discriminated union is on ``kind``, so a payload with an unknown kind is a
loud validation error rather than a silently dropped annotation. A dropped
annotation is a level nobody watches.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from genesis.charting.timeframes import normalise
from genesis.ids import new_id

__all__ = [
    "MAX_ANNOTATIONS",
    "Annotation",
    "BarsRef",
    "Fib",
    "Level",
    "Line",
    "Marker",
    "MarkupSpec",
    "Projection",
    "RenderRef",
    "Structure",
    "TextNote",
    "TradePlan",
    "Zone",
    "unsourced_prices",
]

#: Agent — Chart Markup: *"Maximum ~8 levels per chart. If more qualify, keep
#: the strongest."* Configurable at the call site via
#: :meth:`MarkupSpec.build`, but never silently unbounded.
MAX_ANNOTATIONS = 8

#: How close two prices must be to count as the same price when checking
#: provenance. Floating point round-trips through JSON and a renderer, and a
#: level that came back as 122.10000000000001 is not a hallucination.
PRICE_EPSILON = 1e-6


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------


class _Annotated(_Frozen):
    """Common fields. ``why`` is required here and only relaxed by ``text``."""

    id: str = ""
    label: str
    why: str = ""
    #: Which computation produced this. Not decoration: it is how
    #: Agent — Insight Miner later answers *"do my anchored-VWAP levels hold
    #: better than my trendlines?"* -- a question that needs the derivation,
    #: not the price.
    source: str = ""

    @model_validator(mode="after")
    def _require_why(self) -> _Annotated:
        if not self.why.strip():
            raise ValueError(
                f"annotation {self.label!r} has no `why` — an unexplained line "
                f"on a chart is noise (Markup Spec Schema)"
            )
        return self


class Level(_Annotated):
    """A horizontal price: S/R, PDH/PDL, POC, VWAP, a moving average."""

    kind: Literal["level"] = "level"
    price: float
    type: Literal[
        "support", "resistance", "pivot", "vwap", "poc", "value_area", "ma"
    ]
    #: touches x recency x reaction x volume, normalised to 0..1. Scored, never
    #: asserted -- Agent — Chart Markup is explicit that strength is computed.
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    touches: int = Field(default=0, ge=0)
    #: Populated by confluence merging. Three coincident levels become one
    #: level naming all three, because that is what a trader sees.
    confluence: tuple[str, ...] = ()

    @field_validator("confluence", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v


class Zone(_Annotated):
    """A price band: FVG, supply, demand, value area, order block."""

    kind: Literal["zone"] = "zone"
    from_price: float = Field(alias="from")
    to_price: float = Field(alias="to")
    subtype: Literal["fvg", "supply", "demand", "value_area", "order_block", "orb"]

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _ordered(self) -> Zone:
        if self.from_price > self.to_price:
            raise ValueError(
                f"zone {self.label!r} has from > to ({self.from_price} > "
                f"{self.to_price}); a zone with inverted bounds renders as "
                f"nothing and watches for nothing"
            )
        return self

    @property
    def midpoint(self) -> float:
        return (self.from_price + self.to_price) / 2


class Line(_Annotated):
    """A fitted trendline or channel edge. Two or more (time, price) points."""

    kind: Literal["line"] = "line"
    points: tuple[tuple[str, float], ...]
    touches: int = Field(default=0, ge=0)

    @field_validator("points", mode="before")
    @classmethod
    def _points(cls, v: Any) -> Any:
        if isinstance(v, list):
            return tuple(tuple(p) for p in v)
        return v

    @model_validator(mode="after")
    def _enough(self) -> Line:
        if len(self.points) < 2:
            raise ValueError(f"line {self.label!r} needs at least two points")
        return self


class Projection(Line):
    """Where price is expected to go. Rendered dashed, always.

    A separate kind rather than a flag on ``line`` because the render must not
    be able to confuse the two: a solid line says *this happened*, a dashed one
    says *this is a guess*, and drawing a guess as a fact is the one rendering
    mistake that changes what a person does.
    """

    kind: Literal["projection"] = "projection"  # type: ignore[assignment]


class Marker(_Annotated):
    """A point event: earnings, a fill, a news spike."""

    kind: Literal["marker"] = "marker"
    time: str
    price: float


class TradePlan(_Annotated):
    """Entry, stop and targets, drawn as a risk-reward box.

    **This is not an order and cannot become one.** There is no size field, no
    account, no broker. Safety Invariants §1 puts the only path to a broker
    through propose_order -> approval -> place_approved, and a trade_plan
    annotation is a *drawing*. Keeping size out of the schema is what stops this
    object from being one field away from an order.
    """

    kind: Literal["trade_plan"] = "trade_plan"
    side: Literal["long", "short"]
    entry: float
    stop: float
    targets: tuple[float, ...] = ()
    rr: float | None = None
    idea: str | None = None

    @field_validator("targets", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def _coherent(self) -> TradePlan:
        # A long whose stop is above its entry is not a trade plan, it is a
        # transcription error -- and it would render as an inverted risk box
        # that looks deliberate.
        if self.side == "long" and self.stop >= self.entry:
            raise ValueError(
                f"long plan {self.label!r}: stop {self.stop} is not below entry "
                f"{self.entry}"
            )
        if self.side == "short" and self.stop <= self.entry:
            raise ValueError(
                f"short plan {self.label!r}: stop {self.stop} is not above entry "
                f"{self.entry}"
            )
        return self

    @property
    def computed_rr(self) -> float | None:
        """R:R to the first target, computed here rather than trusted.

        ``rr`` arrives from whoever built the annotation. This recomputes it
        from entry, stop and target -- the arithmetic is trivial and the
        alternative is speaking a reward-to-risk figure that nobody checked.
        """
        if not self.targets:
            return None
        risk = abs(self.entry - self.stop)
        if risk <= 0:
            return None
        reward = abs(self.targets[0] - self.entry)
        return round(reward / risk, 2)


class Fib(_Annotated):
    """Retracements from the dominant swing, chosen by structure not by hand."""

    kind: Literal["fib"] = "fib"
    anchor_from: tuple[str, float]
    anchor_to: tuple[str, float]
    retracements: tuple[float, ...] = (0.236, 0.382, 0.5, 0.618, 0.786)

    @field_validator("anchor_from", "anchor_to", mode="before")
    @classmethod
    def _pair(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @field_validator("retracements", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    def prices(self) -> dict[float, float]:
        """Retracement ratio -> price. Derived, so it cannot drift from the anchors."""
        start, end = self.anchor_from[1], self.anchor_to[1]
        span = end - start
        return {r: end - span * r for r in self.retracements}


class TextNote(_Annotated):
    """Free annotation. The one kind exempt from ``why`` -- it *is* the why."""

    kind: Literal["text"] = "text"
    content: str
    position: tuple[str, float] | None = None

    @model_validator(mode="after")
    def _require_why(self) -> TextNote:  # type: ignore[override]
        return self


Annotation = Annotated[
    Union[Level, Zone, Line, Projection, Marker, TradePlan, Fib, TextNote],
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------
# The spec
# --------------------------------------------------------------------------


class BarsRef(_Frozen):
    """Exactly which bars this spec was built from.

    Without this a stored spec is un-rerenderable, and *"every chart in the
    vault is re-renderable from its stored spec alone"* stops being true.
    """

    source: str
    from_date: str = Field(alias="from")
    to_date: str = Field(alias="to")
    adjusted: bool = True
    bars: int = 0
    #: Market Data Sources' trust tier, travelling with the data. A spec built
    #: from tier-3 bars must never be mistaken for one built from tier-1.
    tier: int = 3

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Structure(_Frozen):
    """Deterministic measurements. No model produces any field here."""

    trend: Literal["up", "down", "range"] = "range"
    swing: Literal["HH-HL", "LH-LL", "mixed", "range"] = "range"
    regime: str | None = None
    volatility_pct_rank: float | None = Field(default=None, ge=0.0, le=1.0)
    atr14: float | None = None
    trend_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    range_high: float | None = None
    range_low: float | None = None
    contraction: float | None = None


class RenderRef(_Frozen):
    theme: str = "dark"
    size: tuple[int, int] = (1600, 900)
    output: str | None = None
    rendered_at: str | None = None
    #: sha256 of the image bytes. The determinism check, and the cache key the
    #: vision interpretation is stored against.
    render_hash: str | None = None

    @field_validator("size", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v


class MarkupSpec(_Frozen):
    """One immutable belief about one chart."""

    id: str = Field(default_factory=lambda: new_id("ms"))
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "chart-markup"
    trace_id: str | None = None
    degraded: bool = False

    symbol: str
    timeframe: str
    as_of: datetime
    parent: str | None = None
    bars_ref: BarsRef

    annotations: tuple[Annotation, ...] = ()
    structure: Structure = Structure()
    render: RenderRef = RenderRef()

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, v: str) -> str:
        return normalise(v)

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("annotations", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def _capped_and_identified(self) -> MarkupSpec:
        if len(self.annotations) > MAX_ANNOTATIONS:
            raise ValueError(
                f"{len(self.annotations)} annotations exceeds the cap of "
                f"{MAX_ANNOTATIONS}. Restraint is the skill — merge confluent "
                f"levels or drop the weakest (Agent — Chart Markup)"
            )
        seen = {a.id for a in self.annotations if a.id}
        if len(seen) != len([a for a in self.annotations if a.id]):
            raise ValueError("duplicate annotation ids in one spec")
        return self

    # -- construction ------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        symbol: str,
        timeframe: str,
        as_of: datetime,
        bars_ref: BarsRef,
        annotations: list[Any],
        structure: Structure | None = None,
        created_by: str = "chart-markup",
        trace_id: str | None = None,
        parent: str | None = None,
        degraded: bool = False,
        max_annotations: int = MAX_ANNOTATIONS,
        render: RenderRef | None = None,
    ) -> MarkupSpec:
        """Assemble a spec, trimming to the cap by strength rather than failing.

        Trimming rather than raising is deliberate and is the opposite of the
        model's usual policy of failing loudly. The cap is an editorial rule,
        not a correctness one: the caller has already computed thirty real
        levels, and the right response to *"too many good levels"* is to keep
        the strongest eight, which is exactly what a person does. Everything
        dropped is still in the computation's own output, so nothing is lost
        that was ever load-bearing.

        Annotation ids are assigned here, densely and in order, so a spec's ids
        are stable for the same input -- which the render hash depends on.
        """
        kept = _trim(annotations, max_annotations)
        numbered = [
            a.model_copy(update={"id": a.id or f"ann_{i:02d}"})
            for i, a in enumerate(kept, start=1)
        ]
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            as_of=as_of,
            bars_ref=bars_ref,
            annotations=tuple(numbered),
            structure=structure or Structure(),
            created_by=created_by,
            trace_id=trace_id,
            parent=parent,
            degraded=degraded,
            render=render or RenderRef(),
        )

    def remark(self, **changes: Any) -> MarkupSpec:
        """A child spec. The original is untouched, by construction.

        ``id`` and ``created`` are regenerated and ``parent`` is set to self --
        none of which the caller may override, because a re-mark that kept the
        parent's id would break the lineage silently and a re-mark with no
        parent would break it loudly six months later.
        """
        for reserved in ("id", "created", "parent"):
            changes.pop(reserved, None)
        return self.model_copy(
            update={
                **changes,
                "id": new_id("ms"),
                "created": datetime.now(UTC),
                "parent": self.id,
            }
        )

    def with_render(self, ref: RenderRef) -> MarkupSpec:
        """The one permitted amendment, and it does not touch the belief.

        Rendering is something that happens *to* a spec, not a change of mind:
        the annotations, the structure and the bars are byte-identical, only the
        output path and hash are filled in. Kept as a method rather than a
        mutation so the immutability rule needs no exception.
        """
        return self.model_copy(update={"render": ref})

    # -- provenance --------------------------------------------------------

    def prices(self) -> list[float]:
        """Every number this spec asserts about price.

        The input to the hallucination check. Fib retracements are included via
        their derived prices, since a wrong anchor produces wrong retracements
        that look authoritative.
        """
        out: list[float] = []
        for a in self.annotations:
            if isinstance(a, Level):
                out.append(a.price)
            elif isinstance(a, Zone):
                out.extend((a.from_price, a.to_price))
            elif isinstance(a, (Projection, Line)):
                out.extend(p[1] for p in a.points)
            elif isinstance(a, Marker):
                out.append(a.price)
            elif isinstance(a, TradePlan):
                out.append(a.entry)
                out.append(a.stop)
                out.extend(a.targets)
            elif isinstance(a, Fib):
                out.append(a.anchor_from[1])
                out.append(a.anchor_to[1])
        return out

    def levels(self) -> tuple[Level, ...]:
        return tuple(a for a in self.annotations if isinstance(a, Level))

    def watchable(self) -> tuple[Annotation, ...]:
        """What Agent — Level Watcher subscribes to: levels, zones, trade plans."""
        return tuple(
            a
            for a in self.annotations
            if isinstance(a, (Level, Zone, TradePlan))
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def _trim(annotations: list[Any], cap: int) -> list[Any]:
    """Keep the strongest ``cap`` annotations, preserving chart order.

    Non-level kinds are never trimmed: a trade plan or a zone is there because
    something asked for it, and dropping one to make room for a moving average
    would be the cap deciding what the chart is about.
    """
    if len(annotations) <= cap:
        return list(annotations)
    protected = [a for a in annotations if not isinstance(a, Level)]
    levels = [a for a in annotations if isinstance(a, Level)]
    room = max(cap - len(protected), 0)
    strongest = sorted(levels, key=lambda a: (-a.strength, a.price))[:room]
    keep = set(id(a) for a in protected) | set(id(a) for a in strongest)
    return [a for a in annotations if id(a) in keep][:cap]


def unsourced_prices(
    spec: MarkupSpec, sourced: list[float], *, epsilon: float = PRICE_EPSILON
) -> list[float]:
    """Prices in the spec that no tool result contains.

    The mechanical form of *"never state a price you did not receive from a tool
    call"*. Returns the offenders rather than a bool, because the useful failure
    message names the number that was invented.

    Tolerance is absolute rather than relative on purpose: a level rounded from
    122.0999 to 122.10 is the same level, while a relative epsilon would quietly
    accept a $2 error on a $2000 stock.
    """
    remaining = list(sourced)
    bad: list[float] = []
    for price in spec.prices():
        hit = next(
            (s for s in remaining if abs(s - price) <= max(epsilon, 0.005)), None
        )
        if hit is None:
            bad.append(price)
        else:
            remaining.remove(hit)
    return bad
