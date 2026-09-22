# Spec: Genesis Markdown/00-Meta/Conventions.md
"""Mutation, and the repair that is allowed to run.

Biological Design calls spec drift *proprioceptive drift*: a note describing an
organ the system does not have makes the system reason confidently about itself
and be wrong. CLAUDE.md hard rule 6 says spec and code move in the same commit.
This is the test for it, because a rule with no test is a preference.

A mis-transcribing cell does not feel wrong. It just is wrong. Every one of the
five kinds below is silent without a check:

1. **A cut forward nerve.** Code carries ``# Spec: <note>`` and the note does
   not list that file in ``implemented_by:``. The organ points at the map; the
   map does not point back. This is how ``MCP Gateway.md`` sat at
   ``status: spec`` with 3,859 lines of ``src/genesis/mcp/`` behind it.
2. **A phantom limb.** ``implemented_by:`` names a file that does not exist.
3. **A stale status.** ``status: spec`` while code exists, or
   ``built``/``building`` with nothing behind it.
4. **A dangling pointer.** Code carries ``# Spec:`` for a note that does not
   exist -- a rename, a typo, or an organ written before its map. Walking the
   vault never sees it, because the vault is not where it is.
5. **A doubled nerve.** Two ``implemented_by:`` keys in one frontmatter. YAML
   keeps the last, so the first list silently stops existing.

``repair`` is DNA repair and is bounded like the biological kind: it only ever
writes what the code already proves. A file whose spec pointer names a note is
appended to that note's ``implemented_by:``; a note with code behind it is
moved off ``spec``. It never invents ``built`` -- "done" is a human judgement,
so the most it claims is ``building``. Phantom limbs are never auto-removed: a
missing file is either a deletion nobody recorded or a typo, and guessing which
one silently is the failure this module exists to catch.

**Nothing calls repair on a schedule.** It is a person's command, and that is
the design: an auto-repair running unattended will eventually paper over the
one drift that mattered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from genesis.dna.genome import (
    REPO,
    STATUSES,
    Genome,
    Note,
    _IMPL_BLOCK,
    _IMPL_INLINE,
    _STATUS,
    load,
)

__all__ = ["Finding", "KINDS", "check", "repair"]

#: Each kind of drift, in report order, with the glyph the CLI and the `DNA`
#: module both use. One table so the two surfaces cannot describe the same
#: finding differently.
KINDS: dict[str, tuple[str, str]] = {
    "broken-frontmatter": ("🧬", "the frontmatter opens and never closes; every reader skips it"),
    "cut-nerve": ("🔌", "code points at the note, the note does not point back"),
    "phantom-limb": ("👻", "implemented_by names a file that does not exist"),
    "stale-status": ("🕰️", "the status disagrees with whether code exists"),
    "dangling-pointer": ("🧷", "code names a note that does not exist"),
    "doubled-nerve": ("🪢", "two implemented_by keys; YAML keeps only the last"),
}


@dataclass(frozen=True)
class Finding:
    """One mutation, named well enough to fix by hand."""

    kind: str
    note: str
    detail: str
    files: tuple[str, ...] = ()

    @property
    def glyph(self) -> str:
        return KINDS[self.kind][0]

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "glyph": self.glyph,
            "note": self.note,
            "detail": self.detail,
            "files": list(self.files),
        }


def check(genome: Genome | None = None) -> list[Finding]:
    """Every drift in the genome, in report order. Pure: it writes nothing."""
    genome = genome or load()
    out: list[Finding] = []

    for note in genome.notes:
        if not note.frontmatter_ok:
            # Everything else about this note is read off frontmatter that no
            # parser can see, so reporting a cut nerve or a stale status here
            # would be reporting an artefact of the real fault. One finding,
            # and it names the line to add.
            out.append(Finding(
                "broken-frontmatter", note.rel,
                "`---` opens the frontmatter and nothing closes it — add the "
                "closing `---`, or its status and implemented_by do not exist",
            ))
            continue
        declared = list(note.implemented_by)
        pointing = genome.pointing_at(note)

        missing = [p for p in pointing if p not in declared]
        if missing:
            out.append(Finding(
                "cut-nerve", note.rel,
                f"{len(missing)} file(s) point here and are not listed back",
                tuple(missing),
            ))

        gone = [p for p in declared if not (genome.root / p).exists()]
        if gone:
            out.append(Finding(
                "phantom-limb", note.rel,
                f"{len(gone)} listed file(s) do not exist",
                tuple(gone),
            ))

        if note.status in STATUSES:
            has_code = bool(declared or pointing)
            if note.status == "spec" and has_code:
                out.append(Finding(
                    "stale-status", note.rel,
                    f"status: spec — {len(declared) + len(missing)} file(s) behind it",
                ))
            elif note.status in ("building", "built") and not has_code:
                out.append(Finding(
                    "stale-status", note.rel,
                    f"status: {note.status} — nothing behind it",
                ))

        if note.doubled:
            out.append(Finding(
                "doubled-nerve", note.rel,
                "two implemented_by keys; the first list is silently dead",
            ))

    known = {n.path for n in genome.notes}
    for path, files in sorted(genome.pointers.items()):
        if path not in known and not path.exists():
            rel = str(path.relative_to(genome.root)) if path.is_relative_to(genome.root) else str(path)
            out.append(Finding(
                "dangling-pointer", rel,
                f"{len(files)} file(s) name a note that is not there",
                tuple(files),
            ))

    order = list(KINDS)
    return sorted(out, key=lambda f: (order.index(f.kind), f.note))


# --------------------------------------------------------------------------
# Repair — writes to the vault. A person's command, never the daemon's.
# --------------------------------------------------------------------------


def _rewrite_impl(fm: str, paths: list[str], *, block: bool) -> str:
    """Remove every ``implemented_by:`` key and write exactly one back."""
    for pattern in (_IMPL_BLOCK, _IMPL_INLINE):
        fm = pattern.sub("", fm)
    fm = re.sub(r"^implemented_by:\s*$\n?", "", fm, flags=re.MULTILINE)
    rendered = (
        "implemented_by:\n" + "".join(f"  - {p}\n" for p in paths)
        if block
        else "implemented_by: [" + ", ".join(paths) + "]\n"
    )
    return fm.rstrip("\n") + "\n" + rendered


_FM = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


def repair(genome: Genome | None = None, root: Path = REPO) -> list[str]:
    """Reconnect cut nerves and move stale `spec` statuses on. Returns what changed.

    Two repairs only, both of which the code already proves. Everything else in
    :func:`check` is reported and left alone on purpose.
    """
    genome = genome or load(root)
    changed: list[str] = []
    for note in genome.notes:
        if not note.frontmatter_ok:
            # Where the frontmatter ends is a guess, and guessing silently is
            # the failure this module exists to catch. Reported, never fixed.
            continue
        missing = [p for p in genome.pointing_at(note) if p not in note.implemented_by]
        needs = missing or note.doubled or (note.status == "spec" and note.implemented_by)
        if not needs:
            continue
        text = note.path.read_text(encoding="utf-8")
        match = _FM.match(text)
        if not match:
            continue
        fm = match.group(1)
        merged = list(dict.fromkeys(list(note.implemented_by) + missing))
        block = bool(_IMPL_BLOCK.search(fm)) or (not _IMPL_INLINE.search(fm) and len(merged) > 3)
        new_fm = _rewrite_impl(fm, merged, block=block)
        if note.status == "spec" and merged:
            new_fm = _STATUS.sub("status: building", new_fm, count=1)
        note.path.write_text("---\n" + new_fm + "---\n" + text[match.end():], encoding="utf-8")
        changed.append(note.rel)
    return changed


def _note_for(genome: Genome, rel: str) -> Note | None:  # pragma: no cover - CLI convenience
    return next((n for n in genome.notes if n.rel == rel), None)
