# Spec: Genesis Markdown/60-UI/Automation.md §Node library
"""The node library: gates, transforms, signals, alerts, processes, the catalogue."""

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from genesis.automation import actions as act
from genesis.automation.actions import ACTIONS, CATEGORIES
from genesis.automation.catalog import TOOL_NODES, nodes
from genesis.automation.grant import permits
from genesis.automation.runner import WorkflowAgent
from genesis.automation.store import WorkflowStore
from genesis.automation.workflow import Workflow
from genesis.bus import TaskBus, TaskState
from genesis.charting.bars import Bars
from genesis.daemon import MarketCalendar

OPEN = dt.datetime(2026, 8, 31, 15, 0, tzinfo=dt.UTC)     # Mon 11:00 ET
SATURDAY = dt.datetime(2026, 8, 29, 15, 0, tzinfo=dt.UTC)


@pytest.fixture
def world(tmp_path: Path):
    bus = TaskBus(tmp_path / "genesis.db", claim_ttl_sec=5.0)
    store = WorkflowStore(tmp_path / "workflows.db")
    yield bus, store
    store.close()
    bus.close()


def wf(steps: list[dict[str, Any]], **extra: Any) -> Workflow:
    return Workflow.model_validate({
        "id": extra.pop("id", "t"), "name": extra.pop("name", "Test"),
        "trigger": {"type": "on-demand"}, "start": steps[0]["id"] if steps else None,
        "steps": steps, **extra,
    })


def chain(*steps: dict[str, Any]) -> list[dict[str, Any]]:
    """Wire a list of steps in order, each reading the previous one."""
    out = []
    for i, s in enumerate(steps):
        s = dict(s)
        if i + 1 < len(steps):
            s.setdefault("next", steps[i + 1]["id"])
        if i > 0 and s.get("kind") == "action" and "input" not in s and ACTIONS[s["action"]].needs_input:
            s["input"] = steps[i - 1]["id"]
        out.append(s)
    return out


class Task:
    def __init__(self, n: int = 1, args: dict[str, Any] | None = None) -> None:
        self.id = f"task-{n}"
        self.trace_id = f"tr-{n}"
        self.args = args or {}


def run(world, workflow: Workflow, *, now=OPEN, n: int = 1, args=None, save: bool = True):  # noqa: ANN001, ANN201
    bus, store = world
    if save:
        store.save(workflow, author="operator")
    agent = WorkflowAgent(workflow, 1, store=store, bus=bus, calendar=MarketCalendar(), clock=lambda: now)
    agent.start()
    agent.run_task(Task(n, args))
    return store.runs(workflow.id)[0]


def statuses(run_row) -> dict[str, str]:  # noqa: ANN001
    return {s["step"]: s["status"] for s in run_row["steps"]}


def items_step(step_id: str, items: list[Any]) -> dict[str, Any]:
    """A template node standing in for a tool: emits fixed items via a process-free path."""
    return {"id": step_id, "kind": "action", "action": "data.template", "params": {"template": "x"}}


# -- catalogue ---------------------------------------------------------------


def test_every_tool_node_is_inside_the_grant() -> None:
    assert [c for c, *_ in TOOL_NODES if not permits(c)] == []


def test_every_node_has_a_known_category_and_the_palette_is_large() -> None:
    known = {c for c, _ in CATEGORIES}
    palette = nodes()["nodes"]
    assert {n["category"] for n in palette} <= known
    assert len(palette) >= 100


def test_unknown_or_bad_settings_are_refused_at_save() -> None:
    with pytest.raises(ValidationError, match="unknown setting"):
        wf([{"id": "a", "kind": "action", "action": "signal.price",
             "params": {"symbol": "NVDA", "level": 1, "levle": 2}}])
    with pytest.raises(ValidationError, match="must be one of"):
        wf([{"id": "a", "kind": "action", "action": "signal.price",
             "params": {"symbol": "NVDA", "level": 1, "direction": "sideways"}}])
    with pytest.raises(ValidationError, match="required"):
        wf([{"id": "a", "kind": "action", "action": "signal.price", "params": {"symbol": "NVDA"}}])
    with pytest.raises(ValidationError, match="only a check or a pass/fail"):
        wf([{"id": "a", "kind": "action", "action": "data.template", "params": {"template": "x"}, "on_fail": "b"},
            {"id": "b", "kind": "action", "action": "logic.stop"}])


def test_trigger_is_a_reserved_input_not_a_step_id() -> None:
    wf([{"id": "a", "kind": "action", "action": "logic.contains", "input": "trigger",
         "params": {"keywords": "earnings"}}])
    with pytest.raises(ValidationError, match="reserved"):
        wf([{"id": "trigger", "kind": "action", "action": "logic.stop"}])


# -- gates -------------------------------------------------------------------


def test_session_and_day_gates_branch(world) -> None:
    steps = [
        {"id": "gate", "kind": "action", "action": "logic.days", "params": {"days": ["mon", "tue"]},
         "next": "yes", "on_fail": "no"},
        {"id": "yes", "kind": "action", "action": "logic.stop"},
        {"id": "no", "kind": "action", "action": "logic.stop"},
    ]
    assert statuses(run(world, wf(steps), now=OPEN))["yes"] == "ok"
    assert statuses(run(world, wf(steps, id="t2"), now=SATURDAY, n=2))["no"] == "ok"

    session = wf([{"id": "g", "kind": "action", "action": "logic.session", "params": {"sessions": ["closed"]}}], id="s")
    assert run(world, session, n=3)["status"] == "failed", "11:00 ET on a Monday is not closed"


def test_contains_reads_the_trigger_data(world) -> None:
    steps = [{"id": "k", "kind": "action", "action": "logic.contains", "input": "trigger",
              "params": {"keywords": "guidance, downgrade"}}]
    assert run(world, wf(steps), args={"event": "news.spike", "headline": "NVDA raises guidance"})["status"] == "ok"
    assert run(world, wf(steps, id="t2"), n=2, args={"headline": "quiet day"})["status"] == "failed"


def test_only_if_changed_passes_once_for_the_same_input(world) -> None:
    steps = [{"id": "c", "kind": "action", "action": "logic.changed", "input": "trigger"}]
    workflow = wf(steps)
    assert run(world, workflow, n=1, args={"x": 1})["status"] == "ok"
    assert run(world, workflow, n=2, args={"x": 1}, save=False)["status"] == "failed"
    assert run(world, workflow, n=3, args={"x": 2}, save=False)["status"] == "ok"


def test_cooldown_holds_until_the_window_passes(world) -> None:
    workflow = wf([{"id": "cd", "kind": "action", "action": "logic.cooldown", "params": {"minutes": 60}}])
    assert run(world, workflow, n=1)["status"] == "ok"
    assert run(world, workflow, n=2, now=OPEN + dt.timedelta(minutes=30), save=False)["status"] == "failed"
    assert run(world, workflow, n=3, now=OPEN + dt.timedelta(minutes=61), save=False)["status"] == "ok"


# -- transforms --------------------------------------------------------------


class Ctx:
    workflow = type("W", (), {"name": "Scan"})()
    now = OPEN
    tz = MarketCalendar().tz


ROWS = {"items": [{"symbol": "nvda", "change_pct": 4.2}, {"symbol": "AMD", "change_pct": -1.0},
                  {"symbol": "TSLA", "change_pct": 7.5}, {"symbol": "NVDA", "change_pct": 4.2}]}


def test_transforms_compose() -> None:
    kept = act.ACTIONS["data.filter"].run(Ctx, {"field": "change_pct", "op": ">", "value": "3"}, ROWS)
    ordered = act.ACTIONS["data.sort"].run(Ctx, {"field": "change_pct", "order": "descending"}, kept)
    top = act.ACTIONS["data.take"].run(Ctx, {"count": 2, "from": "start"}, ordered)
    symbols = act.ACTIONS["data.symbols"].run(Ctx, {}, top)
    assert symbols["items"] == ["TSLA", "NVDA"]
    assert act.ACTIONS["data.dedupe"].run(Ctx, {"field": "symbol"}, ROWS)["structured"]["items"][-1]["symbol"] == "TSLA"


def test_templates_fill_named_slots_only() -> None:
    text = act.render("{count} movers: {symbols} for {workflow}", Ctx, ROWS)
    assert text == "4 movers: NVDA, AMD, TSLA, NVDA for Scan"
    # attribute access and indexing are not an expression language by the back door
    assert act.render("{workflow.__class__} {items[0]} {nope}", Ctx, ROWS) == "{workflow.__class__} {items[0]} {nope}"


def test_comparison_fails_closed_on_non_numbers() -> None:
    with pytest.raises(act.Fail):
        act.ACTIONS["logic.compare"].run(Ctx, {"field": "close", "op": ">", "value": "10"},
                                         {"structured": {"close": "n/a"}})


# -- signals, each, alerts ---------------------------------------------------


def fake_bars(closes: list[float], volume: list[float] | None = None) -> Bars:
    c = np.array(closes, dtype=float)
    times = tuple(OPEN - dt.timedelta(days=len(c) - i) for i in range(len(c)))
    return Bars(symbol="NVDA", timeframe="1D", times=times, open=c, high=c + 1, low=c - 1, close=c,
                volume=np.array(volume or [1000.0] * len(c)))


def test_indicator_signal_from_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    falling = [100 - i * 1.5 for i in range(60)]
    monkeypatch.setattr(act, "_bars", lambda s, tf, n: fake_bars(falling))
    hit = act.ACTIONS["signal.indicator"].run(
        Ctx, act.numbers({"symbol": "NVDA", "indicator": "rsi", "op": "<", "value": 30}, ACTIONS["signal.indicator"]), None)
    assert hit["structured"]["value"] < 30
    with pytest.raises(act.Fail):
        act.ACTIONS["signal.indicator"].run(
            Ctx, act.numbers({"symbol": "NVDA", "indicator": "rsi", "op": ">", "value": 70}, ACTIONS["signal.indicator"]), None)


def test_volume_spike_and_breakout(monkeypatch: pytest.MonkeyPatch) -> None:
    closes = [50.0] * 25 + [60.0]
    monkeypatch.setattr(act, "_bars", lambda s, tf, n: fake_bars(closes, [1000.0] * 25 + [5000.0]))
    assert act.ACTIONS["signal.volume"].run(Ctx, {"symbol": "NVDA", "lookback": 20, "multiple": 3}, None)["structured"]["multiple"] == 5.0
    assert act.ACTIONS["signal.breakout"].run(Ctx, {"symbol": "NVDA", "lookback": 20, "direction": "high"}, None)


def test_repeat_for_each_and_alert_with_cooldown(world, monkeypatch: pytest.MonkeyPatch) -> None:
    prices = {"NVDA": 260.0, "AMD": 140.0, "TSLA": 251.0}
    monkeypatch.setattr(act, "_quote", lambda s: {"symbol": s.upper(), "close": prices[s.upper()],
                                                   "change_pct": 1.0, "as_of": "2026-08-31"})
    steps = chain(
        {"id": "list", "kind": "action", "action": "data.template", "input": "trigger",
         "params": {"template": "{symbols}"}},
        {"id": "above", "kind": "action", "action": "signal.price", "input": "list", "each": True,
         "params": {"direction": "above", "level": 250}},
        {"id": "tell", "kind": "action", "action": "output.alert", "input": "above",
         "params": {"title": "{count} above 250", "message": "{symbols}", "cooldown_minutes": 30}},
    )
    workflow = wf(steps)
    row = run(world, workflow, args={"symbols": ["NVDA", "AMD", "TSLA"]})
    assert row["status"] == "ok"
    _bus, store = world
    alerts = store.alerts()
    assert len(alerts) == 1 and alerts[0]["title"] == "2 above 250"
    assert alerts[0]["message"] == "NVDA, TSLA"

    run(world, workflow, n=2, now=OPEN + dt.timedelta(minutes=10), args={"symbols": ["NVDA"]}, save=False)
    assert len(store.alerts()) == 1, "the cooldown suppresses a repeat"


# -- agents & processes ------------------------------------------------------


def test_agent_nodes_dispatch_with_their_task_type(world) -> None:
    bus, _store = world
    workflow = wf([{"id": "s", "kind": "action", "action": "agent.summarise",
                    "params": {"subject": "Tesla"}}])
    assert run(world, workflow)["status"] == "ok"
    tasks = bus.by_state(TaskState.PENDING)
    assert [(t.agent, t.type, t.args["subject"]) for t in tasks] == [("topic-researcher", "research.summarise", "Tesla")]


def test_a_process_runs_inline_and_cannot_call_itself(world) -> None:
    _bus, store = world
    process = wf([{"id": "say", "kind": "action", "action": "data.template", "input": "trigger",
                   "params": {"template": "got {count}"}}], id="counter", name="Counter")
    store.save(process, author="operator")
    caller = wf(chain(
        {"id": "p", "kind": "action", "action": "flow.process", "params": {"workflow": "counter"}},
        {"id": "k", "kind": "action", "action": "logic.contains", "input": "p", "params": {"keywords": "got"}},
    ), id="caller")
    assert run(world, caller)["status"] == "ok"

    loop = wf([{"id": "me", "kind": "action", "action": "flow.process", "params": {"workflow": "loopy"}}], id="loopy")
    assert run(world, loop, n=2)["status"] == "failed"
