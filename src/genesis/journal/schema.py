# Spec: Genesis Markdown/70-Schemas/Trade Journal Schema.md
"""What the journal stores: entries, lessons, hypotheses, observations.

Trade Journal Schema.md's central design decision is the **machine/human split**,
and it is worth restating because every other choice here follows from it:

> A journal entry with zero human input is still useful. That's deliberate --
> journaling fails for everyone because it demands effort at the worst possible
> moment.

So machine fields are required and computed; human fields are all optional and
all default to empty. A note is complete the instant the trade closes.

Four record types, and the last two are what make the family *compound* rather
than merely report:

:class:`JournalEntry`
    One closed trade. Machine fields immutable, human fields patchable once.
:class:`Lesson`
    A behavioural finding with enough evidence to act on. Insight Miner is the
    only writer.
:class:`Hypothesis`
    A finding **without** enough evidence yet. Agent — Insight Miner's rule is
    *"below that, log it as a hypothesis to watch, not a lesson"* -- and this is
    the type that makes that rule constructive instead of merely restrictive. A
    hypothesis accrues observations until it qualifies, which is how the system
    gets smarter over months rather than starting from zero each night.
:class:`Observation`
    One durable fact worth remembering: a level that held, an idea that was
    skipped, a stop that moved. Not restricted to trades -- which matters,
    because the charting family is producing scoreable outcomes today and
    execution does not exist yet.

Every quantity that could be a claim carries its evidence: an ``n``, a period,
and the ids it was computed from. That is not decoration. Agent — Performance
Analyst's entire discipline is *"always state the sample size in the same breath
as the finding"*, and a schema where ``n`` is optional is a schema that will
eventually carry a finding without one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from genesis.ids import new_id

__all__ = [
    "CONCLUSIVE_N",
    "HARD_LIMIT_N",
    "LESSON_N",
    "Evidence",
    "Hypothesis",
    "JournalEntry",
    "Lesson",
    "Observation",
    "PlanAdherence",
]

#: Agent — Performance Analyst: below this a slice is *indicative, not
#: conclusive*, and the note has to say so.
CONCLUSIVE_N = 20

#: Agent — Insight Miner: *"Minimum 20 observations for a lesson."*
LESSON_N = 20

#: *"30 before recommending a hard limit."* A wall the risk engine enforces is a
#: different class of claim from a sentence in a note, and it needs more.
HARD_LIMIT_N = 30


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(_Frozen):
    """What a finding is built on. Never optional, because a finding without it
    is an opinion wearing a number."""

    observations: int = Field(ge=0)
    period_from: str = ""
    period_to: str = ""
    #: Trade, observation or spec ids. The audit trail from a claim to its rows.
    ids: tuple[str, ...] = ()
    #: How much the author would bet on it, 0..1. Explicitly not a p-value: the
    #: analyst is slicing a small sample many ways and some of what it finds is
    #: coincidence, so this is a stated willingness to bet, not a test statistic.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("ids", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @property
    def conclusive(self) -> bool:
        return self.observations >= CONCLUSIVE_N

    def qualifier(self) -> str:
        """The phrase that must travel with the finding.

        Returned as text rather than left to each caller to remember, because
        "state the sample size in the same breath" is a rule about *sentences*,
        and the only reliable way to keep it is to make the sentence carry it.
        """
        if self.observations == 0:
            return "no observations"
        if not self.conclusive:
            return f"{self.observations} observations — indicative, not conclusive"
        return f"{self.observations} observations"


class PlanAdherence(_Frozen):
    """Plan versus execution. Computed from the ledger, never self-reported.

    ``stop_moved`` is the field the whole schema exists to carry. Trade Journal
    Schema calls it *"the single most predictive input to Agent — Insight
    Miner"*, and it is computed precisely because self-reporting on this
    particular behaviour is unreliable in a way that is entirely human and
    entirely predictable.
    """

    entry_in_zone: bool | None = None
    size_as_planned: bool | None = None
    stop_as_planned: bool | None = None
    #: True when the stop was moved *against* the position — the direction is
    #: the whole signal, so a plain "was it moved" boolean would be useless.
    stop_moved: bool = False
    exit_as_planned: bool | None = None
    deviations: tuple[str, ...] = ()

    @field_validator("deviations", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @property
    def followed(self) -> bool:
        """Did *the trader* follow the plan.

        Two subtleties, both from the schema's own worked example, where
        ``size_as_planned: false`` sits beside ``plan_followed: true``:

        **Size is excluded.** A position resized 192 -> 120 was resized by the
        pre-trade risk engine, which is the system working exactly as designed.
        Scoring it as a discipline failure would make every correctly-gated
        trade look like a deviation and would poison every adherence statistic
        the Insight Miner computes.

        **``None`` is "not checked", not "failed".** An entry with no planned
        stop cannot have deviated from one, and counting the absence as a
        deviation would penalise incomplete records rather than bad behaviour.
        """
        checks = (self.entry_in_zone, self.stop_as_planned, self.exit_as_planned)
        return not self.stop_moved and all(c is not False for c in checks)


class JournalEntry(_Frozen):
    """One closed trade, in the note's shape."""

    id: str = Field(default_factory=lambda: new_id("jrn"))
    trace_id: str | None = None
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # -- identity ----------------------------------------------------------
    symbol: str
    direction: Literal["long", "short"]
    account: str = "primary"
    strategy: str | None = None
    setup: str | None = None
    idea: str | None = None

    # -- execution ---------------------------------------------------------
    entry_price: float
    entry_ts: datetime
    exit_price: float
    exit_ts: datetime
    qty: int = Field(gt=0)
    exit_reason: Literal[
        "target", "stop", "trail", "time", "manual", "invalidation"
    ] = "manual"
    duration_min: float = 0.0
    bars_held: int = 0

    # -- risk and result ---------------------------------------------------
    planned_stop: float | None = None
    planned_target: float | None = None
    planned_rr: float | None = None
    risk_dollars: float | None = None
    pnl_gross: float = 0.0
    fees: float = 0.0
    pnl_net: float = 0.0
    #: The unit everything downstream is measured in. R rather than dollars is
    #: what makes a $200 account and a $200k account produce comparable
    #: statistics, and it is why every slice in the analyst is expectancy in R.
    r_multiple: float | None = None
    mae_r: float | None = None
    mfe_r: float | None = None
    portfolio_heat_at_entry: float | None = None

    # -- context -----------------------------------------------------------
    regime: str | None = None
    session_segment: str | None = None
    day_of_week: str | None = None
    markup_entry: str | None = None
    markup_exit: str | None = None
    chart_entry: str | None = None
    chart_exit: str | None = None
    slippage_bps: float | None = None
    fills: tuple[str, ...] = ()

    # -- the thesis, verbatim ---------------------------------------------
    #: Copied, never re-summarised. Six months later you need to read what you
    #: believed at the time, not a tidied version -- memory reliably rewrites
    #: the thesis of a losing trade into something more reasonable than it was.
    thesis: str = ""

    plan_adherence: PlanAdherence = PlanAdherence()

    # -- human, all optional ----------------------------------------------
    emotion_entry: str | None = None
    emotion_hold: str | None = None
    confidence_felt: float | None = Field(default=None, ge=0.0, le=1.0)
    followed_plan: bool | None = None
    what_i_thought: str = ""
    what_id_do_differently: str = ""
    notes: str = ""
    prompted_at: datetime | None = None

    tags: tuple[str, ...] = ()

    @field_validator("tags", "fills", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _coherent(self) -> JournalEntry:
        if self.exit_ts < self.entry_ts:
            raise ValueError(
                f"{self.symbol}: exit {self.exit_ts} precedes entry {self.entry_ts}"
            )
        return self

    @property
    def is_winner(self) -> bool | None:
        if self.r_multiple is None:
            return None
        return self.r_multiple > 0

    @property
    def has_human_input(self) -> bool:
        return any(
            (
                self.emotion_entry, self.emotion_hold, self.followed_plan is not None,
                self.what_i_thought, self.what_id_do_differently, self.notes,
            )
        )

    def human_patch(self, **fields: Any) -> JournalEntry:
        """Fill in the human half. The only mutation the schema permits.

        Machine fields are not in the accepted set, so a patch cannot rewrite a
        price, an R multiple or a plan-adherence flag. That boundary is the
        reason the analyst's numbers can be trusted: the reflective half is
        subjective by design, and it must not be able to leak into the
        arithmetic.
        """
        allowed = {
            "emotion_entry", "emotion_hold", "confidence_felt", "followed_plan",
            "what_i_thought", "what_id_do_differently", "notes", "tags",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(
                f"human_patch cannot set machine fields: {', '.join(sorted(unknown))}"
            )
        return self.model_copy(
            update={**fields, "prompted_at": datetime.now(UTC)}
        )


class Lesson(_Frozen):
    """A behavioural finding with enough evidence to change a decision."""

    id: str = Field(default_factory=lambda: new_id("lesson"))
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: The detector that produced this, stable across nights. Matching on the
    #: key is what makes a repeated finding *supersede* rather than accumulate;
    #: matching on wording cannot, because the wording is the half a model is
    #: allowed to change.
    key: str = ""
    title: str
    finding: str
    evidence: Evidence
    #: Machine-readable conditions the Idea Synthesizer matches an idea against.
    #: A lesson nothing can match is a diary entry.
    applies_when: tuple[str, ...] = ()
    recommended_action: str = ""
    enforcement: Literal["advisory", "warn", "hard_limit"] = "advisory"
    status: Literal["active", "superseded", "retired"] = "active"
    supersedes: str | None = None
    #: A hard limit is a wall the risk engine enforces, so it needs a person to
    #: agree. The system proposes; you decide.
    approved_by_human: bool = False

    @field_validator("applies_when", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def _evidence_supports_the_claim(self) -> Lesson:
        """The thresholds, enforced by the type rather than by the prompt.

        A model asked not to write a lesson on twelve observations will mostly
        comply. This makes "mostly" irrelevant.
        """
        if self.evidence.observations < LESSON_N:
            raise ValueError(
                f"a lesson needs at least {LESSON_N} observations, got "
                f"{self.evidence.observations} — record it as a Hypothesis instead"
            )
        if self.enforcement == "hard_limit":
            if self.evidence.observations < HARD_LIMIT_N:
                raise ValueError(
                    f"a hard_limit needs at least {HARD_LIMIT_N} observations, got "
                    f"{self.evidence.observations}"
                )
            if not self.approved_by_human:
                raise ValueError(
                    "a hard_limit becomes a constraint the risk engine enforces "
                    "and requires explicit human approval — propose it as 'warn'"
                )
        return self

    def spoken(self) -> str:
        return f"{self.finding.strip()} ({self.evidence.qualifier()})."


class Hypothesis(_Frozen):
    """A finding that does not yet have the evidence to be a lesson.

    The most quietly important type here. Without it, every nightly pass would
    rediscover the same under-evidenced pattern, decline to write it, and forget
    -- and the system would never accumulate anything. With it, a pattern is
    recorded once and then *accrues*: ``observations`` grows, ``last_seen``
    moves, and one night it crosses the threshold and becomes a lesson.

    That is the whole mechanism by which this family compounds.
    """

    id: str = Field(default_factory=lambda: new_id("hyp"))
    created: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: Stable across nights, so the same pattern updates rather than duplicating.
    key: str
    title: str
    finding: str
    evidence: Evidence
    applies_when: tuple[str, ...] = ()
    #: Set when it graduates, so the trail from hypothesis to lesson survives.
    promoted_to: str | None = None

    @field_validator("applies_when", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    @property
    def ready(self) -> bool:
        return self.evidence.observations >= LESSON_N and self.promoted_to is None

    def promote(self, **changes: Any) -> Lesson:
        """Become a lesson, carrying the accumulated evidence — and the key."""
        return Lesson(
            key=changes.pop("key", self.key),
            title=changes.pop("title", self.title),
            finding=changes.pop("finding", self.finding),
            evidence=changes.pop("evidence", self.evidence),
            applies_when=changes.pop("applies_when", self.applies_when),
            **changes,
        )


class Observation(_Frozen):
    """One durable fact worth remembering, whatever produced it.

    Deliberately not trade-shaped. The system has things worth learning from
    long before it has fills: a marked level that held or broke, an idea that
    was ranked and never taken, a data feed that was stale at the open. Every
    one of those is an observation, and every one of them is evidence a lesson
    might later rest on.

    ``subject`` is the entity the fact is about (``level:NVDA:122.10``,
    ``idea_01J8XS``, ``mcp:news``) so observations aggregate by the thing rather
    than by the run that noticed them.
    """

    id: str = Field(default_factory=lambda: new_id("obs"))
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    #: ``level.outcome``, ``idea.skipped``, ``trade.closed``, ``health.incident``
    kind: str
    subject: str
    #: The categorical result: ``held``, ``broke``, ``taken``, ``skipped``.
    outcome: str = ""
    #: The numeric result, in whatever unit ``unit`` names. R for trades.
    value: float | None = None
    unit: str = ""
    source: str = ""
    trace_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _namespaced(cls, v: str) -> str:
        if "." not in v:
            raise ValueError(
                f"observation kind {v!r} must be namespaced (noun.verb), so the "
                f"miner can aggregate by family without a lookup table"
            )
        return v
