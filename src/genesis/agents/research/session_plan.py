# Spec: Genesis Markdown/20-Agents/Research/Agent — Session Plan.md
"""Agent — Session Plan. Your ideas in; a plan of action out.

Two task types, one agent, because they are one conversation: *"here are my
ideas"* and then *"so what do I do?"*.

``idea.record``
    Writes the trader's idea into the same store the Idea Synthesizer writes
    to, in the same shape, through the same :class:`~genesis.research.schema.Idea`
    type -- so *no invalidation, no idea* is enforced on yours exactly as on
    the synthesizer's, and a plan ranks both without caring who wrote them.
    When the orchestrator hears an idea spoken, a model turns the sentence
    into arguments; the readback in ``spoken_summary`` states every number it
    recorded, so a misheard 19,950 is caught by the person who said it.

``plan.build``
    Ranks the live ideas, sizes each through the risk gate's dry run, lists
    levels and what is in the way, and saves a re-readable brief to the vault.

``tier: none``. Nothing here needs a model -- the numbers are the gate's and
the words are yours -- and a spinal agent that later "gains" one is refused at
load time (``SPINAL_AGENTS``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from genesis.agents.base import Agent, AgentDeclaration, TaskResult
from genesis.errors import FatalError
from genesis.research.plan import SessionPlan, build_plan
from genesis.research.schema import Idea, ResearchNote
from genesis.research.store import ResearchStore, new_note_id

__all__ = [
    "DECLARATION",
    "PlanInputs",
    "SessionPlanAgent",
    "default_inputs",
    "live_ideas",
    "record_idea",
]

DECLARATION = AgentDeclaration(
    id="session-plan",
    name="Session Plan",
    family="research",
    cadence=[{"type": "on-demand"}],
    tools=[],
    memory={
        "read": ["shared", "idea-synthesizer", "session-plan", "ledger", "lessons"],
        "write": ["session-plan"],
    },
    model_tier="none",
    timeout_sec=60,
)


def record_idea(store: ResearchStore, args: dict[str, Any], *, trace_id: str | None = None) -> ResearchNote:
    """Validate and store one of the trader's ideas. Raises on a hope.

    One function, every door: the agent, ``genesis idea add`` and
    ``POST /v1/ideas`` all call this, so an idea cannot be looser through one
    of them than through the others (Operating Model §1).
    """
    raw = dict(args)
    for key in ("entry_zone", "targets"):
        if isinstance(raw.get(key), str):
            raw[key] = [float(x) for x in raw[key].replace("–", "-").replace(",", " ").replace("-", " ").split()]
    raw.setdefault("conflicts", "not stated — the trader's own idea")
    raw.setdefault("invalidation_reason", "stated by the trader")
    if raw.get("stop_price") is not None and not raw.get("invalidation"):
        side = "below" if raw.get("direction") == "long" else "above"
        raw["invalidation"] = f"a trade {side} {float(raw['stop_price']):g}"
    raw["author"] = "human"
    raw["symbol"] = str(raw.get("symbol", "")).strip().upper()
    if not raw.get("invalidation"):
        # Idea Schema's rule, said the way a person needs to hear it rather than
        # as a validation error: an idea without a stated invalidation is a hope.
        raise FatalError(
            "not an idea yet: say where it's wrong — a stop price, or the condition "
            "that would prove it wrong. No invalidation, no idea.",
            spoken_summary="Where is it wrong? Give me a price or a condition and I'll record it.",
        )
    try:
        idea = Idea.model_validate(raw)
    except Exception as exc:  # pydantic's message names the field; keep it
        raise FatalError(
            f"not an idea yet: {exc}",
            spoken_summary="I can't record that yet — I need a direction, a thesis, and where it's wrong.",
        ) from exc

    zone = f" {idea.entry_zone[0]:g} to {idea.entry_zone[1]:g}" if idea.entry_zone else ""
    stop = f", wrong at {idea.stop_price:g}" if idea.stop_price is not None else ", no stop price yet"
    body = "\n\n".join([
        f"## Thesis\n\n{idea.thesis}",
        f"## Invalidation\n\n**{idea.invalidation}**\n\n{idea.invalidation_reason}",
        f"## Against it\n\n{idea.conflicts}",
    ])
    return store.put(ResearchNote(
        id=new_note_id(),
        kind="idea",
        title=f"{idea.symbol} {idea.direction} — {idea.setup or idea.timeframe} (yours)",
        # Distinct from the synthesizer's `nq`, so yours never supersedes its
        # idea or it yours. Restating your own NQ long updates it.
        subject=f"{idea.symbol.lower()}-{idea.direction}",
        created_by="human",
        summary=f"{idea.direction.capitalize()} {idea.symbol}{zone}{stop}.",
        body=body,
        tags=("idea", "mine", idea.symbol.lower(), idea.timeframe),
        data={**idea.model_dump(mode="json"), "status": "active"},
        half_life_hours=max(24.0, idea.horizon_days * 24.0),
        confidence=idea.confidence,
        trace_id=trace_id,
    ))


def live_ideas(store: ResearchStore, *, now: datetime | None = None, limit: int = 50) -> list[tuple[str, Idea]]:
    """Current ideas, yours and the synthesizer's, that have not expired.

    An idea past its horizon is not on the desk any more, whether or not the
    nightly consolidation has marked it yet -- the plan checks the date itself
    rather than trusting a pass that may not have run.
    """
    now = now or datetime.now(UTC)
    out: list[tuple[str, Idea]] = []
    for note in store.notes(kind="idea", limit=limit):
        if note.data.get("status", "active") != "active":
            continue
        try:
            idea = Idea.model_validate({k: v for k, v in note.data.items() if k in Idea.model_fields})
        except Exception:  # noqa: BLE001 - a malformed stored idea is skipped, not fatal
            continue
        if note.created + timedelta(days=idea.horizon_days) < now:
            continue
        out.append((note.id, idea))
    return out


@dataclass
class PlanInputs:
    """Everything a plan reads, as callables so each is fetched when it runs.

    Built once per process by :func:`genesis.cli._plan_inputs` and shared by
    the agent, the CLI and the HTTP route, so all three produce the same plan
    from the same inputs.
    """

    allowlist: Callable[[], list[str]]
    configured: Callable[[], list[str]]
    max_contracts: Callable[[], int]
    size: Callable[[], Callable[[dict[str, Any]], dict[str, Any]] | None] = lambda: None
    #: Said on the plan when ``size`` gives nothing. The caller knows why --
    #: "the order path is off" and "the server is not running" are different
    #: fixes, and the plan must not guess which.
    size_off: str = ("the order path is off, so nothing can be sized — "
                     "`execution.enabled: true` and restart the server")
    account: Callable[[], Any] = lambda: None
    lessons: Callable[[], list[Any]] = lambda: []
    events: Callable[[], list[dict[str, Any]]] = lambda: []


def default_inputs(config: Any, *, config_path: Any = None) -> PlanInputs:
    """The live inputs, each read when the plan runs rather than when it is built.

    One builder for every door -- the daemon's agent, ``genesis plan`` and
    ``/v1/plan`` -- so the three cannot drift into three different plans. The
    envelope is re-read on each call (``load_config``), so a limit tightened
    mid-session is the limit the next plan sizes against, as it is for orders.

    ``config_path`` is the file ``config`` came from. Re-reading the *default*
    file instead would make ``genesis --config other.yaml plan`` size against
    a different envelope than the one it was asked about.
    """
    from pathlib import Path

    def envelope() -> Any:
        from genesis.config import DEFAULT_CONFIG_PATH, load_config

        return load_config(config_path or DEFAULT_CONFIG_PATH).risk

    def size() -> Any:
        from genesis.execution import order_manager

        m = order_manager.current()
        return m.dry_run if m is not None else None

    def account() -> Any:
        from genesis.execution import order_manager

        m = order_manager.current()
        if m is None or m.accountant is None:
            return None
        return m.call(m.accountant.snapshot)

    memory = Path(config.memory.db_path).expanduser().parent

    def lessons() -> list[Any]:
        from genesis.journal.store import JournalStore

        path = memory / "journal.db"
        return JournalStore(path).lessons() if path.exists() else []

    def events() -> list[dict[str, Any]]:
        from genesis.news.econ import upcoming
        from genesis.news.store import NewsStore

        return upcoming(NewsStore(memory / "news.db"))

    return PlanInputs(
        allowlist=lambda: list(envelope().symbol_allowlist),
        configured=lambda: [str(s.get("symbol_id", "")) for s in config.marketdata.live],
        max_contracts=lambda: int(envelope().max_contracts_per_symbol),
        size=size, account=account, lessons=lessons, events=events,
    )


def _safe(fn: Callable[[], Any], default: Any, degraded: list[str], what: str) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - a missing input is a stated gap, not a crash
        degraded.append(f"{what} unavailable: {getattr(exc, 'reason', exc)}")
        return default


class SessionPlanAgent(Agent):
    """Record ideas; build plans. Pure assembly -- no model, no sizing of its own."""

    def __init__(self, store: ResearchStore, *, inputs: PlanInputs) -> None:
        super().__init__(DECLARATION)
        self.store = store
        self.inputs = inputs

    def build(self, *, save: bool = True, trace_id: str | None = None) -> tuple[SessionPlan, ResearchNote | None]:
        degraded: list[str] = []
        plan = build_plan(
            live_ideas(self.store),
            allowlist=self.inputs.allowlist(),
            configured=self.inputs.configured(),
            max_contracts=self.inputs.max_contracts(),
            size=_safe(self.inputs.size, None, degraded, "the risk gate"),
            account=_safe(self.inputs.account, None, degraded, "the account"),
            lessons=_safe(self.inputs.lessons, [], degraded, "lessons"),
            events=_safe(self.inputs.events, [], degraded, "the economic calendar"),
            size_off=self.inputs.size_off,
        )
        if degraded:
            plan = SessionPlan(as_of=plan.as_of, items=plan.items, desk=plan.desk,
                               degraded=plan.degraded + tuple(degraded), sources=plan.sources)
        note = None
        if save:
            note = self.store.put(ResearchNote(
                id=new_note_id(), kind="plan", subject="session",
                title=f"Plan of action — {plan.as_of[:16].replace('T', ' ')}",
                created_by=self.id, summary=plan.spoken(), body=plan.brief(),
                tags=("plan",), data=plan.to_dict(),
                half_life_hours=24.0, degraded=bool(plan.degraded),
                caveats=plan.degraded, trace_id=trace_id,
            ))
        return plan, note

    def execute(self, task: Any) -> TaskResult:
        args = dict(getattr(task, "args", {}) or {})
        task_id = getattr(task, "id", "<none>")
        trace_id = getattr(task, "trace_id", None)

        if getattr(task, "type", "") == "idea.record":
            note = record_idea(self.store, args, trace_id=trace_id)
            return TaskResult(
                task_id=task_id, agent=self.id,
                data={"note_id": note.id, "vault_path": note.vault_path(), **note.data},
                wrote=({"layer": "memory", "namespace": "session-plan", "note": note.id},
                       {"layer": "vault", "path": note.vault_path()}),
                spoken_summary=f"Recorded: {note.summary}",
            )

        plan, note = self.build(save=bool(args.get("save", True)), trace_id=trace_id)
        wrote: tuple[dict[str, Any], ...] = ()
        if note is not None:
            wrote = ({"layer": "memory", "namespace": "session-plan", "note": note.id},
                     {"layer": "vault", "path": note.vault_path()})
        return TaskResult(
            task_id=task_id, agent=self.id,
            data={**plan.to_dict(), "note_id": note.id if note else None,
                  "vault_path": note.vault_path() if note else None},
            wrote=wrote,
            spoken_summary=plan.spoken() + (" The brief is in your notes." if note else ""),
            degraded=bool(plan.degraded),
        )
