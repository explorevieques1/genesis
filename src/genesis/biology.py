# Spec: Genesis Markdown/10-Architecture/Biological Design.md §The map
"""The organ map, read from the note that defines it.

`Biological Design` §The map is a table: organ, what it is in Genesis, and the
notes that specify it. This parses that table and asks each linked note for its
``status:``. It keeps no list of its own. Add a row to the note and the organ
shows up here; delete one and it is gone. A hand-kept copy of the table would be
a second body map, and two body maps drift (Safety Invariants #6).

An organ's status rolls up from its notes: ``built`` when all of them are
built, ``spec`` when none has started, ``building`` otherwise. A link that
resolves to no note is ``missing``. That is drift, and it is reported, never
dropped. A note with no status (a principle, not a component) is ``n/a`` and
does not count toward the rollup.

Afferent and pure: it reads markdown and nothing else, so it cannot fail in a
way that matters beyond "this readout is unavailable".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from genesis import dna

REPO = Path(__file__).resolve().parents[2]
VAULT = REPO / "Genesis Markdown"
NOTE = VAULT / "10-Architecture" / "Biological Design.md"

_LINK = re.compile(r"\[\[([^\]|#]+)")
_CODE = re.compile(r"`([^`]+)`")
# `- **Organ** — one line` under `## Organ status`.
_SUMMARY = re.compile(r"^- \*\*(.+?)\*\* — (.+)$", re.M)


def rollup(statuses: list[str]) -> str:
    counted = [s for s in statuses if s != "n/a"]
    if not counted:
        return "n/a"
    if all(s == "built" for s in counted):
        return "built"
    if all(s in ("spec", "missing") for s in counted):
        return "spec"
    return "building"


def organs(note: Path = NOTE, vault: Path = VAULT) -> list[dict[str, Any]]:
    """Every row of the map, with each linked note and its status."""
    # The genome, read once -- the same reading `genesis dna` and the `DNA`
    # module use. This module used to carry its own note index and its own
    # frontmatter regex, which made four parsers of one body map; four
    # readings of one genome is how the readings disagree.
    genome = dna.load(vault.parent)
    text = note.read_text(encoding="utf-8")
    status_section = text.split("## Organ status", 1)[1].split("\n## ", 1)[0] if "## Organ status" in text else ""
    summaries = dict(_SUMMARY.findall(status_section))
    lines = text.split("## The map", 1)[1].splitlines()
    # The first table after the heading, and only that one — the note has others.
    start = next(i for i, ln in enumerate(lines) if ln.startswith("|"))
    rows = []
    for ln in lines[start:]:
        if not ln.startswith("|"):
            break
        rows.append(ln)
    split = lambda row: [c.strip() for c in row.strip().strip("|").split("|")]  # noqa: E731
    col = {h.lower(): i for i, h in enumerate(split(rows[0]))}
    out = []
    for row in rows[2:]:  # header, separator
        cells = split(row)
        if len(cells) < len(col):
            continue
        name, genesis, where = cells[col["biology"]], cells[col["genesis"]], cells[col["where"]]
        parts = []
        for link in _LINK.findall(where):
            linked = genome.resolve(link.strip())
            parts.append({
                "name": link.strip(),
                "path": linked.rel if linked else None,
                # A note with no `status:` is a principle, not a component --
                # `n/a`, and it does not count toward the organ's rollup.
                "status": (linked.status or "n/a") if linked else "missing",
            })
        for code in _CODE.findall(where):
            parts.append({
                "name": code,
                "path": code,
                "status": "built" if (REPO / code).exists() else "spec",
            })
        out.append({
            "organ": name.strip("*"),
            # Bold rows are Phase 1 — the note says so directly under the table.
            "phase1": name.startswith("**"),
            "loop": cells[col["loop"]],
            "genesis": genesis.replace("*", "").replace("`", ""),
            "status": rollup([p["status"] for p in parts]),
            # What it can do today, from `## Organ status`. Empty if the note has no line for it.
            "summary": summaries.get(name.strip("*"), ""),
            "parts": parts,
        })
    return out


if __name__ == "__main__":
    assert rollup(["built", "built"]) == "built"
    assert rollup(["built", "spec"]) == "building"
    assert rollup(["spec", "missing"]) == "spec"
    assert rollup(["n/a", "built"]) == "built"
    assert rollup(["n/a"]) == "n/a"
    got = organs()
    assert len(got) >= 16, len(got)
    assert all(o["summary"] for o in got), [o["organ"] for o in got if not o["summary"]]
    assert got[0]["organ"] == "Brain" and got[0]["loop"] == "judgement"
    assert next(o for o in got if o["organ"] == "Heartbeat")["phase1"]
    for o in got:
        print(f"{o['status']:9} {o['organ']:18} " + ", ".join(f"{p['name']}={p['status']}" for p in o["parts"]))
