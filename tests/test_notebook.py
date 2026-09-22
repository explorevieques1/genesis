# Spec: Genesis Markdown/60-UI/Notebook.md · 60-UI/Nodes.md
"""The notebook's non-trivial logic: containment, resolution, the graph.

The containment tests are the ones that matter. A vault is a directory of the
operator's real files and every path below arrives from a browser, so a
traversal here writes anywhere they can write.
"""

from __future__ import annotations

import pytest

from genesis.errors import GenesisError
from genesis.notebook.links import LinkIndex, parse_links, parse_tags
from genesis.notebook.vault import Vault, VaultRegistry


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "GenesisVault"
    (root / "50-Research").mkdir(parents=True)
    (root / "60-Lessons").mkdir()
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}")
    (root / "50-Research" / "Gann.md").write_text(
        "Cycles. See [[Lessons]] and [[Missing note]].\n#theory\n"
    )
    (root / "60-Lessons" / "Lessons.md").write_text(
        "Drawn from [[Gann|the man]].\n\n```\nnot a [[Link]] in code\n```\n"
    )
    (root / "Orphan.md").write_text("Alone.\n")
    return Vault(root, name="Test")


# -- containment ------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../outside.md", "50-Research/../../outside.md"])
def test_traversal_is_refused(vault, bad):
    with pytest.raises(GenesisError):
        vault.resolve(bad)


def test_an_absolute_path_means_the_vault_root(vault):
    """Obsidian's reading, and the safe one: `/etc/passwd` is *in* the vault.

    Refusing it would be defensible; silently opening the real `/etc/passwd`
    would not, and that is the only outcome this test exists to forbid.
    """
    assert vault.resolve("/etc/passwd") == vault.root.resolve() / "etc/passwd"


def test_symlink_out_of_the_vault_is_refused(vault, tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text("no")
    (vault.root / "link.md").symlink_to(secret)
    with pytest.raises(GenesisError):
        vault.resolve("link.md")


def test_writes_are_markdown_only(vault):
    with pytest.raises(GenesisError):
        vault.write("shell.sh", "rm -rf /")


# -- the tree ---------------------------------------------------------------

def test_tree_is_one_level_folders_first_and_skips_machinery(vault):
    names = [(e.kind, e.name) for e in vault.tree()]
    assert names == [("folder", "50-Research"), ("folder", "60-Lessons"),
                     ("note", "Orphan")]


# -- links ------------------------------------------------------------------

def test_parse_covers_obsidian_syntax():
    refs = parse_links("[[A]] [[B#H|shown]] ![[C]] [[#Here]] `[[D]]`")
    assert [(r.target, r.anchor, r.alias, r.embed) for r in refs] == [
        ("A", "", "", False), ("B", "#H", "shown", False), ("C", "", "", True),
    ]


def test_tags_ignore_headings_and_code():
    assert parse_tags("# Heading\n#theory and #a/b\n`#nope`") == ["theory", "a/b"]


def test_resolution_and_unresolved(vault):
    index = LinkIndex(vault)
    assert index.resolve("Lessons").path == "60-Lessons/Lessons.md"
    assert index.resolve("50-Research/Gann.md").path == "50-Research/Gann.md"
    assert not index.resolve("Missing note").resolved
    assert index.unresolved() == {"Missing note": ["50-Research/Gann.md"]}


def test_ambiguity_is_reported_not_swallowed(vault):
    (vault.root / "60-Lessons" / "Gann.md").write_text("Another one.\n")
    hit = LinkIndex(vault).resolve("Gann", source="60-Lessons/Lessons.md")
    assert hit.ambiguous
    assert hit.path == "60-Lessons/Gann.md"          # nearest wins
    assert set(hit.candidates) == {"50-Research/Gann.md", "60-Lessons/Gann.md"}


def test_backlinks_are_computed_not_stored(vault):
    back = LinkIndex(vault).backlinks("50-Research/Gann.md")
    assert [b["path"] for b in back] == ["60-Lessons/Lessons.md"]
    assert "the man" in back[0]["context"]


# -- the graph --------------------------------------------------------------

def test_graph_shape(vault):
    graph = LinkIndex(vault).graph(tags=True)
    kinds = {n["id"]: n["kind"] for n in graph["nodes"]}
    assert kinds["note:50-Research/Gann.md"] == "note"
    assert kinds["unresolved:Missing note"] == "unresolved"
    assert kinds["tag:theory"] == "tag"
    assert "note:Orphan.md" in kinds
    assert {"source": "note:50-Research/Gann.md",
            "target": "note:60-Lessons/Lessons.md", "kind": "link"} in graph["edges"]


def test_filters_drop_what_they_say(vault):
    index = LinkIndex(vault)
    ids = {n["id"] for n in index.graph(unresolved=False, orphans=False)["nodes"]}
    assert "unresolved:Missing note" not in ids
    assert "note:Orphan.md" not in ids


def test_local_graph_is_depth_limited(vault):
    (vault.root / "Far.md").write_text("[[Orphan]]\n")
    ids = {n["id"] for n in
           LinkIndex(vault).graph(focus="60-Lessons/Lessons.md", depth=1)["nodes"]}
    assert ids == {"note:60-Lessons/Lessons.md", "note:50-Research/Gann.md"}


# -- writing ----------------------------------------------------------------

def test_creating_a_note_resolves_the_link_that_asked_for_it(vault):
    vault.create("50-Research/Missing note.md", "Now it exists.\n")
    assert LinkIndex(vault).resolve("Missing note").resolved


def test_create_refuses_to_clobber(vault):
    with pytest.raises(GenesisError):
        vault.create("Orphan.md")


def test_append_creates_the_daily_note(vault):
    note = vault.append(vault.daily_path(), "- 09:15 — NVDA heavy")
    assert note.path.startswith("00-Inbox/")
    assert "NVDA heavy" in vault.read(note.path).body


def test_rename_previews_then_rewrites_links(vault):
    index = LinkIndex(vault)
    preview = index.rename_preview("50-Research/Gann.md", "50-Research/W D Gann.md")
    assert preview == [{"path": "60-Lessons/Lessons.md", "name": "Lessons",
                        "count": 1, "to": "W D Gann"}]
    moved = vault.move("50-Research/Gann.md", "50-Research/W D Gann.md")
    assert index.rewrite_links("50-Research/Gann.md", moved) == 1
    # The alias is the writer's own words and survives untouched.
    assert "[[W D Gann|the man]]" in vault.read("60-Lessons/Lessons.md").body


def test_delete_refuses_a_full_folder(vault):
    with pytest.raises(GenesisError):
        vault.delete("50-Research")


# -- the registry -----------------------------------------------------------

def test_registry_seeds_from_config_default_and_never_deletes(tmp_path):
    default = tmp_path / "GenesisVault"
    default.mkdir()
    registry = VaultRegistry(tmp_path / "vaults.json", default=default)
    assert registry.active().path == default

    other = tmp_path / "Ideas"
    registry.add("Ideas", other)
    assert registry.active().name == "Ideas"
    registry.forget("Ideas")
    assert other.is_dir()                        # forgotten, not deleted
    assert [v.name for v in registry.list()] == ["GenesisVault"]


# -- the routes -------------------------------------------------------------

@pytest.fixture
def client(vault, tmp_path, monkeypatch):
    """The real app, with the registry pointed at the fixture vault.

    Only `registry` is patched — every route below goes through the same
    `Vault.resolve`, the same index, and the same guard the daemon uses.
    """
    from starlette import testclient

    from genesis.notebook.vault import VaultRegistry
    from genesis.server.app import EventBus, build_app

    registry = VaultRegistry(tmp_path / "vaults.json", default=vault.root)
    monkeypatch.setattr("genesis.notebook.vault.registry", lambda: registry)
    with testclient.TestClient(build_app(EventBus())) as c:
        yield c


def test_routes_read_the_vault(client):
    tree = client.get("/v1/notebook/tree").json()
    assert tree["available"] is True
    assert [e["name"] for e in tree["entries"]] == ["50-Research", "60-Lessons", "Orphan"]

    note = client.get("/v1/notebook/note?path=50-Research/Gann.md").json()
    assert note["note"]["name"] == "Gann"
    assert [(l["target"], l["resolved"]) for l in note["links"]] == [
        ("Lessons", "60-Lessons/Lessons.md"), ("Missing note", None),
    ]
    assert [b["path"] for b in note["backlinks"]] == ["60-Lessons/Lessons.md"]

    graph = client.get("/v1/notebook/graph?tags=true").json()
    assert graph["notes"] == 3
    assert any(n["kind"] == "unresolved" for n in graph["nodes"])


def test_the_link_click_loop_over_http(client):
    """Write `[[X]]`, click it, and X exists — the whole authoring loop."""
    assert client.post("/v1/notebook/save", json={
        "path": "Ideas.md", "body": "Watch [[Semis]].\n",
    }).json()["ok"]

    before = client.get("/v1/notebook/note?path=Ideas.md").json()
    assert before["links"][0]["resolved"] is None

    assert client.post("/v1/notebook/create", json={
        "path": "Semis.md", "body": "# Semis\n",
    }).json()["ok"]

    after = client.get("/v1/notebook/note?path=Ideas.md").json()
    assert after["links"][0]["resolved"] == "Semis.md"


def test_a_traversal_over_http_is_refused_not_served(client):
    body = client.post("/v1/notebook/save", json={
        "path": "../escaped.md", "body": "no",
    })
    assert body.status_code == 400
    assert "escapes the vault" in body.json()["reason"]
