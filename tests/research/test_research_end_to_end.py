# Spec: Genesis Markdown/10-Architecture/Operating Model.md §2 §3
#       Genesis Markdown/20-Agents/Research/Agent — Topic Researcher.md
"""Typing a research question into the terminal, all the way to a saved note.

This is the path a person actually takes: text into the canvas command line,
`POST /v1/command`, and — some minutes later — findings in the research
directory and nodes on the canvas.

**Only two things are stubbed, and they are the two that leave this machine:**
the hosted model and the web. Everything between them is the real component —
the HTTP route, the deterministic command table, the answer ladder, the
planner's validation, the Task Bus, the daemon, the supervisor, the agent, the
research store, the vault mirror, the knowledge graph and the canvas.

That division is the point. A test that stubbed the bus or the daemon would
prove the agent works and say nothing about whether a typed sentence reaches
it, which is exactly the gap Operating Model §2 exists to close.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from genesis.llm.backend import Completion
from genesis.mcp.fence import wrap

QUESTION = "what are option GEX levels"


@dataclass
class StubModel:
    """The hosted tier, without the network.

    It answers by recognising the *real* system prompts rather than by being
    told which call is which — so if a prompt changes shape, this stops
    answering and the test fails loudly instead of quietly testing nothing.
    """

    model: str = "stub"
    catalogue: str = ""
    prompts: list[str] = field(default_factory=list)

    def complete(self, prompt: str, *, system: str | None = None, **_: Any) -> Completion:
        self.prompts.append(prompt)
        text = system or ""

        if "You are the planner inside Genesis" in text:
            # What the planner was told about the fleet. Asserted by the test,
            # because a real model cannot pick an agent it was never shown.
            self.catalogue = text
            body = json.dumps({
                "tasks": [{
                    "id": "t1", "agent": "topic-researcher", "type": "research.topic",
                    "args": {"subject": "option gamma exposure GEX levels"},
                    "depends_on": [],
                }],
                "speak_after": "t1",
            })
        elif "break a research request into search queries" in text:
            body = json.dumps({"queries": ["option gamma exposure GEX"]})
        elif "You are the Topic Researcher" in text:
            body = json.dumps({
                "title": "Option GEX levels",
                "summary": "Gamma exposure marks the strikes where dealer hedging "
                           "flips from damping volatility to amplifying it.",
                "body": "## What GEX measures\n\nDealer gamma, by strike.",
                "key_findings": ["Positive GEX pins price"],
                "open_questions": [], "tags": ["options"], "confidence": 0.6,
                "caveats": [],
            })
        else:  # pragma: no cover - a prompt this test does not know about
            raise AssertionError(f"unexpected system prompt: {text[:120]!r}")
        return Completion(text=body, model=self.model, latency_ms=1.0)


@dataclass
class StubWeb:
    """The gateway's web tools, fenced exactly as the real gateway fences them."""

    calls: list[str] = field(default_factory=list)

    def call(self, agent: str, capability: str, arguments: dict | None = None, **_: Any):
        self.calls.append(capability)

        @dataclass
        class Result:
            content: Any
            structured: Any = None
            fence: Any = None

        if capability == "web.search":
            rows = [{"url": "https://example.test/gex", "title": "GEX explained",
                     "text": "gamma exposure by strike"}]
            fenced = wrap(str(rows), source="exa")
            return Result(content=fenced.text, structured={"results": rows}, fence=fenced)
        if capability in ("web.read", "web.fetch"):
            fenced = wrap("Gamma exposure aggregates dealer gamma by strike.",
                          source="exa", url=(arguments or {}).get("url"))
            return Result(content=fenced.text, fence=fenced)
        raise RuntimeError(f"no such tool {capability}")


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A whole Genesis, on a temp disk, with the network replaced."""
    from genesis.agents.research.fleet import build_fleet, register as register_research
    from genesis.bus.bus import TaskBus
    from genesis.daemon.calendar import MarketCalendar
    from genesis.daemon.daemon import Daemon
    from genesis.memory.graph import KnowledgeGraph
    from genesis.observability import Console
    from genesis.orchestrator.registry import CapabilityRegistry
    from genesis.research.store import ResearchStore
    from genesis.server.analyst import ANALYST

    model, web = StubModel(), StubWeb()
    graph = KnowledgeGraph(path=tmp_path / "graph.db")
    research = ResearchStore(path=tmp_path / "research.db", vault=tmp_path / "vault",
                             graph=graph)
    bus = TaskBus(tmp_path / "genesis.db")

    fleet = build_fleet(gateway=web, store=research, backend=model,
                        planner_backend=model, console=Console(enabled=False))
    daemon = Daemon(bus, calendar=MarketCalendar(), console=Console(enabled=False))
    for agent in fleet.all():
        daemon.register(agent)
    daemon.boot()

    # Wire the analyst the way `genesis serve` wires it: a real bus, a real
    # registry, and the hosted tier swapped for the stub.
    #
    # The packaged defaults, NOT the developer's `~/.genesis/config.yaml`.
    # `analyst._build` calls `load_config()`, so this test used to inherit
    # whichever tiers the machine happened to be configured with -- it passed
    # while `small` was anthropic (which the stub below replaces) and failed
    # the moment someone pointed that tier at ollama or gemini, with a message
    # about a missing model that had nothing to do with the code under test. A
    # test that stubs the network so carefully must not let a local file
    # decide which client it stubs.
    from genesis.config import load_config

    defaults = load_config(None)
    monkeypatch.setattr("genesis.config.load_config", lambda *a, **k: defaults)
    monkeypatch.setattr(
        "genesis.llm.anthropic_backend.AnthropicBackend", lambda *a, **k: model
    )
    # The analyst asks `tool_routes.GATEWAY` for the MCP gateway, which spawns
    # seventeen server subprocesses. The agents in this test get their tools
    # injected directly, so the orchestrator's own tool surface is irrelevant
    # here -- and a test that starts OpenBB is not a test, it is a deployment.
    monkeypatch.setattr(
        "genesis.server.tool_routes.GATEWAY.get", lambda: (None, "stubbed for the test")
    )
    ANALYST.attach(
        bus=bus,
        registry=register_research(CapabilityRegistry(), fleet=fleet),
        supervisor=daemon.supervisor,
        scheduler=daemon.scheduler,
    )
    try:
        yield {"model": model, "web": web, "graph": graph, "research": research,
               "bus": bus, "daemon": daemon, "fleet": fleet}
    finally:
        ANALYST.attach()  # a module-level singleton must not leak into the next test
        daemon.shutdown()
        bus.close()


def _drain(daemon, *, ticks: int = 40) -> list[str]:
    """Run the daemon until it has executed something."""
    ran: list[str] = []
    for _ in range(ticks):
        ran += daemon.tick().ran
        if ran:
            break
        time.sleep(0.02)
    return ran


def test_a_typed_research_question_deploys_an_agent_and_saves_the_findings(desk, monkeypatch):
    tc = pytest.importorskip("starlette.testclient")
    from genesis.server.app import EventBus, build_app

    monkeypatch.setattr("genesis.server.reads._research", lambda: desk["research"])

    with tc.TestClient(build_app(EventBus())) as client:
        reply = client.post("/v1/command", json={"text": QUESTION}).json()

    # 1. It was not eaten by the deterministic table, and it did not fall all
    #    the way through to the reasoner answering from its own memory.
    assert reply["ok"] is True, reply
    # `analyst.planned` — the ladder took the *planning* rung, not the reasoner.
    # The distinction is the whole point: "planned" means agents were put on the
    # question, and "reasoned" would mean the model answered from memory.
    assert reply["command"] == "analyst.planned", reply["command"]
    # 2. Voice must never hang on agent work: the answer comes back immediately
    #    saying the work is running.
    assert "running" in reply["spoken"].lower() or "tell you" in reply["spoken"].lower(), \
        reply["spoken"]

    # 3. The planner was actually shown the agent it picked.
    assert "topic-researcher" in desk["model"].catalogue
    assert "research.topic" in desk["model"].catalogue

    # 4. The daemon claimed the dispatched task and an agent ran it.
    assert _drain(desk["daemon"]), "nothing was executed off the bus"

    # 5. The findings are saved, cited, and mirrored to the vault.
    notes = desk["research"].notes()
    assert len(notes) == 1, [n.title for n in notes]
    note = notes[0]
    assert note.created_by == "topic-researcher"
    assert note.sources and note.sources[0].url == "https://example.test/gex"
    assert "GEX" in note.title or "gex" in note.subject
    assert (desk["research"].vault / note.vault_path()).exists()

    # 6. The web was really used — search, then read. A note built without
    #    fetching anything would be the model's own memory with a citation.
    assert desk["web"].calls[0] == "web.search"
    assert any(c in ("web.read", "web.fetch") for c in desk["web"].calls)


def test_the_findings_reach_the_canvas(desk, tmp_path):
    """"Show me what you found" has to find it afterwards."""
    tc = pytest.importorskip("starlette.testclient")
    from genesis.research.canvas import CanvasStore
    from genesis.server.app import EventBus, build_app

    with tc.TestClient(build_app(EventBus())) as client:
        client.post("/v1/command", json={"text": QUESTION})
    _drain(desk["daemon"])

    canvas = CanvasStore(path=tmp_path / "canvas.db", graph=desk["graph"])
    cid = canvas.open_for("GEX", created_by="orchestrator")
    view = canvas.view(cid).to_dict()

    # The note and the page it cited, joined by the recorded citation.
    assert len(view["nodes"]) == 2, view["nodes"]
    assert {n["type"] for n in view["nodes"]} == {"thesis", "document"}
    assert [e["kind"] for e in view["edges"]] == ["derived_from"]

    # And the node is a reference: following it reaches the saved note.
    thesis = next(n for n in view["nodes"] if n["type"] == "thesis")
    assert desk["research"].note(thesis["ref"]) is not None


def test_with_no_model_the_question_is_declined_rather_than_guessed(desk, monkeypatch):
    """The user's situation today: no working API key.

    The honest outcome is that nothing is dispatched and nothing is written —
    not a note invented from the model's own memory, and not silence.
    """
    from genesis.server.analyst import ANALYST

    ANALYST.attach()  # no bus, no registry: exactly a Genesis with nothing wired
    tc = pytest.importorskip("starlette.testclient")
    from genesis.server.app import EventBus, build_app

    with tc.TestClient(build_app(EventBus())) as client:
        reply = client.post("/v1/command", json={"text": QUESTION}).json()

    assert reply["ok"] is False
    assert reply["spoken"], "a decline still has to say something"
    assert desk["research"].notes() == [], "nothing was invented"
