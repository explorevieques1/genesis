# Spec: Genesis Markdown/00-Meta/Conventions.md
"""The genome: every note, its status, and the code transcribed from it.

One genome, read once, passed around. Before this module the same frontmatter
was parsed in four places -- ``scripts/check_body_map.py``,
``scripts/build_vault_map.py``, ``scripts/add_status_frontmatter.py`` and
``genesis.biology`` -- each with its own regexes and its own idea of what an
``implemented_by:`` looks like. Four readings of one genome is how the readings
disagree, and a body map that disagrees with itself is worse than none.

**Afferent only.** Nothing here writes to the vault. Reading the genome is
cheap, safe and parallel; changing it is a human editing a note and committing
it. That asymmetry is not an oversight -- an organism that can rewrite its own
spec at runtime can rewrite `Safety Invariants.md`, and every reflex in the
system becomes negotiable. Repair lives in :mod:`genesis.dna.drift`, is never
called by the daemon, and only ever writes what the code already proves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = ["Genome", "Note", "REPO", "VAULT", "load"]

REPO = Path(__file__).resolve().parents[3]
VAULT = REPO / "Genesis Markdown"

#: Where a spec pointer may live. Conventions puts it on line 1 of every source
#: file; the UI carries the same pointer in a `//` comment.
SOURCE_DIRS = ("src", "ui/src", "scripts", "tests", "evals")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".sh", ".yaml"}

_FM = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)
_STATUS = re.compile(r"^status:\s*(\S+)", re.MULTILINE)
_TITLE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
#: Both spellings of a YAML list, because both are in the vault: the inline
#: `[a, b]` the notes mostly use and the block form `- a` on following lines.
#: Parsing only one of them reports every note using the other as an organ with
#: nothing behind it -- a reader that lies about the map it is reading.
_IMPL_INLINE = re.compile(r"^implemented_by:\s*(\[.*?\])\s*$", re.MULTILINE | re.DOTALL)
_IMPL_BLOCK = re.compile(r"^implemented_by:\s*$\n((?:[ \t]*-[ \t]*\S.*\n)+)", re.MULTILINE)
_IMPL_KEY = re.compile(r"^implemented_by:", re.MULTILINE)
_POINTER = re.compile(r"^(?:#|//|--)\s*Spec:\s*(.+?)\s*$", re.MULTILINE)
_LINK = re.compile(r"\[\[([^\]|#]+)")

#: The three a note may carry. `spec | building | built` also appears in
#: Conventions as a *template line*, which is why membership is checked rather
#: than truthiness -- a note that is not a component has no status at all.
STATUSES = ("spec", "building", "built")


@dataclass(frozen=True)
class Note:
    """One gene: a note, what it says about itself, and where it sits."""

    name: str
    path: Path
    rel: str
    section: str
    title: str
    status: str
    implemented_by: tuple[str, ...]
    links: tuple[str, ...]
    #: Two `implemented_by:` keys in one frontmatter. YAML keeps the last, so
    #: the first list silently stops existing.
    doubled: bool
    #: False when the note opens `---` and never closes it. Every frontmatter
    #: reader -- Obsidian's properties pane included -- then treats the note as
    #: having no frontmatter at all, so its status and its `implemented_by:`
    #: stop existing without anything saying so. `Workspaces.md` was in this
    #: state and four separate tools skipped it in silence.
    frontmatter_ok: bool = True

    @property
    def depth(self) -> int:
        return len(self.path.parts)


@dataclass(frozen=True)
class Genome:
    """The whole instruction set, read once.

    ``pointers`` is the transcription record in the code-to-note direction:
    an absolute note path (existing or not) mapped to the source files whose
    first lines name it. Unresolvable targets are kept rather than dropped --
    a pointer at a note that does not exist is drift, and a reader that
    silently discarded it would be the reason nobody ever noticed.
    """

    notes: tuple[Note, ...]
    pointers: dict[Path, tuple[str, ...]]
    root: Path

    # -- lookup --------------------------------------------------------

    def resolve(self, name: str) -> Note | None:
        """A note by name. On a collision the most nested one wins.

        A stray file at the vault root -- a pasted chat, a scratch note --
        must not shadow the note in its section. This is the same rule
        :mod:`genesis.biology` used to implement privately.
        """
        found = [n for n in self.notes if n.name == name.strip()]
        if not found:
            return None
        return max(found, key=lambda n: n.depth)

    def collisions(self) -> dict[str, tuple[Note, ...]]:
        """Names that resolve two ways, so `[[link]]` is ambiguous."""
        seen: dict[str, list[Note]] = {}
        for note in self.notes:
            seen.setdefault(note.name, []).append(note)
        return {k: tuple(v) for k, v in sorted(seen.items()) if len(v) > 1}

    def pointing_at(self, note: Note) -> tuple[str, ...]:
        return self.pointers.get(note.path, ())

    def counts(self) -> dict[str, int]:
        """How much of the genome is expressed, by status."""
        out = {s: 0 for s in STATUSES}
        out["none"] = 0
        for note in self.notes:
            out[note.status if note.status in STATUSES else "none"] += 1
        return out


def _impl_list(fm: str) -> list[str]:
    """Every path any ``implemented_by:`` key names, in order, de-duplicated.

    Reads *all* occurrences, not the first: a doubled key is drift to repair,
    and the repair must not lose the half a first-only parser would ignore.
    """
    out: list[str] = []
    for m in _IMPL_INLINE.finditer(fm):
        inner = m.group(1).strip()[1:-1]
        out += [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    for m in _IMPL_BLOCK.finditer(fm):
        out += [
            ln.strip().lstrip("-").strip().strip("'\"")
            for ln in m.group(1).splitlines()
            if ln.strip()
        ]
    return list(dict.fromkeys(out))


def _resolve_target(target: str, root: Path, vault: Path) -> Path:
    """A spec-pointer target, as a note path. Three spellings are in use.

    Repo-relative (``Genesis Markdown/40-Memory/X.md``), vault-relative
    (``40-Memory/X.md``) and a bare name (``X.md``) -- the last valid because
    note names are unique (CLAUDE.md, *wikilinks are real files*). An
    unresolvable target comes back as written, so the report names what the
    code actually says rather than a guess at what it meant.
    """
    for candidate in (root / target, vault / target):
        if candidate.exists():
            return candidate.resolve()
    if "/" not in target:
        found = list(vault.rglob(target))
        if len(found) == 1:
            return found[0].resolve()
    base = root / target if target.startswith(vault.name + "/") else vault / target
    return base.resolve()


def _pointers(root: Path, vault: Path) -> dict[Path, tuple[str, ...]]:
    out: dict[Path, list[str]] = {}
    for directory in SOURCE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in SOURCE_SUFFIXES or "__pycache__" in path.parts:
                continue
            # The pointer is a header, not a mention. Only the first 40 lines
            # count, so prose about another note's spec is not a claim to
            # implement it.
            head = "\n".join(
                path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
            )
            for line in _POINTER.findall(head):
                # One pointer may name several notes, separated by the vault's
                # `·`. Only the first is repo-relative; the rest are
                # vault-relative.
                for target in (t.strip() for t in line.split("·")):
                    if target.endswith(".md"):
                        key = _resolve_target(target, root, vault)
                        out.setdefault(key, []).append(str(path.relative_to(root)))
    return {k: tuple(v) for k, v in out.items()}


def read_note(path: Path, root: Path, vault: Path) -> Note | None:
    """One note. ``None`` when it carries no frontmatter at all."""
    text = path.read_text(encoding="utf-8")
    match = _FM.match(text)
    fm = match.group(1) if match else ""
    # Opened and never closed is a different thing from never opened, and only
    # the first is drift: a note with no frontmatter is usually prose.
    opened_only = match is None and text.startswith("---\n")
    rel = path.relative_to(vault)
    status_match = _STATUS.search(fm)
    title_match = _TITLE.search(fm)
    return Note(
        name=path.stem,
        path=path.resolve(),
        rel=str(path.relative_to(root)),
        section=rel.parts[0] if len(rel.parts) > 1 else "(root)",
        title=title_match.group(1) if title_match else path.stem,
        status=status_match.group(1) if status_match else "",
        implemented_by=tuple(_impl_list(fm)),
        links=tuple(dict.fromkeys(l.strip() for l in _LINK.findall(text))),
        doubled=len(_IMPL_KEY.findall(fm)) > 1,
        frontmatter_ok=not opened_only,
    )


def load(root: Path = REPO) -> Genome:
    """Read the whole genome from disk.

    A few hundred kilobytes of markdown and no cache, deliberately: a cached
    body map is a second body map, and two body maps drift.
    """
    vault = root / "Genesis Markdown"
    notes = tuple(
        note
        for path in sorted(vault.rglob("*.md"))
        if (note := read_note(path, root, vault)) is not None
    )
    return Genome(notes=notes, pointers=_pointers(root, vault), root=root)


@lru_cache(maxsize=1)
def _cached(root: str, stamp: float) -> Genome:
    return load(Path(root))


def load_cached(root: Path = REPO) -> Genome:
    """The genome, re-read when any note's mtime changes.

    For the read route, which a panel polls. The stamp is the newest note
    mtime, so an edit in Obsidian is picked up on the next call and a hot loop
    does not re-parse 219 files for nothing.
    """
    vault = root / "Genesis Markdown"
    stamp = max((p.stat().st_mtime for p in vault.rglob("*.md")), default=0.0)
    return _cached(str(root), stamp)


if __name__ == "__main__":
    genome = load()
    counts = genome.counts()
    assert len(genome.notes) > 100, len(genome.notes)
    assert genome.resolve("Biological Design") is not None
    assert genome.resolve("nothing at all") is None
    assert sum(counts.values()) == len(genome.notes)
    print(f"{len(genome.notes)} notes  {counts}")
    for name, notes in genome.collisions().items():
        print(f"collision: {name} -> {', '.join(n.rel for n in notes)}")
