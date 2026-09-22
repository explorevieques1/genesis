# Spec: Genesis Markdown/20-Agents/Journal/Agent — Watchdog.md
"""Health: liveness, and the thing that matters more — freshness.

Agent — Watchdog names the failure this module exists for:

> **Freshness, not just liveness.** The most dangerous failure mode is a
> component that responds correctly while serving stale data.

So a :class:`Probe` has two independent verdicts. ``alive`` says the thing
answered. ``fresh`` says what it answered with is recent enough to act on. A
component can be alive and stale, and that combination is ``degraded`` -- never
``healthy``, which is the single most important line in this file.

The second thing this module gets right is **notification discipline**. An
alerting system you mute is worthless, the same principle Agent — Level Watcher
is built around. :class:`HealthReport` deduplicates: a component down for two
hours produces one notification, not one per 30-second cycle, and exactly one
more when it recovers.

No LLM anywhere. The component whose answer to *"is the system healthy"* must be
believed is the last one that should depend on a language model being up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Iterable, Literal, Sequence

__all__ = ["HealthReport", "Probe", "State", "Watch", "evaluate"]

State = Literal["healthy", "degraded", "down", "failed"]

#: Ordering, so ``overall`` is a max rather than a chain of ifs.
_SEVERITY: dict[str, int] = {"healthy": 0, "degraded": 1, "down": 2, "failed": 3}

#: Restarts before a component is declared ``failed`` and left alone. Daemon And
#: Cadence's supervision rule: five crashes in ten minutes stops the restarts,
#: because a restart loop is how one broken component becomes an outage.
RESTART_LIMIT = 5


@dataclass(frozen=True)
class Probe:
    """One component's health, as measured."""

    name: str
    kind: str  # agent | mcp | data | broker | llm | voice | memory | bus | resource
    alive: bool
    #: How old the newest data this component served is. ``None`` means the
    #: component serves no data, not that its data is fresh.
    data_age_sec: float | None = None
    max_age_sec: float | None = None
    latency_ms: float | None = None
    restarts: int = 0
    detail: str = ""
    #: True when this component sits on the path to an order. A failure here
    #: forces `confirm` mode; elsewhere it is a dashboard line.
    execution_path: bool = False

    @property
    def fresh(self) -> bool:
        """Whether the data is recent enough to act on.

        A component with no freshness requirement is trivially fresh. One with a
        requirement and no reading is **not** -- an unknown age is not a young
        age, and treating it as one is exactly how a stale feed passes a health
        check.
        """
        if self.max_age_sec is None:
            return True
        if self.data_age_sec is None:
            return False
        return self.data_age_sec <= self.max_age_sec

    @property
    def state(self) -> State:
        if not self.alive:
            return "failed" if self.restarts >= RESTART_LIMIT else "down"
        if not self.fresh:
            # Alive and stale. The dangerous configuration, and the whole reason
            # `fresh` is separate from `alive`.
            return "degraded"
        return "healthy"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state}
        if self.detail:
            out["reason"] = self.detail
        if self.latency_ms is not None:
            out["latency_ms"] = round(self.latency_ms, 1)
        if self.data_age_sec is not None:
            out["data_age_sec"] = round(self.data_age_sec, 1)
        if self.restarts:
            out["restarts"] = self.restarts
        return out


@dataclass(frozen=True)
class HealthReport:
    """Everything, at one moment, plus what is worth saying out loud."""

    as_of: datetime
    probes: tuple[Probe, ...]
    #: Issues that are new since the previous report. The only things spoken.
    new_issues: tuple[str, ...] = ()
    #: Components that were unhealthy and are not any more. Announced once.
    recovered: tuple[str, ...] = ()
    approval_mode_forced: str | None = None

    @property
    def overall(self) -> State:
        if not self.probes:
            return "healthy"
        return max((p.state for p in self.probes), key=lambda s: _SEVERITY[s])

    @property
    def unhealthy(self) -> tuple[Probe, ...]:
        return tuple(p for p in self.probes if p.state != "healthy")

    def to_dict(self) -> dict[str, Any]:
        grouped: dict[str, dict[str, Any]] = {}
        for probe in self.probes:
            grouped.setdefault(probe.kind, {})[probe.name] = probe.to_dict()
        return {
            "as_of": self.as_of.isoformat(),
            "overall": self.overall,
            **grouped,
            "approval_mode_forced": self.approval_mode_forced,
            "new_issues": list(self.new_issues),
            "recovered": list(self.recovered),
        }

    def spoken(self) -> str | None:
        """What the orchestrator may say aloud, if anything.

        Speaks only execution-path problems and approval-mode changes; everything
        else goes to the dashboard. ``None`` on a healthy cycle is the normal
        case and the reason this agent can run every 30 seconds without becoming
        the thing you mute.
        """
        if self.approval_mode_forced:
            return (
                f"{self.new_issues[0] if self.new_issues else 'A component failed'}. "
                f"I've forced {self.approval_mode_forced} mode."
            )
        speakable = [
            p for p in self.unhealthy
            if p.execution_path and p.name in {i.split(" ")[0] for i in self.new_issues}
        ]
        if speakable:
            probe = speakable[0]
            return f"{probe.name} is {probe.state}. {probe.detail}".strip()
        if self.recovered:
            return f"{self.recovered[0]} is back."
        return None


@dataclass
class Watch:
    """Runs probes on a cadence and remembers what it already reported.

    The memory is the point. Without it every cycle re-reports every ongoing
    problem, and the operator learns to ignore the channel -- which is the
    failure mode that makes a health system worse than none.
    """

    probes: list[Callable[[], Probe]] = field(default_factory=list)
    #: name -> state, as of the last report. The deduplication key.
    _seen: dict[str, State] = field(default_factory=dict, repr=False)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def register(self, probe: Callable[[], Probe]) -> None:
        self.probes.append(probe)

    def check(self) -> HealthReport:
        results: list[Probe] = []
        for run in self.probes:
            try:
                results.append(run())
            except Exception as exc:  # noqa: BLE001 - a probe that raises is a failure
                results.append(
                    Probe(
                        name=getattr(run, "__name__", "probe"),
                        kind="agent",
                        alive=False,
                        detail=f"probe raised: {exc}",
                    )
                )
        return self._report(results)

    def _report(self, probes: Sequence[Probe]) -> HealthReport:
        new_issues: list[str] = []
        recovered: list[str] = []
        for probe in probes:
            previous = self._seen.get(probe.name, "healthy")
            if probe.state != "healthy" and probe.state != previous:
                new_issues.append(f"{probe.name} {probe.state}")
            elif probe.state == "healthy" and previous != "healthy":
                recovered.append(probe.name)
            self._seen[probe.name] = probe.state

        # An execution-path component that has exhausted its restarts withdraws
        # autonomy. Not a suggestion: if the code that reaches the broker might
        # be broken, every order gets a human in front of it.
        forced = None
        if any(p.execution_path and p.state == "failed" for p in probes):
            forced = "confirm"

        return HealthReport(
            as_of=self.clock(),
            probes=tuple(probes),
            new_issues=tuple(new_issues),
            recovered=tuple(recovered),
            approval_mode_forced=forced,
        )


def evaluate(probes: Iterable[Probe]) -> State:
    """The worst state present. A convenience for callers holding raw probes."""
    states = [p.state for p in probes]
    return max(states, key=lambda s: _SEVERITY[s]) if states else "healthy"
