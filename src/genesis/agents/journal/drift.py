# Spec: Genesis Markdown/20-Agents/Journal/Agent — Backtest Vs Live Drift.md
"""Agent — Backtest Vs Live Drift. Does reality agree with the backtest?

When live diverges from tested expectation there are exactly two explanations --
**the regime changed** or **the implementation has a bug** -- and they have
opposite responses. Distinguishing them is the entire product; *"it's not
working"* is not an output.

The statistics live in :mod:`genesis.journal.drift`, deterministically, and the
two rules that keep this agent from crying wolf are enforced there:

* **Thirty live trades minimum** before any divergence claim.
* **Compare against the distribution**, not the point estimate. A strategy 20%
  below its backtest expectancy over 40 trades is probably fine; one whose losses
  are systematically larger over the same 40 is not, and only a z-score can tell
  them apart.

**Escalation withdraws autonomy on a suspected bug.** Deliberate, and the note
says why: if the code might be wrong, autonomy goes until it is proven right.
This agent *proposes* the demotion and publishes it; it does not reach into the
approval mode itself, because that is the risk engine's to change and a journal
agent must not have a hand on it.

Today it has no backtests to read -- Phase 5 has not happened -- so the honest
behaviour is to say so per strategy rather than to fabricate an expectation.
That is not a stub: `expectations` is an injected mapping, and the agent works
the moment anything fills it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from genesis.agents.base import Agent, AgentDeclaration, TaskFailure, TaskResult
from genesis.journal.drift import MIN_LIVE_TRADES, DriftReport, Expectation, compare
from genesis.journal.schema import Observation
from genesis.journal.store import JournalStore
from genesis.metrics import summarize
from genesis.observability import Console

__all__ = ["DECLARATION", "DriftAgent"]

DECLARATION = AgentDeclaration(
    id="drift",
    name="Backtest Vs Live Drift",
    family="journal",
    cadence=[
        {"type": "market-closed", "interval_sec": 86400},
        {"type": "cron", "at": "22:00"},
    ],
    tools=["genesis-backtest.run"],
    memory={
        "read": [
            "shared", "ledger", "backtest-runner", "optimizer",
            "regime-correlation", "execution-quality", "trade-journal",
        ],
        "write": ["drift", "shared"],
    },
    model_tier="large",
    vision=False,
    timeout_sec=180,
    max_concurrent=1,
)


class DriftAgent(Agent):
    """One report per live strategy, or an honest silence."""

    def __init__(
        self,
        store: JournalStore,
        *,
        expectations: Mapping[str, Expectation] | None = None,
        console: Console | None = None,
    ) -> None:
        super().__init__(DECLARATION)
        self.store = store
        self.expectations: dict[str, Expectation] = dict(expectations or {})
        self.console = console or Console(enabled=False)

    def execute(self, task: Any) -> TaskResult | TaskFailure:
        args = dict(getattr(task, "args", {}) or {})
        reports = self.check(days=int(args.get("days", 90)))

        for report in reports:
            self.store.record(
                Observation(
                    kind="strategy.drift",
                    subject=report.strategy,
                    outcome=report.likely_cause if report.significant else "variance",
                    value=report.z,
                    unit="z",
                    source="drift",
                    detail={
                        "severity": report.severity,
                        "live_trades": report.live.n,
                        "primary_gap": report.primary_gap,
                    },
                )
            )

        critical = [r for r in reports if r.severity == "critical"]
        return TaskResult(
            task_id=getattr(task, "id", "<none>"),
            agent=self.id,
            data={
                "reports": [r.to_dict() for r in reports],
                "strategies": len(reports),
                "critical": [r.strategy for r in critical],
                # A proposal, not an action. Changing an approval mode belongs
                # to the risk engine; a journal agent recommending one is the
                # correct amount of authority for it to have.
                "demotion_proposed": [
                    {"strategy": r.strategy, "to": "confirm", "why": r.reasoning}
                    for r in critical
                ],
                "unmeasurable": self._unmeasurable(days=int(args.get("days", 90))),
            },
            wrote=({"layer": "memory", "namespace": "drift"},),
            spoken_summary=_spoken(reports),
            degraded=bool(self._unmeasurable(days=int(args.get("days", 90)))),
            cost={"tool_calls": 0},
        )

    # -- the work ----------------------------------------------------------

    def check(self, *, days: int = 90) -> list[DriftReport]:
        since = datetime.now(UTC) - timedelta(days=days)
        entries = self.store.entries(since=since)

        by_strategy: dict[str, list[Any]] = {}
        for entry in entries:
            if entry.strategy:
                by_strategy.setdefault(entry.strategy, []).append(entry)

        reports: list[DriftReport] = []
        for strategy, rows in sorted(by_strategy.items()):
            expected = self.expectations.get(strategy)
            if expected is None:
                # No backtest to compare against. Silence is the honest answer;
                # inventing an expectation would make every strategy look either
                # fine or broken according to a number nobody produced.
                continue
            live = summarize(
                [e.r_multiple for e in rows], pnl=[e.pnl_net for e in rows]
            )
            weeks = max(days / 7.0, 1.0)
            reports.append(
                compare(
                    strategy,
                    live,
                    expected,
                    live_regime=_dominant(rows, "regime"),
                    live_slippage_bps=_average(rows, "slippage_bps"),
                    live_trades_per_week=live.n / weeks,
                )
            )
        return reports

    def _unmeasurable(self, *, days: int) -> list[str]:
        """Live strategies with no backtest expectation on file.

        Reported rather than skipped quietly. A strategy trading live with
        nothing to compare it against is itself a finding, and it is exactly the
        gap that Paper To Live Promotion is supposed to close.
        """
        since = datetime.now(UTC) - timedelta(days=days)
        live = {e.strategy for e in self.store.entries(since=since) if e.strategy}
        return sorted(live - set(self.expectations))


def _spoken(reports: list[DriftReport]) -> str | None:
    """Speak only what needs saying: the worst real divergence, or nothing."""
    significant = [r for r in reports if r.significant]
    if not significant:
        return None
    worst = min(significant, key=lambda r: r.z or 0.0)
    return worst.spoken()


def _dominant(rows: list[Any], field: str) -> str | None:
    values = [getattr(row, field, None) for row in rows]
    present = [v for v in values if v]
    if not present:
        return None
    return max(set(present), key=present.count)


def _average(rows: list[Any], field: str) -> float | None:
    values = [
        getattr(row, field, None) for row in rows if getattr(row, field, None) is not None
    ]
    return (sum(values) / len(values)) if values else None
