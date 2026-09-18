# Spec: Genesis Markdown/10-Architecture/Biological Design.md §Interoception
"""The body-map checker. It writes to the vault, and its first version damaged it.

Yesterday's first cut read only the inline `[a, b]` form, saw nothing in a
block-form note, and `--fix` appended a second `implemented_by:` key to
fourteen notes. These tests pin every shape the vault actually uses.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_body_map.py"


@pytest.fixture()
def checker(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_body_map", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    (tmp_path / "Genesis Markdown").mkdir()
    (tmp_path / "src").mkdir()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "VAULT", tmp_path / "Genesis Markdown")

    def run(*argv: str) -> int:
        monkeypatch.setattr(sys, "argv", ["check_body_map.py", *argv])
        return mod.main()

    return tmp_path, run


def note(root: Path, name: str, frontmatter: str, body: str = "# Body\n\nprose\n") -> Path:
    path = root / "Genesis Markdown" / f"{name}.md"
    path.write_text(f"---\ntitle: {name}\n{frontmatter}---\n\n{body}", encoding="utf-8")
    return path


def code(root: Path, rel: str, *notes: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    pointer = " · ".join([f"Genesis Markdown/{notes[0]}.md", *(f"{n}.md" for n in notes[1:])])
    path.write_text(f"# Spec: {pointer}\n", encoding="utf-8")


def test_an_honest_map_passes(checker) -> None:
    root, run = checker
    note(root, "A", "status: building\nimplemented_by: [src/a.py]\n")
    code(root, "src/a.py", "A")
    assert run() == 0


def test_a_cut_nerve_is_found_and_fixed_inline(checker) -> None:
    root, run = checker
    path = note(root, "A", "status: spec\nimplemented_by: []\n")
    code(root, "src/a.py", "A")
    assert run() == 1
    run("--fix")
    assert run() == 0
    assert "implemented_by: [src/a.py]" in path.read_text()
    assert "status: building" in path.read_text()


def test_a_block_list_is_read_and_kept_as_a_block(checker) -> None:
    """The shape the first version could not see."""
    root, run = checker
    path = note(root, "A", "status: building\nimplemented_by:\n  - src/a.py\n")
    code(root, "src/a.py", "A")
    code(root, "src/b.py", "A")
    assert run() == 1
    run("--fix")
    text = path.read_text()
    assert text.count("implemented_by:") == 1, "the bug: a second key was appended"
    assert "  - src/a.py\n  - src/b.py\n" in text


def test_a_doubled_key_is_found_and_merged_without_loss(checker) -> None:
    root, run = checker
    path = note(root, "A", "status: building\nimplemented_by:\n  - src/a.py\n"
                           "implemented_by: [src/b.py]\n")
    code(root, "src/a.py", "A")
    code(root, "src/b.py", "A")
    assert run() == 1
    run("--fix")
    text = path.read_text()
    assert text.count("implemented_by:") == 1
    assert "src/a.py" in text and "src/b.py" in text
    assert text.endswith("# Body\n\nprose\n"), "the body is never touched"
    assert run() == 0


def test_one_pointer_may_name_several_notes(checker) -> None:
    root, run = checker
    a = note(root, "A", "status: spec\nimplemented_by: []\n")
    b = note(root, "B", "status: spec\nimplemented_by: []\n")
    code(root, "src/ab.ts", "A", "B")
    run("--fix")
    assert "src/ab.ts" in a.read_text() and "src/ab.ts" in b.read_text()


def test_a_phantom_limb_is_reported_and_never_auto_removed(checker) -> None:
    root, run = checker
    path = note(root, "A", "status: building\nimplemented_by: [src/gone.py]\n")
    assert run() == 1
    run("--fix")
    assert "src/gone.py" in path.read_text(), "a missing file is a question, not a deletion"
    assert run() == 1


def test_a_key_in_the_body_is_not_a_doubled_nerve(checker) -> None:
    """Conventions.md shows `implemented_by:` in a code example. That is prose."""
    root, run = checker
    note(root, "A", "status: building\nimplemented_by: [src/a.py]\n",
         body="```yaml\nimplemented_by: [example.py]\n```\n")
    code(root, "src/a.py", "A")
    assert run() == 0


def test_a_pointer_to_a_note_that_does_not_exist_is_drift(checker) -> None:
    """Code written before its map, or a note renamed out from under it."""
    root, run = checker
    code(root, "src/orphan.py", "Never Written")
    assert run() == 1


def test_a_bare_note_name_resolves_because_names_are_unique(checker) -> None:
    root, run = checker
    sub = root / "Genesis Markdown" / "20-Agents"
    sub.mkdir()
    (sub / "Deep.md").write_text("---\ntitle: Deep\nstatus: building\nimplemented_by: [src/x.ts]\n---\n")
    (root / "src" / "x.ts").write_text("// Spec: Genesis Markdown/20-Agents/Deep.md · Deep.md\n")
    assert run() == 0
