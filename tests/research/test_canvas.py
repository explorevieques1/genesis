# Spec: Genesis Markdown/60-UI/Research Canvas.md · 40-Memory/Knowledge Graph.md
"""The canvas and the graph under it.

What these pin down is the set of properties that would each produce a canvas
that *looks* right and is wrong: a node that duplicates content instead of
referencing it, an edge nobody asserted, a line that only one browser knows
about, an arrangement an agent silently undid, and a "delete" that threw away
what the system learned along with the picture of it.
"""

from __future__ import annotations

import pytest

from genesis.errors import FatalError, GenesisError
from genesis.memory.graph import EDGE_KINDS, ENTITY_TYPES, KnowledgeGraph
from genesis.research.canvas import OPERATOR, CanvasStore
from genesis.research.schema import ResearchNote, Source
from genesis.research.store import ResearchStore


@pytest.fixture
def graph(tmp_path) -> KnowledgeGraph:
    return KnowledgeGraph(path=tmp_path / "graph.db")


@pytest.fixture
def canvas(tmp_path, graph) -> CanvasStore:
    return CanvasStore(path=tmp_path / "canvas.db", graph=graph)


@pytest.fixture
def research(tmp_path, graph) -> ResearchStore:
    return ResearchStore(path=tmp_path / "research.db", vault=None, graph=graph)


def _note(**over):
    base = dict(
        id="res_1", kind="topic", title="W.D. Gann", subject="wd-gann",
        created_by="topic-researcher", summary="Time and price.",
        body="## Claim\n\nSquare of nine.",
        sources=[Source(url="https://a.test/g", title="Gann primer")],
    )
    base.update(over)
    return ResearchNote(**base)


# ---------------------------------------------------------------------------
# the graph


def test_entities_and_edges_are_typed_and_untyped_writes_are_refused(graph):
    """Typing is what makes the graph answerable rather than merely connected."""
    a = graph.upsert("thesis", "gann", label="Gann", namespace="topic-researcher")
    b = graph.upsert("document", "https://a.test", label="page", namespace="topic-researcher")
    graph.link(a.id, "derived_from", b.id, namespace="topic-researcher")

    with pytest.raises(FatalError, match="unknown entity type"):
        graph.upsert("planet", "mars", label="Mars", namespace="x")
    with pytest.raises(FatalError, match="unknown edge kind"):
        graph.link(a.id, "reminds_me_of", b.id, namespace="x")

    assert set(ENTITY_TYPES) >= {"symbol", "level", "idea", "thesis", "lesson", "document"}
    assert "derived_from" in EDGE_KINDS


def test_an_edge_to_a_node_that_does_not_exist_is_refused(graph):
    """A dangling edge renders as a line into nothing and answers with a hole."""
    a = graph.upsert("thesis", "gann", label="Gann", namespace="who")
    with pytest.raises(FatalError, match="do not exist"):
        graph.link(a.id, "mentions", "symbol:NOPE", namespace="who")
    assert graph.edges_of(a.id) == []


def test_writes_are_idempotent_so_one_thing_is_one_node(graph):
    for _ in range(3):
        graph.upsert("symbol", "NVDA", label="NVDA", namespace="shared")
    assert len(graph.entities(type_="symbol")) == 1


def test_a_superseded_fact_leaves_retrieval_but_keeps_its_history(graph):
    old = graph.upsert("thesis", "gann", label="Gann v1", namespace="who")
    new = graph.upsert("thesis", "gann-2", label="Gann v2", namespace="who")
    graph.supersede(old.id, new.id, namespace="who")

    live = {e.id for e in graph.entities()}
    assert old.id not in live and new.id in live
    assert graph.entity(old.id).superseded_by == new.id
    assert {e.id for e in graph.entities(include_superseded=True)} == {old.id, new.id}
    assert any(e.kind == "supersedes" for e in graph.edges_of(new.id))


def test_expansion_is_bounded_by_depth_and_by_limit(graph):
    hub = graph.upsert("symbol", "NVDA", label="NVDA", namespace="shared")
    for i in range(10):
        leaf = graph.upsert("document", f"https://a.test/{i}", label=f"d{i}", namespace="who")
        graph.link(leaf.id, "mentions", hub.id, namespace="who")

    nodes, _ = graph.subgraph([hub.id], depth=0)
    assert len(nodes) == 1, "depth 0 is the seed alone"
    nodes, _ = graph.subgraph([hub.id], depth=1, limit=4)
    assert len(nodes) == 4, "the limit is honoured"
    nodes, edges = graph.subgraph([hub.id], depth=1)
    assert len(nodes) == 11
    assert all(e.src in {n.id for n in nodes} and e.dst in {n.id for n in nodes}
               for e in edges), "no edge points off the returned set"


# ---------------------------------------------------------------------------
# the projection: research becomes graph


def test_a_saved_note_becomes_a_referenced_node_not_a_copy(research, graph):
    note = research.put(_note(), mirror=False)

    entity = graph.entity("thesis:wd-gann")
    assert entity is not None
    assert entity.ref == note.id, "the node points at the note"
    assert "Square of nine" not in str(entity.data), "content is not copied in"
    assert entity.namespace == "topic-researcher"

    # Its cited source is a node, and the citation is a recorded edge.
    doc = graph.entity("document:https://a.test/g")
    assert doc is not None and doc.label == "Gann primer"
    kinds = {e.kind for e in graph.edges_of(entity.id)}
    assert kinds == {"derived_from"}


def test_an_idea_links_to_its_symbol_and_to_the_notes_it_cited(research, graph):
    research.put(_note(), mirror=False)
    research.put(
        _note(
            id="res_idea", kind="idea", title="NVDA long", subject="nvda",
            created_by="idea-synthesizer", sources=[],
            data={"symbol": "NVDA", "evidence": ["res_1"]},
        ),
        mirror=False,
    )
    idea = graph.entity("idea:nvda")
    assert idea is not None
    targets = {(e.kind, e.dst) for e in graph.edges_of(idea.id) if e.src == idea.id}
    assert ("applies_to", "symbol:NVDA") in targets
    assert ("derived_from", "thesis:wd-gann") in targets


def test_a_graph_that_will_not_write_does_not_fail_the_research(tmp_path):
    """The note is already committed; a broken graph is a caveat, not a loss."""
    class Broken:
        def upsert(self, *a, **k):
            raise RuntimeError("disk is on fire")

    store = ResearchStore(path=tmp_path / "r.db", vault=None, graph=Broken())
    note = store.put(_note(), mirror=False)
    assert store.note(note.id) is not None
    assert any("knowledge graph" in m for m in store.mirror_notes)


def test_backfill_is_idempotent(research, graph):
    research.put(_note(), mirror=False)
    assert research.backfill() == 1
    research.backfill()
    assert len(graph.entities(type_="thesis")) == 1


# ---------------------------------------------------------------------------
# the canvas


def test_open_for_seeds_from_the_graph_and_leaves_the_rest_alone(research, canvas, graph):
    research.put(_note(), mirror=False)
    graph.upsert("symbol", "TSLA", label="TSLA", namespace="shared")

    cid = canvas.open_for("Gann", created_by="orchestrator")
    view = canvas.view(cid).to_dict()
    ids = {n["id"] for n in view["nodes"]}

    assert "thesis:wd-gann" in ids
    assert "document:https://a.test/g" in ids, "one hop reaches the cited source"
    assert "symbol:TSLA" not in ids, "an unrelated entity is not dragged in"
    assert view["edges"], "the recorded citation is drawn"


def test_a_canvas_with_no_matches_still_exists_and_says_so(canvas):
    """An empty canvas is an answer. Returning nothing looks like a broken button."""
    cid = canvas.open_for("nothing at all matches this")
    view = canvas.view(cid).to_dict()
    assert view["id"] == cid and view["nodes"] == []
    assert view["query"] == "nothing at all matches this"


def test_a_node_with_nothing_behind_it_cannot_be_placed(canvas):
    cid = canvas.create("board")
    with pytest.raises(FatalError, match="not in the knowledge graph"):
        canvas.add(cid, ["symbol:GHOST"])
    assert canvas.nodes(cid) == []


def test_a_dragged_node_is_pinned_and_survives_an_agent_adding_one(research, canvas, graph):
    """The arrangement is shared, so an agent must not undo what a person did."""
    research.put(_note(), mirror=False)
    cid = canvas.open_for("Gann")
    canvas.move(cid, "thesis:wd-gann", 111.0, 222.0)

    later = graph.upsert("symbol", "NVDA", label="NVDA", namespace="shared")
    canvas.add(cid, [later.id], by="market-analyst")

    placed = {n.entity: n for n in canvas.nodes(cid)}
    assert (placed["thesis:wd-gann"].x, placed["thesis:wd-gann"].y) == (111.0, 222.0)
    assert placed["thesis:wd-gann"].pinned
    assert placed[later.id].added_by == "market-analyst"
    # And the newcomer was actually placed somewhere, not stacked at the origin
    # on top of everything else.
    assert (placed[later.id].x, placed[later.id].y) != (0.0, 0.0)


def test_a_line_drawn_by_hand_is_a_graph_edge_under_the_operators_name(research, canvas, graph):
    """Not a canvas-local decoration: a claim every agent can later read."""
    research.put(_note(), mirror=False)
    cid = canvas.open_for("Gann")
    canvas.assert_edge("document:https://a.test/g", "confirms", "thesis:wd-gann")

    edge = next(e for e in graph.edges_of("thesis:wd-gann", kinds=["confirms"]))
    assert edge.namespace == OPERATOR
    assert any(e["kind"] == "confirms" for e in canvas.view(cid).to_dict()["edges"])


def test_a_line_you_drew_you_may_undraw(research, canvas, graph):
    research.put(_note(), mirror=False)
    canvas.open_for("Gann")
    canvas.assert_edge("document:https://a.test/g", "confirms", "thesis:wd-gann")

    canvas.retract_edge("document:https://a.test/g", "confirms", "thesis:wd-gann")
    assert not graph.edges_of("thesis:wd-gann", kinds=["confirms"])
    # The retraction removes the claim, not the things it was about.
    assert graph.entity("thesis:wd-gann") is not None


def test_a_line_an_agent_drew_you_may_not(research, canvas, graph):
    """An agent's edge is provenance it observed. A drag must not delete it."""
    research.put(_note(), mirror=False)
    canvas.open_for("Gann")
    before = graph.edges_of("thesis:wd-gann", kinds=["derived_from"])
    assert before and before[0].namespace != OPERATOR

    with pytest.raises(FatalError) as refused:
        canvas.retract_edge(
            "thesis:wd-gann", "derived_from", "document:https://a.test/g"
        )
    assert before[0].namespace in str(refused.value)
    assert graph.edges_of("thesis:wd-gann", kinds=["derived_from"]) == before


def test_deleting_a_canvas_keeps_what_genesis_learned(research, canvas, graph):
    research.put(_note(), mirror=False)
    cid = canvas.open_for("Gann")
    canvas.delete(cid)

    assert canvas.list() == []
    assert graph.entity("thesis:wd-gann") is not None
    assert graph.edges_of("thesis:wd-gann"), "the citations survive the arrangement"


def test_the_view_never_draws_an_edge_to_a_node_that_is_not_shown(research, canvas):
    research.put(_note(), mirror=False)
    cid = canvas.open_for("Gann")
    canvas.remove(cid, ["document:https://a.test/g"])

    view = canvas.view(cid).to_dict()
    shown = {n["id"] for n in view["nodes"]}
    assert all(e["source"] in shown and e["target"] in shown for e in view["edges"])


# ---------------------------------------------------------------------------
# the surface


def test_the_canvas_routes_read_and_write_the_same_object(tmp_path, monkeypatch):
    tc = pytest.importorskip("starlette.testclient")
    from genesis.server.app import EventBus, build_app

    graph = KnowledgeGraph(path=tmp_path / "graph.db")
    research = ResearchStore(path=tmp_path / "research.db", vault=None, graph=graph)
    research.put(_note(), mirror=False)
    monkeypatch.setattr(
        "genesis.server.canvas_routes._store",
        lambda: CanvasStore(path=tmp_path / "canvas.db", graph=graph),
    )

    with tc.TestClient(build_app(EventBus())) as client:
        made = client.post("/v1/canvas/new", json={"query": "Gann"}).json()
        assert made["ok"]
        cid = made["canvas"]["id"]
        thesis = next(n for n in made["canvas"]["nodes"] if n["type"] == "thesis")
        doc = next(n for n in made["canvas"]["nodes"] if n["type"] == "document")

        # A node carries a reference the UI can follow, not the note's body.
        assert thesis["ref"] == "res_1" and "body" not in thesis

        assert client.post(f"/v1/canvas/{cid}/move", json={
            "entity": thesis["id"], "x": 5.0, "y": 6.0}).json()["ok"]
        back = client.get(f"/v1/canvas/{cid}").json()["canvas"]
        moved = next(n for n in back["nodes"] if n["id"] == thesis["id"])
        assert (moved["x"], moved["y"], moved["pinned"]) == (5.0, 6.0, True)

        linked = client.post(f"/v1/canvas/{cid}/link", json={
            "source": doc["id"], "kind": "confirms", "target": thesis["id"]}).json()
        assert linked["edge"]["namespace"] == OPERATOR

        # Refusals are stated, never a 500 and never silence.
        bad = client.post(f"/v1/canvas/{cid}/link", json={
            "source": doc["id"], "kind": "vibes_with", "target": thesis["id"]})
        assert bad.status_code == 400 and "unknown edge kind" in bad.json()["reason"]

        ghost = client.post(f"/v1/canvas/{cid}/add", json={"entities": ["symbol:GHOST"]})
        assert ghost.status_code == 400 and "knowledge graph" in ghost.json()["reason"]

        cut = client.post(f"/v1/canvas/{cid}/unlink", json={
            "source": doc["id"], "kind": "confirms", "target": thesis["id"]}).json()
        assert cut["ok"] and not any(
            e["kind"] == "confirms" for e in cut["canvas"]["edges"])

        # And an agent's line is refused with its reason, not silently ignored.
        agents = client.post(f"/v1/canvas/{cid}/unlink", json={
            "source": thesis["id"], "kind": "derived_from", "target": doc["id"]})
        assert agents.status_code == 400
        assert "not you" in agents.json()["reason"]

        listing = client.get("/v1/canvas").json()
        assert listing["graph"]["thesis"] == 1
        assert client.post(f"/v1/canvas/{cid}/delete", json={}).json()["ok"]


def test_the_canvas_command_opens_one_and_says_what_is_on_it(tmp_path, monkeypatch):
    """"Show me what you found on Gann" — deterministic, no model involved."""
    from genesis import commands
    from genesis.commands import dispatch

    graph = KnowledgeGraph(path=tmp_path / "graph.db")
    research = ResearchStore(path=tmp_path / "research.db", vault=None, graph=graph)
    research.put(_note(), mirror=False)

    class Memory:
        db_path = tmp_path / "genesis.db"

    class Cfg:
        memory = Memory()

    monkeypatch.setattr("genesis.config.load_config", lambda *a, **k: Cfg())

    result = dispatch("show me what you found on Gann")
    assert result.ok and result.command == "canvas"
    assert "thesis" in result.spoken and "document" in result.spoken
    # The id is what lets the shell put the panel on screen.
    assert result.data["canvas_id"].startswith("cv_")
    assert result.data["nodes"] == "2"


def test_an_empty_canvas_command_is_an_answer_not_a_silence(tmp_path, monkeypatch):
    from genesis.commands import dispatch

    class Memory:
        db_path = tmp_path / "genesis.db"

    class Cfg:
        memory = Memory()

    monkeypatch.setattr("genesis.config.load_config", lambda *a, **k: Cfg())

    result = dispatch("what do you know about cabbage futures")
    assert result.ok, "an empty graph is not a failure"
    assert "nothing on cabbage futures" in result.spoken.lower()
    assert result.data["nodes"] == "0"
    # The canvas still exists, so the difference between "nobody researched
    # this" and "the button is broken" is visible.
    assert result.data["canvas_id"].startswith("cv_")
