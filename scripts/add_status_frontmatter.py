#!/usr/bin/env python3
"""Add `status` and `implemented_by` to buildable vault notes.

Buildable = a note that describes something we will write code for. Meta notes,
repo notes, the home MOC and the canvas are excluded — they document, they are
not built.

Idempotent: a note that already carries a `status:` key is left alone, so this is
safe to re-run after you have started moving notes to `building` / `built`.
"""

import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent / "Genesis Markdown"

BUILDABLE = [
    "10-Architecture",
    "20-Agents",
    "30-MCP",
    "40-Memory",
    "50-Risk",
    "60-UI",
    "70-Schemas",
]

FM = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


def main() -> int:
    touched = skipped = broken = 0

    for section in BUILDABLE:
        for note in sorted((VAULT / section).rglob("*.md")):
            text = note.read_text(encoding="utf-8")
            m = FM.match(text)

            if not m:
                print(f"  no frontmatter: {note.relative_to(VAULT)}")
                broken += 1
                continue

            block = m.group(1)
            if re.search(r"^status:", block, re.MULTILINE):
                skipped += 1
                continue

            addition = "status: spec\nimplemented_by: []\n"
            note.write_text(
                text[: m.end(1)] + addition + text[m.end(1) :],
                encoding="utf-8",
            )
            touched += 1

    print(f"\nadded: {touched}   already had status: {skipped}   no frontmatter: {broken}")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
