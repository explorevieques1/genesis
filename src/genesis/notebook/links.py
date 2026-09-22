# Spec: Genesis Markdown/60-UI/Notebook.md · 60-UI/Nodes.md
"""Wikilinks: one regex, one index, two consumers.

Backlinks in [[Notebook]] and the graph in [[Nodes]] are the same question
asked twice -- *what links to what* -- so they are one parse of the vault, here,
rather than two that can disagree about whether ``[[Gann|the man]]`` points at
``Gann``.

**Nothing is stored.** The index is built from the files on each request and
thrown away. A cached link graph is a second truth that goes stale the moment
someone edits a note in Obsidian, and the staleness is invisible: the picture
still draws, it is just wrong.

> ``ponytail: full-vault parse per request. Cache by directory mtime when a
> vault passes ~5k notes; the LinkIndex constructor is the only seam that
> needs to change.``

Resolution follows Obsidian: an exact vault-relative path, else the unique file
with that basename, else -- when several match -- the nearest one, with the
alternatives reported rather than swallowed. Ambiguity is surfaced, never
guessed ([[Operating Model]] §4 makes the same argument about tickers).

A target that resolves to nothing is **not an error**. It is an unresolved
link: dimmed in the editor, hollow in the graph, and clicking it creates the
note. That is the whole authoring loop -- you write the link you wish existed,
then click it into being.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from genesis.notebook.vault import MARKDOWN, Vault

__all__ = ["LinkIndex", "Ref", "parse_links", "parse_tags"]

#: ``![[Target#Heading|Alias]]``. The leading ``!`` makes it an embed.
_WIKILINK = re.compile(
    r"(?P<embed>!)?\[\[(?P<target>[^\[\]|#^]*)"
    r"(?P<anchor>[#^][^\[\]|]*)?"
    r"(?:\|(?P<alias>[^\[\]]*))?\]\]"
)

#: ``#tag``, ``#tag/sub``. Must start with a letter -- ``#1`` is a heading or a
#: number, not a tag, and Obsidian agrees.
_TAG = re.compile(r"(?<![\w#/])#(?P<tag>[A-Za-z][\w\-/]*)")

#: Fenced and inline code, blanked before parsing. A ``[[link]]`` inside a code
#: block is an example of a link, not one, and a graph that believes otherwise
#: grows edges out of documentation.
_CODE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]*`", re.DOTALL)


def _strip_code(body: str) -> str:
    """Blank code spans, preserving offsets so positions stay meaningful."""
    return _CODE.sub(lambda m: " " * len(m.group(0)), body)


@dataclass(frozen=True, slots=True)
class Ref:
    """One ``[[link]]`` as written, before it is resolved to a file."""

    target: str
    anchor: str = ""
    alias: str = ""
    embed: bool = False
    start: int = 0
    end: int = 0

    @property
    def display(self) -> str:
        return self.alias or (self.target + self.anchor)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target, "anchor": self.anchor, "alias": self.alias,
            "embed": self.embed, "start": self.start, "end": self.end,
        }


def parse_links(body: str) -> list[Ref]:
    """Every wikilink in a note, in the order written."""
    out: list[Ref] = []
    for match in _WIKILINK.finditer(_strip_code(body)):
        target = (match.group("target") or "").strip()
        if not target:
            continue          # `[[#Heading]]` — a link inside this same note
        out.append(Ref(
            target=target,
            anchor=(match.group("anchor") or "").strip(),
            alias=(match.group("alias") or "").strip(),
            embed=bool(match.group("embed")),
            start=match.start(), end=match.end(),
        ))
    return out


def parse_tags(body: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _TAG.finditer(_strip_code(body)):
        seen.setdefault(match.group("tag"), None)
    return list(seen)


@dataclass
class IndexedNote:
    path: str
    name: str
    refs: list[Ref] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Resolution:
    """Where a ``[[link]]`` points, and what else it could have meant."""

    path: str | None
    candidates: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.path is not None

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


class LinkIndex:
    """Every note in a vault, its links, and its tags. Built once, per request."""

    def __init__(self, vault: Vault) -> None:
        vault.require()
        self.vault = vault
        self.notes: dict[str, IndexedNote] = {}
        self._by_stem: dict[str, list[str]] = defaultdict(list)
        for path in vault.walk():
            rel = vault.rel(path)
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            note = IndexedNote(rel, path.stem, parse_links(body), parse_tags(body))
            self.notes[rel] = note
            self._by_stem[path.stem.lower()].append(rel)

    # -- resolution -------------------------------------------------------

    def resolve(self, target: str, *, source: str = "") -> Resolution:
        """Obsidian's order: exact path, then unique basename, then nearest."""
        cleaned = target.strip().strip("/")
        if not cleaned:
            return Resolution(None)

        # 1. as a vault-relative path, with `.md` supplied when it is absent.
        as_path = cleaned if Path(cleaned).suffix.lower() in MARKDOWN else f"{cleaned}.md"
        if as_path in self.notes:
            return Resolution(as_path)
        lowered = as_path.lower()
        for rel in self.notes:
            if rel.lower() == lowered:
                return Resolution(rel)

        # 2. by basename. One match is the answer; several is a real ambiguity.
        stem = Path(cleaned).stem.lower()
        matches = self._by_stem.get(stem, [])
        if len(matches) == 1:
            return Resolution(matches[0])
        if matches:
            nearest = min(matches, key=lambda m: (-_shared_depth(m, source), m.lower()))
            return Resolution(nearest, tuple(sorted(matches)))
        return Resolution(None)

    def unresolved(self) -> dict[str, list[str]]:
        """Link target → the notes that link to it, for targets with no file."""
        out: dict[str, list[str]] = defaultdict(list)
        for note in self.notes.values():
            for ref in note.refs:
                if _is_attachment(ref.target):
                    continue
                if not self.resolve(ref.target, source=note.path).resolved:
                    out[ref.target].append(note.path)
        return dict(out)

    # -- backlinks --------------------------------------------------------

    def backlinks(self, rel: str) -> list[dict[str, Any]]:
        """Which notes link here, with the line each link sits on."""
        out: list[dict[str, Any]] = []
        for note in self.notes.values():
            if note.path == rel:
                continue
            for ref in note.refs:
                if self.resolve(ref.target, source=note.path).path != rel:
                    continue
                out.append({
                    "path": note.path, "name": note.name,
                    "context": self._context(note.path, ref),
                    "embed": ref.embed,
                })
                break
        out.sort(key=lambda b: b["path"].lower())
        return out

    def _context(self, rel: str, ref: Ref) -> str:
        try:
            body = self.vault.resolve(rel, markdown=True).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return ""
        start = body.rfind("\n", 0, ref.start) + 1
        end = body.find("\n", ref.end)
        return body[start:end if end >= 0 else len(body)].strip()[:240]

    # -- the graph --------------------------------------------------------

    def graph(
        self, *,
        tags: bool = False,
        attachments: bool = False,
        unresolved: bool = True,
        orphans: bool = True,
        focus: str | None = None,
        depth: int = 1,
    ) -> dict[str, Any]:
        """Nodes and edges for [[Nodes]], in `ForceGraph`'s input shape.

        Node ids are namespaced (``note:``, ``tag:``, ``unresolved:``) because a
        note and a tag can share a name and one collision would silently merge
        two dots into one.
        """
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []

        def node(node_id: str, kind: str, label: str, path: str | None = None) -> None:
            nodes.setdefault(node_id, {
                "id": node_id, "kind": kind, "label": label, "path": path, "weight": 0,
            })

        for note in self.notes.values():
            node(f"note:{note.path}", "note", note.name, note.path)

        for note in self.notes.values():
            source = f"note:{note.path}"
            for ref in note.refs:
                if _is_attachment(ref.target):
                    if not attachments:
                        continue
                    target_id = f"attachment:{ref.target}"
                    node(target_id, "attachment", Path(ref.target).name)
                else:
                    hit = self.resolve(ref.target, source=note.path)
                    if hit.resolved:
                        target_id = f"note:{hit.path}"
                    elif unresolved:
                        target_id = f"unresolved:{ref.target}"
                        node(target_id, "unresolved", ref.target)
                    else:
                        continue
                if target_id == source:
                    continue
                edges.append({"source": source, "target": target_id, "kind": "link"})
            if tags:
                for tag in note.tags:
                    node(f"tag:{tag}", "tag", f"#{tag}")
                    edges.append({"source": source, "target": f"tag:{tag}", "kind": "tag"})

        edges = _dedupe(edges)
        for edge in edges:
            for end in (edge["source"], edge["target"]):
                if end in nodes:
                    nodes[end]["weight"] += 1

        keep = set(nodes)
        if focus:
            keep = _reachable(f"note:{focus}", edges, max(1, min(depth, 3)))
        elif not orphans:
            keep = {n for n in nodes if nodes[n]["weight"] > 0}

        return {
            "nodes": [n for nid, n in nodes.items() if nid in keep],
            "edges": [e for e in edges if e["source"] in keep and e["target"] in keep],
        }

    # -- renames ----------------------------------------------------------

    def rename_preview(self, src: str, dst: str) -> list[dict[str, Any]]:
        """Which links a rename would rewrite, and to what.

        Shown before anything is written. A bulk edit of the human's own prose
        is exactly the thing that must not happen without them seeing it.
        """
        new_target = Path(dst).stem
        out: list[dict[str, Any]] = []
        for note in self.notes.values():
            hits = [r for r in note.refs
                    if self.resolve(r.target, source=note.path).path == src]
            if hits:
                out.append({
                    "path": note.path, "name": note.name, "count": len(hits),
                    "to": new_target,
                })
        out.sort(key=lambda h: h["path"].lower())
        return out

    def rewrite_links(self, src: str, dst: str) -> int:
        """Point every link at ``src`` to ``dst``. Returns notes changed.

        Rewrites the *target* only; an alias is the writer's own words and is
        left exactly as it was. Applied back-to-front so earlier offsets stay
        valid while later ones are replaced.
        """
        new_target = Path(dst).stem
        changed = 0
        for note in list(self.notes.values()):
            hits = [r for r in note.refs
                    if self.resolve(r.target, source=note.path).path == src]
            if not hits:
                continue
            path = self.vault.resolve(note.path, markdown=True)
            body = path.read_text(encoding="utf-8", errors="replace")
            for ref in sorted(hits, key=lambda r: r.start, reverse=True):
                bang = "!" if ref.embed else ""
                alias = f"|{ref.alias}" if ref.alias else ""
                body = body[:ref.start] + f"{bang}[[{new_target}{ref.anchor}{alias}]]" + body[ref.end:]
            path.write_text(body, encoding="utf-8")
            changed += 1
        return changed


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _is_attachment(target: str) -> bool:
    suffix = Path(target).suffix.lower()
    return bool(suffix) and suffix not in MARKDOWN


def _shared_depth(candidate: str, source: str) -> int:
    """How many leading folders two vault paths have in common."""
    a, b = candidate.split("/")[:-1], source.split("/")[:-1]
    shared = 0
    for x, y in zip(a, b):
        if x != y:
            break
        shared += 1
    return shared


def _dedupe(edges: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: dict[tuple[str, str, str], dict[str, str]] = {}
    for edge in edges:
        seen.setdefault((edge["source"], edge["target"], edge["kind"]), edge)
    return list(seen.values())


def _reachable(start: str, edges: list[dict[str, str]], depth: int) -> set[str]:
    """BFS both ways from a focus node. The local graph."""
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        neighbours[edge["source"]].add(edge["target"])
        neighbours[edge["target"]].add(edge["source"])
    seen = {start}
    frontier = {start}
    for _ in range(depth):
        nxt: set[str] = set()
        for node in frontier:
            nxt |= neighbours[node] - seen
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    return seen
