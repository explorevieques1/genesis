# Spec: Genesis Markdown/20-Agents/Journal/Agent — Watchdog.md
"""Agent — Watchdog. Is everything actually running?

> In an always-on system, silent failure is the real danger. An agent that died
> three hours ago and nobody noticed is worse than one that crashes loudly.

Three things this agent gets right, and each is a rule the note states:

**Freshness, not just liveness.** A component that responds correctly while
serving stale data is the most dangerous failure mode there is, so every data
probe carries an age assertion and alive-but-stale resolves to ``degraded`` --
never ``healthy``.

**A failed execution-path component withdraws autonomy.** If the code that
reaches a broker might be broken, every order gets a human in front of it. The
forcing happens in :mod:`genesis.journal.health`, deterministically, and this
agent reports it rather than deciding it.

**Notification discipline.** One notification per issue, not one per cycle, and
exactly one more on recovery. An alerting system you mute is worthless -- the
same principle Agent — Level Watcher is built on, and the reason this agent can
run every thirty seconds.

``tier: small`` in the note, and it uses no model at all in practice: every
verdict here is a comparison. The component whose answer to *"is the system
healthy"* must be believed is the last one that should depend on a language
model being up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable, Sequence

from genesis.agents.base import Agent, AgentDeclaration, TaskFailure, TaskResult
from genesis.journal.health import Probe, Watch
from genesis.journal.schema import Observation
from genesis.journal.store import JournalStore
from genesis.observability import Console

__all__ = ["DECLARATION", "WatchdogAgent", "probes_for"]

DECLARATION = AgentDeclaration(
    id="watchdog",
    name="Watchdog",
    family="journal",
    cadence=[
        {"type": "market-open", "interval_sec": 30},
        {"type": "market-closed", "interval_sec": 120},
        {"type": "event", "on": ["agent.down", "agent.degraded"]},
    ],
    tools=["time.*", "git.*", "fs.list", "fs.stat"],
    memory={"read": ["shared"], "write": ["watchdog", "shared"]},
    model_tier="none",
    vision=False,
    timeout_sec=30,
    max_concurrent=1,
)


class WatchdogAgent(Agent):
    """Probes everything, deduplicates, and records every incident."""

    def __init__(
        self,
        *,
        store: JournalStore | None = None,
        supervisor: Any = None,
        gateway: Any = None,
        bus: Any = None,
        extra_probes: Sequence[Callable[[], Probe]] = (),
        console: Console | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(DECLARATION)
        self.store = store
        self.console = console or Console(enabled=False)
        self.watch = Watch(clock=clock or (lambda: datetime.now(UTC)))
        for probe in probes_for(supervisor=supervisor, gateway=gateway, bus=bus):
            self.watch.register(probe)
        for probe in extra_probes:
            self.watch.register(probe)

    def execute(self, task: Any) -> TaskResult | TaskFailure:
        report = self.watch.check()

        # Every incident becomes an observation. Health history is exactly the
        # kind of thing nobody records and everybody later wishes they had --
        # "the news feed has gone down eleven times this month" is a fact you
        # can only have if something wrote it down each time.
        if self.store is not None:
            for probe in report.unhealthy:
                self.store.record(
                    Observation(
                        kind="health.incident",
                        subject=f"{probe.kind}:{probe.name}",
                        outcome=probe.state,
                        source="watchdog",
                        detail={
                            "reason": probe.detail,
                            "restarts": probe.restarts,
                            "execution_path": probe.execution_path,
                        },
                    )
                )

        return TaskResult(
            task_id=getattr(task, "id", "<none>"),
            agent=self.id,
            data=report.to_dict(),
            wrote=({"layer": "memory", "namespace": "shared", "record": "health"},),
            spoken_summary=report.spoken(),
            degraded=report.overall != "healthy",
            cost={"tool_calls": len(report.probes)},
        )


def probes_for(
    *, supervisor: Any = None, gateway: Any = None, bus: Any = None
) -> list[Callable[[], Probe]]:
    """Build probes for whatever this install actually has.

    Absent subsystems contribute no probes rather than a probe that reports
    ``down``. A component that does not exist is not unhealthy, and reporting it
    as such would make the overall state permanently degraded on every install
    that has not reached Phase 7 -- which is the fastest way to teach someone to
    ignore this agent.
    """
    probes: list[Callable[[], Probe]] = []

    if supervisor is not None:
        probes.append(lambda: _supervisor_probe(supervisor))
    if gateway is not None:
        probes.append(lambda: _gateway_probe(gateway))
    if bus is not None:
        probes.append(lambda: _bus_probe(bus))
    return probes


def _supervisor_probe(supervisor: Any) -> Probe:
    """Every supervised agent, as one probe. Down if any is down or given up."""
    try:
        report = supervisor.health_report()
    except Exception as exc:  # noqa: BLE001
        return Probe(name="fleet", kind="agent", alive=False, detail=str(exc))
    if not report:
        return Probe(name="fleet", kind="agent", alive=True, detail="no agents registered")

    unhealthy = sorted(a for a, h in report.items() if not h["alive"] or h["given_up"])
    return Probe(
        name="fleet",
        kind="agent",
        alive=not unhealthy,
        detail=(
            f"{len(unhealthy)} of {len(report)} agents not alive: " + ", ".join(unhealthy)
            if unhealthy
            else f"{len(report)} agents alive"
        ),
    )


def _gateway_probe(gateway: Any) -> Probe:
    """The tool surface. Alive means the catalogue is non-empty and reachable."""
    try:
        count = len(gateway.registry)
    except Exception as exc:  # noqa: BLE001
        return Probe(name="mcp-gateway", kind="mcp", alive=False, detail=str(exc))
    return Probe(
        name="mcp-gateway",
        kind="mcp",
        alive=count > 0,
        detail=f"{count} tools registered" if count else "no tools registered",
    )


def _bus_probe(bus: Any) -> Probe:
    """Queue depth. A bus nobody drains looks identical to a hang from outside."""
    try:
        pending = int(bus.depth())
    except Exception as exc:  # noqa: BLE001
        return Probe(name="task-bus", kind="bus", alive=False, detail=str(exc))
    # A deep queue is not a dead bus, but it is not healthy either: work is
    # arriving faster than it is draining, and saying so early is the point.
    return Probe(
        name="task-bus",
        kind="bus",
        alive=True,
        data_age_sec=0.0 if pending < 200 else 1.0,
        max_age_sec=0.5,
        detail=f"{pending} tasks pending",
    )
