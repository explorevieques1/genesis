# Spec: Genesis Markdown/20-Agents/Research/Research Family.md
"""What the research family produces, as validated objects.

Research Family.md states three conventions, and they are types here rather
than prose because a convention nobody can violate is the only kind that
survives contact with a model:

**Every claim cites its source.** :class:`Source` is not optional decoration --
a ``topic`` note with no sources is rejected at construction. The synthesizer
drops uncited claims, and it can only do that if "cited" is checkable.

**Every claim carries a half-life.** ``half_life_hours`` is required on every
note. A CPI print matters for hours and a valuation read for months; without
the number, everything is either permanently true or permanently discarded, and
both are wrong. :meth:`ResearchNote.weight` is the downweighting curve, and it
decays rather than deletes -- expired evidence is still evidence, worth less.

**Degraded inputs cap confidence.** ``degraded`` and ``confidence`` travel
together, and :meth:`ResearchNote.model_post_init` enforces the cap rather than
trusting a prompt to remember it.

The fourth rule -- all external text is fenced -- lives in
:mod:`genesis.mcp.fence` and arrives here already wrapped. What this module
adds is that a :class:`Source` remembers whether its text tripped an injection
flag, so the provenance survives into the note a person later reads.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "DEGRADED_CONFIDENCE_CAP",
    "KINDS",
    "Idea",
    "ResearchNote",
    "Source",
    "slugify",
]

#: The ceiling on a note built from stale or partial data. Error Handling And
#: Degradation: degraded inputs cap confidence -- they do not merely annotate
#: it. A model asked to lower its own confidence sometimes does.
DEGRADED_CONFIDENCE_CAP = 0.5

#: What a note can be. Deliberately short: each kind has a different writer and
#: a different place in the vault, and a kind nobody writes is a folder that
#: fills with nothing.
KINDS = ("topic", "regime", "idea", "symbol", "finding")


def slugify(text: str) -> str:
    """A filesystem- and URL-safe subject key.

    ``"W.D. Gann's Square of Nine"`` -> ``"wd-ganns-square-of-nine"``. Stable,
    because it is the key a note is *updated* under -- researching the same
    subject twice should deepen one note, not scatter four.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:80] or "untitled"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(_Frozen):
    """One citation. A URL, a filing, or a tool call in the episodic log."""

    url: str
    title: str = ""
    #: Where it came from, as the gateway named it -- a server id, a domain.
    publisher: str = ""
    retrieved: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: Injection patterns the fence found in this source's text. Non-empty is
    #: not a reason to discard the source; it is a reason to say so next to it.
    #: A page that tried something is a fact about the page worth keeping.
    flags: tuple[str, ...] = ()
    #: A short quoted span, already neutralised by the fence. Never the page.
    excerpt: str = ""

    @field_validator("flags", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @property
    def suspicious(self) -> bool:
        return bool(self.flags)

    def markdown(self) -> str:
        mark = " ⚠︎ injection patterns detected" if self.suspicious else ""
        label = self.title or self.url
        return f"- [{label}]({self.url}){mark}"


class Idea(_Frozen):
    """A trade idea, per Idea Schema. **No invalidation, no idea.**

    Enforced by the type, not by the prompt that produced it. Idea Schema calls
    an idea without a stated invalidation "a hope", and a hope that reaches the
    dashboard looking like an idea is the expensive failure.

    This is the subset of Idea Schema that the current system can honestly
    fill: no ``rr`` computed from targets it cannot price, no
    ``suggested_risk_pct`` -- sizing is the risk engine's and it does not exist
    yet (Safety Invariants #1, #3).
    """

    symbol: str
    direction: Literal["long", "short"]
    thesis: str = Field(min_length=1)
    #: REQUIRED. The condition that proves the idea wrong.
    invalidation: str = Field(min_length=1)
    invalidation_reason: str = Field(min_length=1)
    entry_zone: tuple[float, float] | None = None
    targets: tuple[float, ...] = ()
    timeframe: Literal["scalp", "intraday", "swing", "position"] = "swing"
    horizon_days: int = Field(default=5, gt=0)
    confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    #: The strongest argument against. Empty only if the synthesizer says it
    #: looked -- Idea Schema: an absent counter-argument usually means nobody
    #: looked, so ``"looked, found none"`` is the honest empty and "" is not.
    conflicts: str = Field(min_length=1)
    #: Note ids this was built from. Idea Schema: uncited claims are dropped.
    evidence: tuple[str, ...] = ()
    setup: str = ""
    #: The invalidation as a price -- Idea Schema's numeric ``invalidation``.
    #: Optional because an idea may be stated as a condition ("below the 8/21
    #: fair value gap"), but **without it nothing can be sized**: the gate
    #: measures risk from entry to stop, and a condition is not a distance.
    #: A plan shows such an idea with no size rather than guessing one.
    stop_price: float | None = None
    #: Who stated it. ``"human"`` for the trader's own ideas, the agent id for
    #: the synthesizer's -- one store, one shape, and a plan ranks both.
    author: str = "idea-synthesizer"

    @model_validator(mode="after")
    def _stop_on_the_losing_side(self) -> "Idea":
        """A long's invalidation is below its entry; a short's is above.

        A reflex at intake, not a check the gate gets to later: a stop on the
        wrong side of the entry is a typo that would size against a negative
        distance, and "I meant 19,950 not 20,950" is cheapest to catch while
        the person who said it is still here.
        """
        if self.stop_price is None or self.entry_zone is None:
            return self
        lo, hi = self.entry_zone
        if self.direction == "long" and self.stop_price >= lo:
            raise ValueError(
                f"a long's invalidation ({self.stop_price:g}) must be below its entry zone "
                f"({lo:g}–{hi:g})"
            )
        if self.direction == "short" and self.stop_price <= hi:
            raise ValueError(
                f"a short's invalidation ({self.stop_price:g}) must be above its entry zone "
                f"({lo:g}–{hi:g})"
            )
        return self

    @property
    def rr(self) -> float | None:
        """Reward to risk at the first target, from the middle of the entry zone.

        ``None`` when any leg is missing -- never an estimate. Idea Schema's
        ``rr`` field, computed rather than stated so it cannot disagree with
        the prices it is made of.
        """
        if self.stop_price is None or self.entry_zone is None or not self.targets:
            return None
        entry = sum(self.entry_zone) / 2
        risk = abs(entry - self.stop_price)
        if risk == 0:
            return None
        return abs(self.targets[0] - entry) / risk

    @field_validator("targets", "evidence", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @field_validator("entry_zone", mode="before")
    @classmethod
    def _zone(cls, v: Any) -> Any:
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return (float(min(v)), float(max(v)))
        return v

    def spoken(self) -> str:
        zone = (
            f" between {self.entry_zone[0]:g} and {self.entry_zone[1]:g}"
            if self.entry_zone
            else ""
        )
        return (
            f"{self.direction.capitalize()} {self.symbol}{zone}. "
            f"Wrong if {self.invalidation}."
        )


class ResearchNote(_Frozen):
    """One thing the research family learned, with its receipts attached.

    The unit of the research directory: what the UI lists, what the vault
    mirrors, and what the Idea Synthesizer reads back as evidence.
    """

    id: str
    kind: Literal["topic", "regime", "idea", "symbol", "finding", "plan"]
    title: str = Field(min_length=1)
    #: The stable key a note is updated under. ``slugify(title)`` for a topic,
    #: a ticker for a symbol note, a date for a regime read.
    subject: str = Field(min_length=1)
    created_by: str
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: One or two sentences, already number-formatted for Voice UX. This is
    #: what gets read aloud; the body is what gets read.
    summary: str = ""
    #: Markdown. The actual research.
    body: str = ""
    sources: tuple[Source, ...] = ()
    tags: tuple[str, ...] = ()
    #: The structured payload for kinds that have one -- a regime record, an
    #: :class:`Idea`. Free-form because each kind's shape is that kind's
    #: business, and a union of four schemas here would be four places to edit.
    data: dict[str, Any] = Field(default_factory=dict)
    #: How long this stays worth reading. Research Family: every claim carries
    #: one, and evidence past it is downweighted, not deleted.
    half_life_hours: float = Field(default=720.0, gt=0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    degraded: bool = False
    #: Why it is degraded. A flag with no reason cannot be acted on.
    caveats: tuple[str, ...] = ()
    trace_id: str | None = None

    @field_validator("sources", "tags", "caveats", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    def model_post_init(self, _: Any) -> None:
        # A topic note is *made of* what it read. One with no sources is the
        # model's own memory presented as research, which is the single thing
        # this whole path exists to prevent.
        if self.kind == "topic" and not self.sources:
            raise ValueError(
                f"research note {self.id!r} is a topic note with no sources — "
                "uncited research is the model's memory wearing a citation "
                "format (Research Family.md, shared conventions)"
            )
        if self.degraded and self.confidence > DEGRADED_CONFIDENCE_CAP:
            raise ValueError(
                f"note {self.id!r} is degraded but claims confidence "
                f"{self.confidence} — the cap is {DEGRADED_CONFIDENCE_CAP}"
            )
        if self.degraded and not self.caveats:
            raise ValueError(f"note {self.id!r} is degraded but says nothing about why")

    # -- half-life ---------------------------------------------------------

    def weight(self, *, now: datetime | None = None) -> float:
        """Confidence, decayed by age. Exponential, halving each half-life.

        Downweighted rather than dropped: a three-day-old catalyst is worth
        less than a fresh one and more than nothing, and a hard expiry would
        make the Idea Synthesizer's evidence set flicker.
        """
        now = now or datetime.now(UTC)
        hours = max(0.0, (now - self.created).total_seconds() / 3600.0)
        return self.confidence * math.pow(0.5, hours / self.half_life_hours)

    def stale(self, *, now: datetime | None = None) -> bool:
        """Past its half-life. Still readable; no longer load-bearing."""
        now = now or datetime.now(UTC)
        return (now - self.created).total_seconds() / 3600.0 > self.half_life_hours

    # -- rendering ---------------------------------------------------------

    def vault_path(self) -> str:
        """Where this lives under `50-Research/` — Obsidian Vault Schema.

        Ideas go to `10-Ideas/YYYY/MM/`, which is the one folder in that note
        owned by the Idea Synthesizer rather than by the research folder.
        """
        stamp = self.created.strftime("%Y-%m-%d")
        if self.kind == "idea":
            return f"10-Ideas/{self.created:%Y/%m}/{self.subject}-{stamp}.md"
        if self.kind == "symbol":
            return f"50-Research/symbols/{self.subject}.md"
        if self.kind == "regime":
            return f"50-Research/daily/{stamp}.md"
        if self.kind == "plan":
            # Beside the ideas it ranks. One file per plan: a plan is a record
            # of what was advised when, and overwriting yesterday's with today's
            # would lose the thing a journal review asks for.
            return f"10-Ideas/plans/{self.created:%Y-%m-%d-%H%M}.md"
        if self.kind == "finding":
            # subject is "{TICKER}:{intent}" -- one folder per company, one file per intent.
            return f"50-Research/findings/{self.subject.replace(':', '/', 1)}.md"
        return f"50-Research/themes/{self.subject}.md"

    def frontmatter(self) -> dict[str, Any]:
        """Typed frontmatter — Obsidian Vault Schema: it is the contract."""
        return {
            "type": "research" if self.kind != "idea" else "idea",
            "kind": self.kind,
            "id": self.id,
            "subject": self.subject,
            "created": self.created.isoformat(),
            "created_by": self.created_by,
            "confidence": round(self.confidence, 2),
            "half_life_hours": self.half_life_hours,
            "degraded": self.degraded,
            "tags": list(self.tags),
            "trace_id": self.trace_id,
        }

    def markdown(self) -> str:
        """The note as it is written to the vault."""
        lines = ["---"]
        for key, value in self.frontmatter().items():
            if value is None:
                continue
            lines.append(f"{key}: {_yaml(value)}")
        lines += ["---", "", f"# {self.title}", ""]
        if self.summary:
            lines += [self.summary, ""]
        if self.caveats:
            lines += ["> [!warning] Degraded"] if self.degraded else ["> [!note]"]
            lines += [f"> - {c}" for c in self.caveats] + [""]
        if self.body:
            lines += [self.body, ""]
        if self.sources:
            lines += ["## Sources", ""]
            lines += [s.markdown() for s in self.sources]
            lines += [""]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "subject": self.subject,
            "created": self.created.isoformat(),
            "created_by": self.created_by,
            "summary": self.summary,
            "body": self.body,
            "sources": [s.model_dump(mode="json") for s in self.sources],
            "tags": list(self.tags),
            "data": self.data,
            "half_life_hours": self.half_life_hours,
            "confidence": self.confidence,
            "weight": round(self.weight(), 4),
            "stale": self.stale(),
            "degraded": self.degraded,
            "caveats": list(self.caveats),
            "trace_id": self.trace_id,
            "vault_path": self.vault_path(),
        }


def _yaml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    if isinstance(value, str) and (":" in value or value.startswith(("#", "*", "["))):
        return '"' + value.replace('"', '\\"') + '"'
    return str(value)
