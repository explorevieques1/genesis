# Spec: Genesis Markdown/20-Agents/Journal/Agent — Insight Miner.md
"""Behavioural detectors. Deterministic, quantified, and allowed to find nothing.

Agent — Insight Miner's job is *"the patterns in your behaviour that you cannot
see yourself"*, and the note is precise about what makes such a finding useful:

> "You sometimes oversize" is useless. "Position size increases 62% after two
> consecutive losses, and those trades average −0.61R over 34 observations" is
> actionable.

So every detector here returns a number, a comparison, and an ``n`` -- or it
returns nothing. None of them is a model. A language model reading a trade
history will find patterns in it whether or not they are there, which is the
same failure the charting family guards against with its rules engine, and the
same fix applies: the arithmetic is deterministic and the model's job is to
explain it, never to discover it.

**Nothing here writes a lesson.** A detector emits a :class:`Finding`; the agent
decides whether the evidence clears the threshold for a lesson, or whether it
becomes a hypothesis that accrues until it does. That separation is what lets
the thresholds be enforced in exactly one place.

**Comparative, not absolute.** *"Trades after two losses average −0.61R"* means
nothing without *"against an overall expectancy of +0.23R"*. Every finding here
carries its baseline, because a detector that reports a slice without its
comparison is a detector that will eventually flag a normal number.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Iterable, Sequence

from genesis.journal.schema import Evidence, JournalEntry, Observation
from genesis.metrics import summarize

__all__ = ["Finding", "detect_all", "DETECTORS"]

#: Minimum rows a detector needs before it will speak at all. Well below the
#: lesson threshold on purpose: a finding with eight observations is worth
#: *recording as a hypothesis* so it can accumulate, and suppressing it entirely
#: would mean the system never notices anything until it already has twenty.
MIN_ROWS = 5

#: How much worse a slice must be than the baseline to be worth reporting, in R.
#: Below this it is noise dressed as a finding.
MATERIAL_R = 0.25


@dataclass(frozen=True)
class Finding:
    """One detected pattern, with everything needed to judge it.

    ``key`` is stable across nights. That is what makes accumulation possible:
    the same pattern found again updates one hypothesis rather than creating a
    second, and after enough nights it graduates.
    """

    key: str
    title: str
    finding: str
    evidence: Evidence
    applies_when: tuple[str, ...] = ()
    recommended_action: str = ""
    #: The measurement, so a reader can check the claim without re-running it.
    measures: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "finding": self.finding,
            "observations": self.evidence.observations,
            "confidence": self.evidence.confidence,
            "applies_when": list(self.applies_when),
            "recommended_action": self.recommended_action,
            "measures": self.measures,
        }


# --------------------------------------------------------------------------
# Detectors over the trade journal
# --------------------------------------------------------------------------


def sequence_effect(entries: Sequence[JournalEntry], **_: Any) -> Finding | None:
    """*"You oversize after two losses. Those trades average −0.6R."*

    Two claims in one finding, and both are needed: the size change is the
    behaviour, and the outcome is why it matters. Reporting either alone leaves
    the obvious rebuttal open -- "so what if I size up, it works".
    """
    graded = [e for e in entries if e.r_multiple is not None]
    if len(graded) < MIN_ROWS + 2:
        return None

    after_losses: list[JournalEntry] = []
    baseline: list[JournalEntry] = []
    for i, entry in enumerate(graded):
        prior = graded[max(i - 2, 0) : i]
        two_losses = len(prior) == 2 and all(
            (p.r_multiple or 0) <= 0 for p in prior
        )
        (after_losses if two_losses else baseline).append(entry)

    if len(after_losses) < MIN_ROWS or not baseline:
        return None

    after = summarize([e.r_multiple for e in after_losses])
    rest = summarize([e.r_multiple for e in baseline])
    if after.expectancy_r is None or rest.expectancy_r is None:
        return None
    gap = rest.expectancy_r - after.expectancy_r
    if gap < MATERIAL_R:
        return None

    size_shift = _size_shift(after_losses, baseline)
    size_clause = (
        f"Position size is {size_shift:+.0%} on those trades. "
        if size_shift is not None and abs(size_shift) >= 0.15
        else ""
    )
    return Finding(
        key="sequence.after-two-losses",
        title="Performance after consecutive losses",
        finding=(
            f"{size_clause}Trades taken after two consecutive losses average "
            f"{after.expectancy_r:+.2f}R against {rest.expectancy_r:+.2f}R "
            f"otherwise."
        ),
        evidence=Evidence(
            observations=after.n,
            ids=tuple(e.id for e in after_losses),
            confidence=_confidence(after.n, gap),
            period_from=after_losses[0].exit_ts.date().isoformat(),
            period_to=after_losses[-1].exit_ts.date().isoformat(),
        ),
        applies_when=("consecutive_losses >= 2",),
        recommended_action=(
            "Cap size at the normal risk percentage after two consecutive "
            "losses, or take a mandatory cooldown."
        ),
        measures={
            "expectancy_after": after.expectancy_r,
            "expectancy_baseline": rest.expectancy_r,
            "size_shift": size_shift,
        },
    )


def revenge_trading(
    entries: Sequence[JournalEntry], *, window_min: int = 15, **_: Any
) -> Finding | None:
    """Trades entered soon after a loss closed.

    The window is a parameter because "soon" is instrument- and style-dependent;
    fifteen minutes is the note's own example and a sensible default for a day
    trader. What is *not* a parameter is the comparison: this only reports when
    those trades are materially worse than the rest.
    """
    graded = sorted(
        (e for e in entries if e.r_multiple is not None), key=lambda e: e.entry_ts
    )
    if len(graded) < MIN_ROWS + 1:
        return None

    window = timedelta(minutes=window_min)
    quick: list[JournalEntry] = []
    rest: list[JournalEntry] = []
    for i, entry in enumerate(graded):
        prior = graded[i - 1] if i else None
        soon_after_loss = (
            prior is not None
            and (prior.r_multiple or 0) <= 0
            and timedelta() <= entry.entry_ts - prior.exit_ts <= window
        )
        (quick if soon_after_loss else rest).append(entry)

    if len(quick) < MIN_ROWS or not rest:
        return None
    fast = summarize([e.r_multiple for e in quick])
    slow = summarize([e.r_multiple for e in rest])
    if fast.expectancy_r is None or slow.expectancy_r is None:
        return None
    gap = slow.expectancy_r - fast.expectancy_r
    if gap < MATERIAL_R:
        return None

    return Finding(
        key=f"sequence.revenge-{window_min}m",
        title="Re-entering immediately after a loss",
        finding=(
            f"Trades entered within {window_min} minutes of a losing exit average "
            f"{fast.expectancy_r:+.2f}R against {slow.expectancy_r:+.2f}R otherwise."
        ),
        evidence=Evidence(
            observations=fast.n,
            ids=tuple(e.id for e in quick),
            confidence=_confidence(fast.n, gap),
            period_from=quick[0].exit_ts.date().isoformat(),
            period_to=quick[-1].exit_ts.date().isoformat(),
        ),
        applies_when=(f"minutes_since_loss <= {window_min}",),
        recommended_action=f"Impose a {window_min}-minute cooldown after a loss.",
        measures={"expectancy_fast": fast.expectancy_r, "expectancy_rest": slow.expectancy_r},
    )


def stop_migration(entries: Sequence[JournalEntry], **_: Any) -> Finding | None:
    """*"You moved your stop against yourself on 3 of the last 5 losers."*

    Trade Journal Schema calls ``stop_moved`` the single most predictive field
    in the whole schema, and the reason it is computed rather than asked is that
    self-reporting on this particular behaviour is unreliable in a way that is
    entirely human and entirely predictable.
    """
    graded = [e for e in entries if e.r_multiple is not None]
    if len(graded) < MIN_ROWS:
        return None
    moved = [e for e in graded if e.plan_adherence.stop_moved]
    if len(moved) < 3:
        return None

    held = [e for e in graded if not e.plan_adherence.stop_moved]
    moved_sample = summarize([e.r_multiple for e in moved])
    held_sample = summarize([e.r_multiple for e in held]) if held else None
    losers = [e for e in graded if (e.r_multiple or 0) <= 0]
    moved_losers = [e for e in losers if e.plan_adherence.stop_moved]

    comparison = ""
    if held_sample and held_sample.expectancy_r is not None and moved_sample.expectancy_r is not None:
        comparison = (
            f" Those trades average {moved_sample.expectancy_r:+.2f}R against "
            f"{held_sample.expectancy_r:+.2f}R when the stop was left alone."
        )

    return Finding(
        key="discipline.stop-migration",
        title="Moving the stop against the position",
        finding=(
            f"The stop was moved against the position on {len(moved)} of "
            f"{len(graded)} trades, including {len(moved_losers)} of "
            f"{len(losers)} losers.{comparison}"
        ),
        evidence=Evidence(
            observations=len(moved),
            ids=tuple(e.id for e in moved),
            confidence=_confidence(len(moved), 0.5),
            period_from=moved[0].exit_ts.date().isoformat(),
            period_to=moved[-1].exit_ts.date().isoformat(),
        ),
        applies_when=("stop_moved == true",),
        recommended_action=(
            "Treat the stop as fixed once placed. If it needs moving, that is a "
            "signal to close, not to widen."
        ),
        measures={
            "moved": len(moved),
            "of": len(graded),
            "moved_losers": len(moved_losers),
        },
    )


def cutting_winners(entries: Sequence[JournalEntry], **_: Any) -> Finding | None:
    """Exits well short of the planned target, on trades that were working.

    Measured against ``mfe_r`` -- how far the trade actually went in your favour
    -- rather than against the target. A target that was never approached says
    nothing about your exits; a trade that reached 1.9R and was closed at 1.0R
    says a great deal.
    """
    usable = [
        e for e in entries
        if e.r_multiple is not None and e.mfe_r is not None and e.mfe_r > 0
    ]
    if len(usable) < MIN_ROWS:
        return None

    winners = [e for e in usable if (e.r_multiple or 0) > 0]
    if len(winners) < MIN_ROWS:
        return None

    captured = [
        (e.r_multiple or 0) / e.mfe_r for e in winners if e.mfe_r and e.mfe_r > 0
    ]
    if not captured:
        return None
    average_capture = sum(captured) / len(captured)
    if average_capture > 0.65:
        return None  # capturing most of the move; nothing to report

    left = [e for e in winners if e.mfe_r and (e.r_multiple or 0) / e.mfe_r < 0.6]
    return Finding(
        key="discipline.cutting-winners",
        title="Exiting winners early",
        finding=(
            f"Winning trades capture {average_capture:.0%} of the move that went "
            f"in their favour; {len(left)} of {len(winners)} closed below 60% of "
            f"their best point."
        ),
        evidence=Evidence(
            observations=len(winners),
            ids=tuple(e.id for e in winners),
            confidence=_confidence(len(winners), 0.65 - average_capture),
            period_from=winners[0].exit_ts.date().isoformat(),
            period_to=winners[-1].exit_ts.date().isoformat(),
        ),
        applies_when=("position_open and unrealised_r > 0",),
        recommended_action=(
            "Take partials at a planned level rather than closing the whole "
            "position on the first pullback."
        ),
        measures={"average_capture": average_capture, "early_exits": len(left)},
    )


def time_of_day(entries: Sequence[JournalEntry], **_: Any) -> Finding | None:
    """*"You lose money after 14:30. Consistently."*"""
    return _worst_slice(
        entries,
        key=lambda e: e.session_segment,
        dimension="session",
        key_name="session",
        title="Performance by session segment",
        applies_when_template="session_segment == {value!r}",
        action="Stop taking new entries in that window, or halve size there.",
    )


def regime_blindness(entries: Sequence[JournalEntry], **_: Any) -> Finding | None:
    """*"You trade the ORB setup in ranging tape. It only works trending."*"""
    graded = [
        e for e in entries
        if e.r_multiple is not None and e.setup and e.regime
    ]
    if len(graded) < MIN_ROWS * 2:
        return None

    by_pair: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_setup: dict[str, list[float]] = defaultdict(list)
    for entry in graded:
        by_pair[(entry.setup or "", entry.regime or "")].append(entry.r_multiple or 0.0)
        by_setup[entry.setup or ""].append(entry.r_multiple or 0.0)

    worst: tuple[float, tuple[str, str], int] | None = None
    for (setup, regime), values in by_pair.items():
        if len(values) < MIN_ROWS:
            continue
        others = [
            v for (s, r), vs in by_pair.items() if s == setup and r != regime for v in vs
        ]
        if not others:
            continue
        gap = (sum(others) / len(others)) - (sum(values) / len(values))
        if gap >= MATERIAL_R and (worst is None or gap > worst[0]):
            worst = (gap, (setup, regime), len(values))

    if worst is None:
        return None
    gap, (setup, regime), n = worst
    here = summarize(by_pair[(setup, regime)])
    elsewhere = summarize(
        [v for (s, r), vs in by_pair.items() if s == setup and r != regime for v in vs]
    )
    return Finding(
        key=f"regime.{setup}-in-{regime}",
        title=f"{setup} in {regime} tape",
        finding=(
            f"The {setup} setup averages {here.expectancy_r:+.2f}R in {regime} tape "
            f"against {elsewhere.expectancy_r:+.2f}R in other regimes."
        ),
        evidence=Evidence(
            observations=n,
            confidence=_confidence(n, gap),
            ids=tuple(
                e.id for e in graded if e.setup == setup and e.regime == regime
            ),
        ),
        applies_when=(f"setup == {setup!r} and regime == {regime!r}",),
        recommended_action=f"Skip {setup} when the regime is {regime}.",
        measures={"expectancy_here": here.expectancy_r, "expectancy_elsewhere": elsewhere.expectancy_r},
    )


def size_effect(entries: Sequence[JournalEntry], **_: Any) -> Finding | None:
    """*"Do bigger positions do worse?"* They usually do.

    Agent — Performance Analyst calls this one of the two highest-value analyses
    in the system, because it catches overconfidence while it is happening
    rather than in the monthly review.
    """
    graded = [e for e in entries if e.r_multiple is not None and e.qty]
    if len(graded) < MIN_ROWS * 2:
        return None
    average_size = sum(e.qty for e in graded) / len(graded)
    if average_size <= 0:
        return None

    big = [e for e in graded if e.qty >= average_size * 1.5]
    small = [e for e in graded if e.qty < average_size * 1.5]
    if len(big) < MIN_ROWS or not small:
        return None
    large = summarize([e.r_multiple for e in big])
    normal = summarize([e.r_multiple for e in small])
    if large.expectancy_r is None or normal.expectancy_r is None:
        return None
    gap = normal.expectancy_r - large.expectancy_r
    if gap < MATERIAL_R:
        return None

    return Finding(
        key="sizing.large-positions",
        title="Larger positions perform worse",
        finding=(
            f"Trades above 1.5x average size average {large.expectancy_r:+.2f}R "
            f"against {normal.expectancy_r:+.2f}R below it."
        ),
        evidence=Evidence(
            observations=large.n,
            ids=tuple(e.id for e in big),
            confidence=_confidence(large.n, gap),
        ),
        applies_when=("size > 1.5 * average_size",),
        recommended_action="Cap size at the risk envelope's normal percentage.",
        measures={"expectancy_large": large.expectancy_r, "expectancy_normal": normal.expectancy_r},
    )


def plan_adherence_effect(entries: Sequence[JournalEntry], **_: Any) -> Finding | None:
    """*"Plan-followed trades +0.51R; deviated trades −0.22R."*"""
    graded = [e for e in entries if e.r_multiple is not None]
    followed = [e for e in graded if e.plan_adherence.followed]
    deviated = [e for e in graded if not e.plan_adherence.followed]
    if len(followed) < MIN_ROWS or len(deviated) < MIN_ROWS:
        return None
    kept = summarize([e.r_multiple for e in followed])
    broke = summarize([e.r_multiple for e in deviated])
    if kept.expectancy_r is None or broke.expectancy_r is None:
        return None
    gap = kept.expectancy_r - broke.expectancy_r
    if gap < MATERIAL_R:
        return None
    return Finding(
        key="discipline.plan-adherence",
        title="Following the plan is worth more than the plan",
        finding=(
            f"Trades that followed the plan average {kept.expectancy_r:+.2f}R; "
            f"trades that deviated average {broke.expectancy_r:+.2f}R."
        ),
        evidence=Evidence(
            observations=len(deviated),
            ids=tuple(e.id for e in deviated),
            confidence=_confidence(len(deviated), gap),
        ),
        applies_when=("plan_followed == false",),
        recommended_action="Deviating from the plan is the costliest habit in the data.",
        measures={"expectancy_followed": kept.expectancy_r, "expectancy_deviated": broke.expectancy_r},
    )


# --------------------------------------------------------------------------
# Detectors over observations — these work before the first trade exists
# --------------------------------------------------------------------------


def level_quality(
    entries: Sequence[JournalEntry], *, observations: Sequence[Observation] = (), **_: Any
) -> Finding | None:
    """*"Your anchored-VWAP levels hold 71%. Your trendlines hold 38%."*

    Charting Family calls this the system's most distinctive edge, and it is the
    one finding available **today**: the charting family records a level outcome
    every time a spec is scored, and none of that needs a broker.

    Reported only when two level types differ materially, because "your levels
    hold 55% of the time" is a fact about levels in general and changes nothing.
    """
    outcomes = [o for o in observations if o.kind.startswith("level.")]
    if len(outcomes) < MIN_ROWS * 2:
        return None

    by_source: dict[str, list[bool]] = defaultdict(list)
    for observation in outcomes:
        if observation.outcome in ("held", "reclaimed", "broke"):
            by_source[observation.source or "unknown"].append(
                observation.outcome in ("held", "reclaimed")
            )

    scored = {
        source: (sum(held) / len(held), len(held))
        for source, held in by_source.items()
        if len(held) >= MIN_ROWS
    }
    if len(scored) < 2:
        return None

    best = max(scored.items(), key=lambda kv: kv[1][0])
    worst = min(scored.items(), key=lambda kv: kv[1][0])
    if best[1][0] - worst[1][0] < 0.2:
        return None

    total = sum(n for _, n in scored.values())
    return Finding(
        key="charting.level-quality",
        title="Not all level types hold equally",
        finding=(
            f"{best[0]} levels hold {best[1][0]:.0%} of the time over "
            f"{best[1][1]} tests; {worst[0]} levels hold {worst[1][0]:.0%} over "
            f"{worst[1][1]}."
        ),
        evidence=Evidence(
            observations=total,
            confidence=_confidence(total, best[1][0] - worst[1][0]),
        ),
        applies_when=(f"level_source == {worst[0]!r}",),
        recommended_action=(
            f"Weight {best[0]} levels above {worst[0]} levels when siting entries "
            f"and invalidations."
        ),
        measures={source: {"rate": rate, "n": n} for source, (rate, n) in scored.items()},
    )


def selection_bias(
    entries: Sequence[JournalEntry], *, observations: Sequence[Observation] = (), **_: Any
) -> Finding | None:
    """*"You skipped 4 of your 6 highest-confidence ideas. They averaged +0.9R."*

    Needs idea outcomes, which arrive as observations rather than journal rows --
    a skipped idea has no trade, which is exactly the point of the finding and
    exactly why it cannot be computed from the journal alone.
    """
    ideas = [o for o in observations if o.kind.startswith("idea.")]
    taken = [o for o in ideas if o.outcome == "taken" and o.value is not None]
    skipped = [o for o in ideas if o.outcome == "skipped" and o.value is not None]
    if len(taken) < MIN_ROWS or len(skipped) < MIN_ROWS:
        return None

    took = summarize([o.value for o in taken])
    passed = summarize([o.value for o in skipped])
    if took.expectancy_r is None or passed.expectancy_r is None:
        return None
    gap = passed.expectancy_r - took.expectancy_r
    if gap < MATERIAL_R:
        return None

    return Finding(
        key="selection.skipped-ideas",
        title="The ideas you skip outperform the ones you take",
        finding=(
            f"Ideas you skipped would have averaged {passed.expectancy_r:+.2f}R "
            f"over {passed.n}; the ones you took averaged {took.expectancy_r:+.2f}R "
            f"over {took.n}."
        ),
        evidence=Evidence(
            observations=passed.n + took.n,
            confidence=_confidence(passed.n + took.n, gap),
        ),
        applies_when=("idea_confidence >= 0.7 and not taken",),
        recommended_action=(
            "Take the ranked idea or write down why not — the skips are costing "
            "more than the entries."
        ),
        measures={"skipped_expectancy": passed.expectancy_r, "taken_expectancy": took.expectancy_r},
    )


#: The detector roster. Order is the order findings are reported in, which puts
#: discipline before statistics -- a habit you can change tonight is more
#: actionable than a slice you can only observe.
DETECTORS: tuple[Callable[..., Finding | None], ...] = (
    stop_migration,
    sequence_effect,
    revenge_trading,
    plan_adherence_effect,
    cutting_winners,
    size_effect,
    time_of_day,
    regime_blindness,
    level_quality,
    selection_bias,
)


def detect_all(
    entries: Sequence[JournalEntry],
    *,
    observations: Sequence[Observation] = (),
    detectors: Sequence[Callable[..., Finding | None]] = DETECTORS,
) -> list[Finding]:
    """Run every detector. An empty list is a normal and frequent result.

    A detector that raises is skipped rather than allowed to fail the whole
    pass: nine working findings and one broken detector is a better night than
    no findings at all, and the broken one shows up as a missing key rather than
    as an agent that stopped learning.
    """
    found: list[Finding] = []
    for detector in detectors:
        try:
            finding = detector(entries, observations=observations)
        except Exception:  # noqa: BLE001 - one bad detector must not end the pass
            continue
        if finding is not None:
            found.append(finding)
    return found


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _worst_slice(
    entries: Sequence[JournalEntry],
    *,
    key: Callable[[JournalEntry], str | None],
    dimension: str,
    key_name: str,
    title: str,
    applies_when_template: str,
    action: str,
) -> Finding | None:
    """The worst bucket of a dimension, but only if it is worse than the rest.

    The comparison is against *the other buckets*, not against zero. A slice
    with negative expectancy in a losing month is not a finding about that
    slice; it is a finding about the month.
    """
    graded = [e for e in entries if e.r_multiple is not None and key(e)]
    if len(graded) < MIN_ROWS * 2:
        return None
    buckets: dict[str, list[JournalEntry]] = defaultdict(list)
    for entry in graded:
        buckets[str(key(entry))].append(entry)

    eligible = {name: rows for name, rows in buckets.items() if len(rows) >= MIN_ROWS}
    if len(eligible) < 2:
        return None

    scored = {
        name: summarize([e.r_multiple for e in rows]) for name, rows in eligible.items()
    }
    worst_name = min(
        scored, key=lambda n: scored[n].expectancy_r if scored[n].expectancy_r is not None else 0.0
    )
    worst = scored[worst_name]
    others = [
        r for name, rows in eligible.items() if name != worst_name
        for r in (e.r_multiple for e in rows) if r is not None
    ]
    rest = summarize(others)
    if worst.expectancy_r is None or rest.expectancy_r is None:
        return None
    gap = rest.expectancy_r - worst.expectancy_r
    if gap < MATERIAL_R:
        return None

    return Finding(
        key=f"{dimension}.{worst_name}",
        title=title,
        finding=(
            f"The {worst_name} {key_name} averages {worst.expectancy_r:+.2f}R "
            f"against {rest.expectancy_r:+.2f}R elsewhere."
        ),
        evidence=Evidence(
            observations=worst.n,
            ids=tuple(e.id for e in eligible[worst_name]),
            confidence=_confidence(worst.n, gap),
        ),
        applies_when=(applies_when_template.format(value=worst_name),),
        recommended_action=action,
        measures={"expectancy_worst": worst.expectancy_r, "expectancy_rest": rest.expectancy_r},
    )


def _size_shift(subset: Sequence[JournalEntry], baseline: Sequence[JournalEntry]) -> float | None:
    """Relative size difference between two groups, or ``None`` if unmeasurable."""
    if not subset or not baseline:
        return None
    a = sum(e.qty for e in subset) / len(subset)
    b = sum(e.qty for e in baseline) / len(baseline)
    if b <= 0:
        return None
    return (a / b) - 1.0


def _confidence(n: int, effect: float) -> float:
    """How much to bet on this, 0..1. Deliberately crude and deliberately capped.

    Not a p-value. Agent — Insight Miner is mining a small dataset many ways, so
    a real significance test would be misapplied -- the multiple-comparisons
    problem is not fixable by computing the statistic more carefully. What is
    honest is a monotonic function of sample size and effect size, capped below
    certainty, presented as *"how much I would bet on this"*.
    """
    size_term = min(n / 40.0, 1.0)
    effect_term = min(abs(effect) / 0.8, 1.0)
    return round(min(0.15 + 0.7 * size_term * effect_term, 0.9), 2)
