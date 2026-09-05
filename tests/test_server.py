# Spec: Genesis Markdown/60-UI/UI Stack.md §7 Transport
"""The UI server: shape, honesty, and the idle promise.

The properties worth testing are not "does it return 200". They are the ones
the UI note makes structural claims about -- no write path on the socket, a
watermark that cannot fake continuity, and a surface that does nothing until
asked.
"""

from __future__ import annotations

import json

import pytest

from genesis.server.app import EventBus, build_app

starlette_testclient = pytest.importorskip("starlette.testclient")
TestClient = starlette_testclient.TestClient


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def client(bus):
    with TestClient(build_app(bus)) as c:
        yield c


# -- shape ------------------------------------------------------------------


def test_the_socket_has_no_write_path():
    """`transport.ts` has no `send`, deliberately: commands go over HTTP so
    they carry a response and an audit line. The server must not offer a way
    around that, or the constraint is decoration."""
    app = build_app(EventBus())
    sockets = [r for r in app.routes if type(r).__name__ == "WebSocketRoute"]
    assert len(sockets) == 1
    assert sockets[0].path == "/v1/events"

    posts = {
        r.path for r in app.routes
        if getattr(r, "methods", None) and "POST" in r.methods
    }
    # The complete efferent surface, enumerated. This assertion is meant to
    # fail when someone adds a POST -- that is the review prompt, and the
    # question to ask at that moment is whether the new route can reach an
    # order path.
    #
    #   /v1/command           a typed command; the same path voice takes
    #   /v1/voice/utterance   audio in, action out
    #   /v1/backtest/run      a simulation over stored bars. Burns CPU and
    #                         writes a durable row, so it is a POST -- but it
    #                         talks to a simulated venue and has no route to a
    #                         broker.
    assert posts == {"/v1/command", "/v1/voice/utterance", "/v1/backtest/run"}


def test_no_route_reaches_an_order_path():
    """`Safety Invariants` #1 as a structural test, not a promise.

    There is no `place_order`. If a route ever appears whose path suggests one,
    this fails and somebody has to justify it in a review rather than in a
    commit message.
    """
    app = build_app(EventBus())
    forbidden = ("order", "trade", "position", "broker", "execute", "place")
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if "POST" not in methods:
            continue
        assert not any(word in path.lower() for word in forbidden), (
            f"{path} looks like an execution route; Safety Invariants #1 says "
            "no order reaches a broker except through the pre-trade risk engine"
        )


def test_snapshot_reports_a_confirm_mode_and_an_unhalted_floor(client):
    """Safety Invariants §5: never ship a default that trades unattended."""
    snap = client.get("/v1/snapshot").json()
    assert snap["safety"]["approvalMode"] == "confirm"
    assert snap["safety"]["halted"] is False
    assert "watermark" in snap


def test_health_says_idle(client):
    assert client.get("/v1/health").json() == {"ok": True, "idle": True}


# -- the idle promise -------------------------------------------------------


def test_nothing_is_emitted_until_something_is_asked(bus, client):
    """The whole point of replacing the mock: an idle Genesis produces no
    events. The mock transport opened onto a busy simulated fleet whether or
    not anything was running, which is what made the surface a demo."""
    assert bus.watermark == "e0"
    client.get("/v1/snapshot")
    client.get("/v1/health")
    assert bus.watermark == "e0", "a read produced an event"


def test_a_command_narrates_itself_onto_the_bus(bus, client):
    before = bus.watermark
    client.post("/v1/command", json={"text": "status"})
    assert bus.watermark != before
    events = [e["event"] for e in bus._recent]
    assert "task.dispatched" in events
    assert "task.completed" in events
    # The core returns to idle. A sigil left mid-utterance is a UI that lies
    # about what the system is doing.
    states = [e["data"].get("to") for e in bus._recent if e["event"] == "voice.state_changed"]
    assert states[-1] == "idle"


def test_a_failed_command_emits_task_failed_not_completed(bus, client):
    client.post("/v1/command", json={"text": "make me a sandwich"})
    events = [e["event"] for e in bus._recent]
    assert "task.failed" in events
    assert "task.completed" not in events


# -- the watermark ----------------------------------------------------------


def test_events_are_totally_ordered(bus):
    ids = [bus.emit("x")["id"] for _ in range(5)]
    assert ids == ["e1", "e2", "e3", "e4", "e5"]


def test_replay_returns_only_what_came_after(bus):
    bus.emit("a")
    mark = bus.watermark
    bus.emit("b")
    bus.emit("c")
    assert [e["event"] for e in bus.since(mark)] == ["b", "c"]


def test_an_aged_out_watermark_replays_nothing_rather_than_everything(bus):
    """Returning the whole buffer would look like continuity across a gap the
    server cannot vouch for. The UI is required to report a gap; the server
    must not hide one from it."""
    assert bus.since("e999999") == []
    assert bus.since(None) == []


def test_the_socket_streams_an_event(bus):
    with TestClient(build_app(bus)) as client:
        with client.websocket_connect("/v1/events") as ws:
            bus.emit("task.started", data={"command": "chart"})
            frame = json.loads(ws.receive_text())
            assert frame["event"] == "task.started"
            assert frame["id"].startswith("e")
            # The UI's field names, not ours. See
            # `test_the_envelope_matches_the_uis_contract_exactly`.
            assert "ts" in frame and "trace_id" in frame


# -- voice ------------------------------------------------------------------


def test_no_audio_is_refused_before_the_model_loads(client):
    """A tap that released early must not spend seconds in whisper only to
    transcribe silence into a wrong command."""
    res = client.post("/v1/voice/utterance", files={"audio": ("u.webm", b"tiny", "audio/webm")})
    body = res.json()
    assert body["ok"] is False
    assert body["command"] == "no_audio"


def test_a_missing_file_is_a_400(client):
    assert client.post("/v1/voice/utterance", data={}).status_code == 400


def test_an_empty_command_is_a_400(client):
    assert client.post("/v1/command", json={"text": "  "}).status_code == 400


# -- the envelope contract --------------------------------------------------


def test_the_envelope_matches_the_uis_contract_exactly(bus):
    """`ui/src/types/events.ts` defines Envelope, and the store reads
    `e.trace_id`. An envelope with the wrong field names is accepted by the
    socket, ignored by every store handler, and produces a UI that looks
    connected and does nothing — silent from both ends.

    This was a real bug: the first version emitted `trace`, `at` and
    `severity`, none of which the UI reads.
    """
    envelope = bus.emit("task.started", data={"task_id": "t1", "agent": "orchestrator"})
    assert set(envelope) == {
        "id", "event", "ts", "trace_id", "source", "priority", "speak", "data"
    }
    # `ts` is an ISO string, not an epoch int.
    assert isinstance(envelope["ts"], str) and "T" in envelope["ts"]
    assert envelope["priority"] in {"critical", "high", "normal", "low"}


def test_a_command_emits_the_whole_task_lifecycle(bus, client):
    """`task.dispatched` is what CREATES the task record and the edge token;
    `started` and `completed` look it up by id. Emitting only the ending
    leaves the store nothing to update — the graph stays still while the
    command runs perfectly, which reads as a broken UI."""
    client.post("/v1/command", json={"text": "status"})
    events = [e["event"] for e in bus._recent]
    assert events.index("task.dispatched") < events.index("task.started")
    assert events.index("task.started") < events.index("task.completed")

    dispatched = next(e for e in bus._recent if e["event"] == "task.dispatched")
    assert set(dispatched["data"]) >= {
        "task_id", "parent_task_id", "agent", "task_type", "lane"
    }
    completed = next(e for e in bus._recent if e["event"] == "task.completed")
    assert completed["data"]["task_id"] == dispatched["data"]["task_id"]
    # Money is a string all the way to the UI, which sums it as fixed point.
    assert isinstance(completed["data"]["cost_usd"], str)


def test_one_command_is_one_trace(bus, client):
    """Everything the UI groups — the trace view, the lineage edge — keys on
    trace_id. Two ids for one utterance splits it into two stories."""
    client.post("/v1/command", json={"text": "status"})
    traces = {e["trace_id"] for e in bus._recent}
    assert len(traces) == 1
