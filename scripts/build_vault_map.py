#!/usr/bin/env python3
"""Regenerate `Genesis Markdown/00-Meta/Vault Map.md`.

The map exists for one reason: Claude Code reads files, not graphs. A wikilink
like [[Risk Envelope]] means nothing to it until something resolves that name to
a path. This file is that something.

Run after adding, renaming, or moving a note:

    python3 scripts/build_vault_map.py
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "Genesis Markdown"
OUT = VAULT / "00-Meta" / "Vault Map.md"

FM = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)
STATUS = re.compile(r"^status:\s*(\S+)", re.MULTILINE)
IMPL = re.compile(r"^implemented_by:\s*(.+)$", re.MULTILINE)

STATUS_ICON = {"spec": "○", "building": "◐", "built": "●"}


def frontmatter(text: str) -> str:
    m = FM.match(text)
    return m.group(1) if m else ""


def main() -> int:
    notes = []
    names = defaultdict(list)

    for path in sorted(VAULT.rglob("*.md")):
        if path == OUT:
            continue
        rel = path.relative_to(VAULT)
        fm = frontmatter(path.read_text(encoding="utf-8"))
        status = (STATUS.search(fm) or [None, ""])[1] if STATUS.search(fm) else ""
        impl = IMPL.search(fm)
        impl_txt = impl.group(1).strip() if impl else ""
        if impl_txt in ("[]", ""):
            impl_txt = ""
        notes.append((rel, status, impl_txt))
        names[path.stem].append(rel)

    collisions = {n: p for n, p in names.items() if len(p) > 1}

    lines = [
        "---",
        "title: Vault Map",
        "tags: [meta, generated]",
        "---",
        "",
        "# Vault Map",
        "",
        "> [!warning] Generated file",
        "> Written by `scripts/build_vault_map.py`. Do not edit by hand —",
        "> re-run the script after adding, renaming, or moving a note.",
        "",
        "Every note name resolves to exactly one path. When you meet a `[[wikilink]]`",
        "while reading, this is how you find the file behind it.",
        "",
        f"**{len(notes)} notes.** Status: ○ spec · ◐ building · ● built",
        "",
    ]

    if collisions:
        lines += [
            "> [!danger] Name collisions",
            "> These names appear more than once, so `[[link]]` is ambiguous. Rename one:",
            "",
        ]
        for name, paths in sorted(collisions.items()):
            lines.append(f"> - `{name}` → " + ", ".join(f"`{p}`" for p in paths))
        lines.append("")

    current = None
    for rel, status, impl in notes:
        section = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        if section != current:
            lines += ["", f"## {section}", "", "| Note | Path | | Implemented by |", "|---|---|---|---|"]
            current = section
        icon = STATUS_ICON.get(status, "")
        lines.append(f"| `{rel.stem}` | `Genesis Markdown/{rel}` | {icon} | {impl} |")

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

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(notes)} notes")
    if collisions:
        print(f"WARNING: {len(collisions)} name collision(s); wikilinks are ambiguous")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
