# Spec: Genesis Markdown/00-Meta/Conventions.md
"""The five recorded mutations, and the two repairs that are allowed.

Each test is one way the body map can lie. The reason they are worth testing
rather than trusting is in the module: a mis-transcribing cell does not feel
wrong, so every one of these is silent without a check — and a check nobody
tested is a check that reports honest because it looked at nothing.
"""

from __future__ import annotations

from pathlib import Path

from genesis.dna import drift, genome
from tests.dna.test_genome import source, vault


def kinds(root: Path) -> list[str]:
    return [f.kind for f in drift.check(genome.load(root))]


def test_a_cut_forward_nerve_is_found(tmp_path: Path) -> None:
    """Code points at the note; the note does not point back.

    This is how `MCP Gateway.md` sat at `status: spec` with 3,859 lines behind
    it — the organ pointed at the map and the map never answered.
    """
    root = vault(tmp_path, {"10/Thing.md": "---\nstatus: built\nimplemented_by: [src/a.py]\n---\n\n# T\n"})
    source(root, "src/a.py", "10/Thing.md")
    source(root, "src/b.py", "10/Thing.md")
    findings = drift.check(genome.load(root))
    assert [f.kind for f in findings] == ["cut-nerve"]
    assert findings[0].files == ("src/b.py",)


def test_a_phantom_limb_is_found_and_never_auto_removed(tmp_path: Path) -> None:
    """A missing file is either a deletion nobody recorded or a typo.

    Guessing which one silently is the failure the checker exists to catch, so
    repair leaves it exactly where it is.
    """
    root = vault(tmp_path, {"10/Thing.md": "---\nstatus: built\nimplemented_by: [src/gone.py]\n---\n\n# T\n"})
    assert kinds(root) == ["phantom-limb"]
    drift.repair(genome.load(root), root)
    assert kinds(root) == ["phantom-limb"]


def test_a_stale_status_is_found_in_both_directions(tmp_path: Path) -> None:
    root = vault(tmp_path, {
        "10/Claims.md": "---\nstatus: built\n---\n\n# nothing behind it\n",
        "10/Hides.md": "---\nstatus: spec\nimplemented_by: [src/a.py]\n---\n\n# code behind it\n",
    })
    source(root, "src/a.py", "10/Hides.md")
    assert kinds(root) == ["stale-status", "stale-status"]


def test_a_dangling_pointer_is_found_although_the_vault_never_sees_it(tmp_path: Path) -> None:
    """Code names a note that does not exist — a rename, or an organ written
    before its map. Walking the vault never finds it, because the vault is not
    where it is."""
    root = vault(tmp_path, {"10/Real.md": "---\nstatus: spec\n---\n\n# R\n"})
    source(root, "src/a.py", "10/Renamed Away.md")
    findings = drift.check(genome.load(root))
    assert [f.kind for f in findings] == ["dangling-pointer"]
    assert findings[0].files == ("src/a.py",)


def test_a_doubled_nerve_is_found(tmp_path: Path) -> None:
    """YAML keeps the last key, so the first list silently stops existing."""
    root = vault(tmp_path, {
        "10/Thing.md": "---\nstatus: built\nimplemented_by: [src/a.py]\nimplemented_by: [src/b.py]\n---\n\n# T\n",
    })
    source(root, "src/a.py", "10/Thing.md")
    source(root, "src/b.py", "10/Thing.md")
    assert "doubled-nerve" in kinds(root)


# ----------------------------------------------------------------------
# Repair — bounded to what the code already proves
# ----------------------------------------------------------------------


def test_repair_reconnects_a_cut_nerve_and_merges_a_doubled_key(tmp_path: Path) -> None:
    root = vault(tmp_path, {
        "10/Thing.md": "---\nstatus: built\nimplemented_by: [src/a.py]\nimplemented_by: [src/b.py]\n---\n\n# T\n",
    })
    for name in ("a", "b", "c"):
        source(root, f"src/{name}.py", "10/Thing.md")
    assert drift.repair(genome.load(root), root) == ["Genesis Markdown/10/Thing.md"]
    note = genome.load(root).resolve("Thing")
    assert set(note.implemented_by) == {"src/a.py", "src/b.py", "src/c.py"}
    assert not note.doubled
    assert kinds(root) == []


def test_repair_moves_spec_to_building_and_never_to_built(tmp_path: Path) -> None:
    """"Done" is a human judgement. The most an automatic repair may claim is
    that something has started."""
    root = vault(tmp_path, {"10/Thing.md": "---\nstatus: spec\nimplemented_by: [src/a.py]\n---\n\n# T\n"})
    source(root, "src/a.py", "10/Thing.md")
    drift.repair(genome.load(root), root)
    assert genome.load(root).resolve("Thing").status == "building"


def test_repair_will_not_touch_a_note_whose_frontmatter_never_closes(tmp_path: Path) -> None:
    """Where the frontmatter ends is a guess, and guessing silently is the
    failure this module exists to catch."""
    root = vault(tmp_path, {"10/Broken.md": "---\nstatus: spec\nimplemented_by: [src/a.py]\n\n# B\n"})
    source(root, "src/a.py", "10/Broken.md")
    before = (root / "Genesis Markdown" / "10" / "Broken.md").read_text()
    assert drift.repair(genome.load(root), root) == []
    assert (root / "Genesis Markdown" / "10" / "Broken.md").read_text() == before


def test_the_real_body_map_is_honest() -> None:
    """CLAUDE.md hard rule 6, as a test rather than a preference."""
    findings = drift.check()
    assert findings == [], [f"{f.glyph} {f.note}: {f.detail}" for f in findings]


# ----------------------------------------------------------------------
# The shapes the vault actually uses
#
# These came from `tests/test_check_body_map.py`, which tested the script
# before the logic moved into `genesis.dna`. They are kept because of how they
# were earned: the checker's first version read only the inline `[a, b]` form,
# saw nothing in a block-form note, and `--fix` appended a second
# `implemented_by:` key to fourteen notes. A repair tool damaged the thing it
# was repairing, which is the most expensive shape of bug in this package.
# ----------------------------------------------------------------------


def test_a_block_list_is_read_and_kept_as_a_block(tmp_path: Path) -> None:
    """The shape the first version could not see, and destroyed."""
    root = vault(tmp_path, {"10/A.md": "---\nstatus: building\nimplemented_by:\n  - src/a.py\n---\n\n# A\n"})
    source(root, "src/a.py", "10/A.md")
    source(root, "src/b.py", "10/A.md")
    drift.repair(genome.load(root), root)
    text = (root / "Genesis Markdown" / "10" / "A.md").read_text()
    assert text.count("implemented_by:") == 1, "the bug: a second key was appended"
    assert "  - src/a.py\n  - src/b.py\n" in text


def test_a_key_in_the_body_is_not_a_doubled_nerve(tmp_path: Path) -> None:
    """`Conventions.md` shows `implemented_by:` in a code example. That is prose."""
    root = vault(tmp_path, {
        "10/A.md": "---\nstatus: building\nimplemented_by: [src/a.py]\n---\n\n"
                   "```yaml\nimplemented_by: [example.py]\n```\n",
    })
    source(root, "src/a.py", "10/A.md")
    assert kinds(root) == []


def test_repair_never_touches_the_body(tmp_path: Path) -> None:
    root = vault(tmp_path, {
        "10/A.md": "---\nstatus: building\nimplemented_by:\n  - src/a.py\nimplemented_by: [src/b.py]\n---\n\n# Body\n\nprose\n",
    })
    for name in ("a", "b"):
        source(root, f"src/{name}.py", "10/A.md")
    drift.repair(genome.load(root), root)
    assert (root / "Genesis Markdown" / "10" / "A.md").read_text().endswith("# Body\n\nprose\n")


def test_the_pre_commit_script_still_runs_and_agrees(tmp_path: Path) -> None:
    """`scripts/check_body_map.py` is the pre-commit door to the same check.

    Run as a subprocess, because that is how it is used: a wrapper that
    imports cleanly in a test and crashes from the shell has not been tested.
    """
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[2]
    done = subprocess.run(
        [sys.executable, "scripts/check_body_map.py"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    assert done.returncode == (1 if drift.check() else 0), done.stdout + done.stderr
    assert "body map is honest" in done.stdout
