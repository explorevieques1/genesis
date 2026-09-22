# Spec: Genesis Markdown/00-Meta/Conventions.md
"""The genome reader, against a vault built for the test.

A miniature vault rather than the real one: the checks here are about the
*rules* — which frontmatter spellings parse, which collisions resolve which way
— and a test that asserts those against 220 real notes fails every time
somebody writes a note. The real vault gets one test, at the bottom, and it
asserts only what must never stop being true of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genesis.dna import drift, genome


def vault(tmp_path: Path, notes: dict[str, str]) -> Path:
    """A repo with a vault in it. Keys are vault-relative paths."""
    for rel, text in notes.items():
        path = tmp_path / "Genesis Markdown" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def source(root: Path, rel: str, spec: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Spec: {spec}\nx = 1\n", encoding="utf-8")


# ----------------------------------------------------------------------
# Frontmatter — both spellings of a list, because both are in the vault
# ----------------------------------------------------------------------


def test_both_spellings_of_implemented_by_are_read(tmp_path: Path) -> None:
    """Inline `[a, b]` and the block form are one key with two spellings.

    Reading only one of them reports every note using the other as an organ
    with nothing behind it — a reader that lies about the map it is reading.
    """
    root = vault(tmp_path, {
        "10/Inline.md": "---\nstatus: built\nimplemented_by: [a.py, b.py]\n---\n\n# Inline\n",
        "10/Block.md": "---\nstatus: built\nimplemented_by:\n  - a.py\n  - b.py\n---\n\n# Block\n",
    })
    g = genome.load(root)
    assert g.resolve("Inline").implemented_by == ("a.py", "b.py")
    assert g.resolve("Block").implemented_by == ("a.py", "b.py")


def test_frontmatter_that_never_closes_is_flagged_not_skipped(tmp_path: Path) -> None:
    """`Workspaces.md` sat in this state and four separate tools skipped it.

    Opened and never closed reads, to every frontmatter parser, as a note with
    no frontmatter at all — so its status and its `implemented_by` silently
    stop existing. The one thing that must not happen is what used to: nothing
    said anything.
    """
    root = vault(tmp_path, {
        "10/Broken.md": "---\nstatus: built\nimplemented_by: [a.py]\n\n# Broken\n",
        "10/Prose.md": "# Just prose, no frontmatter at all\n",
    })
    g = genome.load(root)
    assert g.resolve("Broken").frontmatter_ok is False
    # Prose was never claiming to have frontmatter, so it is not drift.
    assert g.resolve("Prose").frontmatter_ok is True

    findings = drift.check(g)
    assert [f.kind for f in findings] == ["broken-frontmatter"]
    assert "closing" in findings[0].detail


def test_a_broken_note_reports_once_not_three_times(tmp_path: Path) -> None:
    """Everything else about it is read off frontmatter no parser can see."""
    root = vault(tmp_path, {"10/Broken.md": "---\nstatus: spec\n\n# Broken\n"})
    source(root, "src/x.py", "10/Broken.md")
    findings = drift.check(genome.load(root))
    assert len(findings) == 1, [f.kind for f in findings]


# ----------------------------------------------------------------------
# Resolution
# ----------------------------------------------------------------------


def test_on_a_name_collision_the_most_nested_note_wins(tmp_path: Path) -> None:
    """A stray file at the vault root must not shadow the note in its section."""
    root = vault(tmp_path, {
        "Voice Stack.md": "---\nstatus: spec\n---\n\n# stray copy\n",
        "10-Architecture/Voice Stack.md": "---\nstatus: built\n---\n\n# the real one\n",
    })
    g = genome.load(root)
    assert g.resolve("Voice Stack").status == "built"
    assert "Voice Stack" in g.collisions()


def test_a_spec_pointer_resolves_in_all_three_spellings(tmp_path: Path) -> None:
    """Repo-relative, vault-relative and a bare name are all in use."""
    root = vault(tmp_path, {"40-Memory/Thing.md": "---\nstatus: built\n---\n\n# Thing\n"})
    source(root, "src/a.py", "Genesis Markdown/40-Memory/Thing.md")
    source(root, "src/b.py", "40-Memory/Thing.md")
    source(root, "src/c.py", "Thing.md")
    g = genome.load(root)
    assert set(g.pointing_at(g.resolve("Thing"))) == {"src/a.py", "src/b.py", "src/c.py"}


def test_one_pointer_may_name_several_notes(tmp_path: Path) -> None:
    """`# Spec: 60-UI/Workspaces.md · 60-UI/Terminal.md` — the vault's own separator."""
    root = vault(tmp_path, {
        "60-UI/One.md": "---\nstatus: built\n---\n\n# One\n",
        "60-UI/Two.md": "---\nstatus: built\n---\n\n# Two\n",
    })
    source(root, "src/a.py", "Genesis Markdown/60-UI/One.md · 60-UI/Two.md")
    g = genome.load(root)
    assert g.pointing_at(g.resolve("One")) == ("src/a.py",)
    assert g.pointing_at(g.resolve("Two")) == ("src/a.py",)


def test_a_mention_further_down_a_file_is_not_a_claim_to_implement(tmp_path: Path) -> None:
    """The pointer is a header. Prose about another note's spec is prose."""
    root = vault(tmp_path, {"10/Thing.md": "---\nstatus: spec\n---\n\n# Thing\n"})
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n" * 60 + "# Spec: 10/Thing.md\n", encoding="utf-8")
    g = genome.load(root)
    assert g.pointing_at(g.resolve("Thing")) == ()


# ----------------------------------------------------------------------
# The real genome — only what must never stop being true
# ----------------------------------------------------------------------


def test_the_real_vault_reads(tmp_path: Path) -> None:
    g = genome.load()
    assert len(g.notes) > 150
    assert g.resolve("Safety Invariants") is not None
    assert g.resolve("Biological Design") is not None
    assert sum(g.counts().values()) == len(g.notes)


def test_every_note_in_the_real_vault_has_closeable_frontmatter() -> None:
    """The bug this module was written to find, kept found."""
    broken = [n.rel for n in genome.load().notes if not n.frontmatter_ok]
    assert broken == [], broken


def test_the_route_serves_the_same_genome_the_cli_reads() -> None:
    """Parity, asserted rather than assumed.

    Operating Model §1: the panel and the terminal go through the same door.
    A route that read the vault its own way could show an honest body map
    while `genesis dna check` showed a drifting one, and the operator would
    have no way to know which to believe.
    """
    from starlette import testclient

    from genesis.server.app import EventBus, build_app

    with testclient.TestClient(build_app(EventBus())) as client:
        body = client.get("/v1/dna").json()

    g = genome.load()
    assert body["available"] is True
    assert body["counts"] == g.counts()
    assert body["honest"] is (drift.check(g) == [])
    assert sum(len(s["notes"]) for s in body["sections"]) == len(g.notes)
    assert body["prompts"], "the prompt half of the genome is missing from the route"
