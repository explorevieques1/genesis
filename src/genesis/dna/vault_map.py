# Spec: Genesis Markdown/00-Meta/Vault Map.md
"""Expression: the genome rendered as the table a reader can navigate.

The map exists for one reason. Claude Code reads files, not graphs, and a
wikilink like ``[[Risk Envelope]]`` means nothing to it until something
resolves that name to a path. This is that something -- and it is generated,
never hand-kept, because a hand-kept index of 220 notes is an index that is
wrong by Thursday.

The rendered file carries its own ``status:`` and ``implemented_by:``, read out
of the genome like any other note's: the map's gene is transcribed from the
code that writes it, so it cannot claim a file that has stopped pointing back.
"""

from __future__ import annotations

from pathlib import Path

from genesis.dna.genome import REPO, Genome, load

__all__ = ["OUT", "render", "write"]

OUT = REPO / "Genesis Markdown" / "00-Meta" / "Vault Map.md"
ICON = {"spec": "○", "building": "◐", "built": "●"}


def render(genome: Genome) -> str:
    """The whole map as markdown. Pure -- :func:`write` is the one that writes."""
    out_rel = str(OUT.relative_to(genome.root))
    notes = [n for n in genome.notes if n.rel != out_rel]
    mine = next((n for n in genome.notes if n.rel == out_rel), None)
    behind = list(genome.pointing_at(mine)) if mine else []

    lines = [
        "---",
        "title: Vault Map",
        "tags: [meta, generated]",
        # The map is an organ like any other and says so, so the DNA row of
        # the body map stops reading `n/a`.
        "status: built",
    ]
    if behind:
        lines.append("implemented_by: [" + ", ".join(behind) + "]")
    lines += [
        "---",
        "",
        "# Vault Map",
        "",
        "> [!warning] Generated file",
        "> Written by `genesis dna map` (`src/genesis/dna/vault_map.py`). Do not edit",
        "> by hand — re-run it after adding, renaming, or moving a note.",
        "",
        "Every note name resolves to exactly one path. When you meet a `[[wikilink]]`",
        "while reading, this is how you find the file behind it.",
        "",
        f"**{len(notes)} notes.** Status: ○ spec · ◐ building · ● built",
        "",
    ]

    collisions = genome.collisions()
    if collisions:
        lines += [
            "> [!danger] Name collisions",
            "> These names appear more than once, so `[[link]]` is ambiguous. Rename one:",
            "",
        ]
        for name, found in collisions.items():
            lines.append(f"> - `{name}` → " + ", ".join(f"`{n.rel}`" for n in found))
        lines.append("")

    current = None
    for note in notes:
        if note.section != current:
            lines += ["", f"## {note.section}", "", "| Note | Path | | Implemented by |", "|---|---|---|---|"]
            current = note.section
        impl = ", ".join(note.implemented_by)
        lines.append(f"| `{note.name}` | `{note.rel}` | {ICON.get(note.status, '')} | {impl} |")

    lines += [
        "",
        "---",
        "",
        "## Build status",
        "",
        "```dataview",
        "TABLE status, implemented_by",
        'FROM "10-Architecture" OR "20-Agents" OR "30-MCP" OR "40-Memory" '
        'OR "50-Risk" OR "60-UI" OR "70-Schemas"',
        "WHERE status != null",
        "SORT status ASC, file.name ASC",
        "```",
        "",
    ]
    return "\n".join(lines)


def write(genome: Genome | None = None, out: Path = OUT) -> tuple[int, dict[str, tuple]]:
    """Regenerate the map. Returns the note count and any name collisions."""
    genome = genome or load()
    out.write_text(render(genome), encoding="utf-8")
    return len(genome.notes), genome.collisions()
