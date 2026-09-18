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
    #   /v1/voice/say         text in, WAV out. A POST because it spends money
    #                         at a TTS vendor and takes real time -- the same
    #                         reasoning UI Stack §7 gives for commands.
    #   /v1/backtest/run      a simulation over stored bars. Burns CPU and
    #                         writes a durable row, so it is a POST -- but it
    #                         talks to a simulated venue and has no route to a
    #                         broker.
    #   /v1/mcp/call          one MCP tool, run by hand, through the same
    #                         `Gateway.call` the orchestrator uses. A POST
    #                         because it acts and takes real time. It refuses
    #                         any tool the catalogue marks mutating, and the
    #                         `operator` allow-list grants no write pattern --
    #                         two independent reasons it cannot reach an order
    #                         path, neither of which is this test.
    #
    #   /v1/canvas/*          six writes, and they were asked the question
    #                         above. Each one edits an *arrangement*: canvas
    #                         membership, a node's position, or an edge in the
    #                         Knowledge Graph. `canvas_routes.py` imports no
    #                         execution code, the graph holds no orders, and
    #                         `assert_edge` can only write an edge kind from
    #                         Knowledge Graph.md's own list -- none of which
    #                         names an order, a size or a broker. They are here
    #                         rather than in `reads.py` precisely so that they
    #                         stay countable.
    #
    #   /v1/conversations/{id}/delete
    #                         throws away one saved Ask Genesis conversation.
    #                         `conversation_routes.py` imports no execution
    #                         code; the store is the trader's own chat
    #                         scrollback in its own SQLite file, with no order,
    #                         size or broker anywhere in its schema. The turns
    #                         are written by `/v1/command` above -- this route
    #                         only reads them back and deletes.
    #
    #   /v1/watchlists/*      six writes, each a single fact about the trader's
    #                         own symbol lists: make a list, rename it, delete
    #                         it, add or drop a symbol, move a symbol between
    #                         sections. `watchlist_routes.py` imports no
    #                         execution code; `watchlists.db` is the trader's
    #                         own file with no order, size or broker in its
    #                         schema -- the conversation-store pattern. A symbol
    #                         is a string validated by `company.symbols`, never
    #                         a position.
    #
    #   /v1/notebook/*        nine writes, and they write **files**, not rows --
    #                         a vault is a directory of markdown the trader
    #                         also opens in Obsidian. Every path passes through
    #                         `Vault.resolve`, which joins to the vault root,
    #                         resolves symlinks and refuses anything landing
    #                         outside it; writes are markdown-only. That single
    #                         door is why this is nine routes and one check.
    #                         `notebook_routes.py` imports no execution code,
    #                         and a note has no order, size or broker in it --
    #                         it is prose the trader and the research agents
    #                         both write, through the same routes, which is the
    #                         parity rule rather than an exception to it.
    #
    #   /v1/settings/models/set
    #                         points one model tier at one backend and model.
    #                         Deliberately narrow: it writes `llm.<tier>` and
    #                         refuses every other key, so it is not a path from
    #                         the browser to the risk limits -- Safety
    #                         Invariants #9 keeps approval mode off a panel.
    #                         It cannot reach an order path: `llm/tiers.py`
    #                         imports config and yaml, and nothing it writes is
    #                         read by the execution family, which is `tier:
    #                         none` and has no model in its call path at all.
    #
    #   /v1/market/ranges/*   three writes over the trader's candle-range
    #                         scrapbook: capture a named window of price,
    #                         rename it, delete it. Capture is a POST because
    #                         it reaches a vendor and takes real time. It
    #                         cannot reach an order path: `range_routes.py`
    #                         imports no execution code, `ranges.db` is the
    #                         trader's own file holding OHLCV rows and a name,
    #                         and the fetch is a read of a free public feed --
    #                         the conversation-store pattern again.
    #
    #   /v1/charting/drawings/*
    #                         three writes over the trader's own chart marks:
    #                         save one, delete one, clear a series.
    #                         `drawing_routes.py` imports no execution code and
    #                         `drawings.db` holds shapes -- a `trade_plan`
    #                         drawing has entry, stop and targets and no size,
    #                         no account and no broker, which is the markup
    #                         schema's own guarantee rather than this test's.
    assert posts == {
        "/v1/command",
        "/v1/voice/utterance",
        "/v1/voice/say",
        "/v1/backtest/run",
        "/v1/mcp/call",
        "/v1/canvas/new",
        "/v1/canvas/{canvas_id}/add",
        "/v1/canvas/{canvas_id}/remove",
        "/v1/canvas/{canvas_id}/move",
        "/v1/canvas/{canvas_id}/unlink",
        "/v1/settings/models/set",
        "/v1/canvas/{canvas_id}/link",
        "/v1/canvas/{canvas_id}/delete",
        "/v1/conversations/{conversation_id}/delete",
        "/v1/watchlists/new",
        "/v1/watchlists/{list_id}/rename",
        "/v1/watchlists/{list_id}/delete",
        "/v1/watchlists/{list_id}/add",
        "/v1/watchlists/{list_id}/remove",
        "/v1/watchlists/{list_id}/group",
        "/v1/notebook/save",
        "/v1/notebook/create",
        "/v1/notebook/append",
        "/v1/notebook/folder",
        "/v1/notebook/rename",
        "/v1/notebook/delete",
        "/v1/notebook/vaults/add",
        "/v1/notebook/vaults/select",
        "/v1/notebook/vaults/forget",
        "/v1/market/ranges/new",
        "/v1/market/ranges/{range_id}/rename",
        "/v1/market/ranges/{range_id}/delete",
        "/v1/charting/drawings/save",
        "/v1/charting/drawings/clear",
        "/v1/charting/drawings/{drawing_id}/delete",
        # /v1/automation/workflows/*
        #                       four writes: save a version, enable/disable,
        #                       run now, delete (a tombstone version). Each
        #                       appends to `workflows.db`, which holds step
        #                       definitions and run records -- no order, size or
        #                       broker. A step can only call a capability in
        #                       `automation/grant.py` (read namespaces), and
        #                       `tests/automation/test_import_graph.py` proves
        #                       the package loads no execution or risk module.
        #                       Enable refuses any author but the operator.
        "/v1/automation/workflows/save",
        "/v1/automation/workflows/{workflow_id}/enable",
        "/v1/automation/workflows/{workflow_id}/run",
        "/v1/automation/workflows/{workflow_id}/delete",
        # /v1/news/*            three writes: collect headlines now, summarise
        #                       one article, write a brief. `news_routes.py`
        #                       imports no execution code; `news.db` holds
        #                       third-party text and a model's reading of it --
        #                       no order, size or broker. The summary prompt
        #                       forbids sizes, stops and targets, and article
        #                       text is fenced before it meets the model.
        # /v1/exec/*            THE order path (Phase 7, 2026-09-13), and the
        #                       one place in this list that reaches a broker.
        #                       Not an exception to the rule this test guards
        #                       but its structural form: no route places an
        #                       order without an approval the risk engine
        #                       issued (`/propose` -> `/place`), `/submit` does
        #                       both only in auto-within-limits, and `/mode`,
        #                       `/resume`, `/adopt` pass by="dashboard". The
        #                       orchestrator, voice and automation have no
        #                       route here -- see tests/execution/.
        # /v1/market/load       fills one series into the bar store from the
        #                       read-only data connection -- the same fetch
        #                       `genesis chart` runs. Afferent; places nothing.
        "/v1/market/load",
        # /v1/broker/*          connection settings: save the IBKR login to
        #                       ~/.genesis/.env, start/stop the gateway
        #                       container, set the feed, test and refresh the
        #                       connection. They place nothing.
        "/v1/broker/login",
        "/v1/broker/feed",
        "/v1/broker/gateway",
        "/v1/broker/test",
        "/v1/broker/refresh",
        "/v1/exec/propose",
        "/v1/exec/place",
        "/v1/exec/submit",
        "/v1/exec/modify",
        "/v1/exec/cancel",
        "/v1/exec/flatten",
        "/v1/exec/mode",
        "/v1/exec/resume",
        "/v1/exec/adopt",
        # /v1/exec/reconcile    compares the ledger with the broker's positions
        #                       and records the finding in the ledger's
        #                       reconciliation table. A POST for that audit row
        #                       only: it places nothing and cannot halt -- the
        #                       order manager owns the halt flag, so asking "do
        #                       we agree?" cannot stop trading.
        "/v1/exec/reconcile",
        # /v1/news/econ/refresh pulls the economic calendar into news.db now.
        #                       Found unenumerated on 2026-09-18; same module
        #                       and same answer as the three below -- it
        #                       imports no execution code.
        "/v1/news/econ/refresh",
        # /v1/ideas             records one of the trader's own ideas into the
        #                       research store through `record_idea`, the same
        #                       function the agent and the CLI call. Text and
        #                       prices the trader stated; no order, no size.
        "/v1/ideas",
        # /v1/plan              builds a plan of action and saves its brief to
        #                       the vault. Every size in it is the gate's
        #                       `dry_run`, which mints no approval, and each
        #                       item's ticket is only data -- acting on it is
        #                       still /v1/exec/propose then /v1/exec/place.
        "/v1/plan",
        "/v1/news/collect",
        "/v1/news/article/{article_id}/summarise",
        "/v1/news/brief",
        # /v1/journal/run       submits a task for one of five named journal
        #                       agents (`JOURNAL_RUNNABLE`) to the daemon's
        #                       bus. A fixed allow-list, no execution family,
        #                       no Trade Journal: nothing it names holds an order.
        "/v1/journal/run",
        # /v1/journal/mark      the trader's own hand: a range of candles they
        #                       selected, as an Observation and -- when they
        #                       name a trade -- appended to that entry's human
        #                       half. It cannot reach the frozen machine record
        #                       (the schema refuses machine fields and a SQLite
        #                       trigger refuses the write), so it changes no
        #                       number the Performance Analyst reasons over,
        #                       and it holds no order.
        "/v1/journal/mark",
    }


def test_the_journal_desk_refuses_anything_off_its_list(client):
    response = client.post("/v1/journal/run", json={"agent": "execution"})
    assert response.status_code == 400
    response = client.post("/v1/journal/run", json={"agent": "trade-journal"})
    assert response.status_code == 400


def test_no_route_reaches_an_order_path():
    """`Safety Invariants` #1 as a structural test, not a promise.

    There is no `place_order`. If a route ever appears whose path suggests one,
    this fails and somebody has to justify it in a review rather than in a
    commit message.
    """
    app = build_app(EventBus())
    forbidden = ("order", "trade", "position", "broker", "execute", "place")
    # Phase 7 (2026-09-13): the order path exists, in exactly one module, and
    # every placing route spends a risk-engine approval (tests/execution/).
    # The broker routes are connection settings -- login, gateway, feed -- and
    # place nothing. Anything else that looks like an order route still fails.
    efferent = {
        "/v1/exec/propose", "/v1/exec/place", "/v1/exec/submit", "/v1/exec/modify",
        "/v1/exec/cancel", "/v1/exec/flatten", "/v1/exec/mode", "/v1/exec/resume",
        "/v1/exec/adopt",
        "/v1/broker/login", "/v1/broker/feed", "/v1/broker/gateway", "/v1/broker/test",
        "/v1/broker/refresh",
    }
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any("place_order" in p or "placeorder" in p for p in paths)
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if "POST" not in methods or path in efferent:
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


# -- speech -----------------------------------------------------------------


def test_wav_header_is_well_formed():
    """Both TTS backends yield headerless PCM, which no browser will play.

    The 44-byte RIFF header is the entire difference between "Genesis answered"
    and "Genesis answered and you heard it", and it is the kind of thing that
    is either exactly right or silently produces a file that decodes to noise.
    """
    import io
    import wave

    from genesis.server.voice_routes import wav_bytes

    # Half a second of 24 kHz 16-bit silence.
    pcm = b"\x00\x00" * 12_000
    blob = wav_bytes(pcm, 24_000)

    assert blob[:4] == b"RIFF"
    assert blob[8:12] == b"WAVE"

    reader = wave.open(io.BytesIO(blob))
    try:
        assert reader.getnchannels() == 1
        assert reader.getframerate() == 24_000
        assert reader.getsampwidth() == 2
        assert reader.getnframes() == 12_000
    finally:
        reader.close()


def test_say_rejects_empty_and_oversized_text(client):
    """A reply is a sentence. Paying a vendor per character for more is the
    expensive way to discover a bug upstream."""
    from genesis.server.voice_routes import MAX_CHARS

    assert client.post("/v1/voice/say", json={"text": "   "}).status_code == 400
    assert client.post(
        "/v1/voice/say", json={"text": "a" * (MAX_CHARS + 1)}
    ).status_code == 413


def test_voice_status_reports_whether_genesis_can_speak(client):
    """Settings reads this so a missing key is visible.

    The failure mode of absent TTS is *silence*, which is indistinguishable
    from not having been heard — so it has to be stated somewhere.
    """
    body = client.get("/v1/voice/status").json()
    assert "available" in body
    assert isinstance(body.get("backends"), list)
    if not body["available"]:
        assert body["reason"], "an unavailable voice must say why"


def test_a_marked_range_is_journalled_and_refused_when_it_is_nonsense(client, tmp_path, monkeypatch):
    """The journal's one hand-authored door: a range of candles, and a note."""
    from genesis.config import load_config

    config = load_config()
    monkeypatch.setattr(
        "genesis.config.load_config",
        lambda *a, **k: config.model_copy(
            update={"memory": config.memory.model_copy(update={"db_path": tmp_path / "genesis.db"})}
        ),
    )
    mark = {"kind": "idea", "symbol": "NVDA", "timeframe": "1h",
            "start": 1_700_000_000, "end": 1_700_086_400, "note": "base on the 4h"}
    response = client.post("/v1/journal/mark", json=mark)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["mark"]["kind"] == "mark.idea"

    listed = client.get("/v1/journal/marks?symbol=NVDA").json()
    assert [m["id"] for m in listed["marks"]] == [body["mark"]["id"]]

    # A refusal says why: this is a person typing, not an agent.
    bad = client.post("/v1/journal/mark", json={**mark, "kind": "musing"})
    assert bad.status_code == 400 and "musing" in bad.json()["reason"]
