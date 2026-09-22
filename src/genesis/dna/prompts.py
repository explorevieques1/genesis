# Spec: Genesis Markdown/00-Meta/Conventions.md
"""The other half of the genome: the prompts, inventoried.

Biological Design's DNA row is *"system prompts **and** this vault"*, and until
now only the vault half was visible to anything. A prompt is a gene like a note
is: inherited, expressed in one cell type, and invisible to the organism that
runs on it.

Read with :mod:`ast`, never by importing. Importing a module to look at its
strings runs its top level -- which in this codebase opens stores, reads config
and occasionally starts a client -- and an inventory that has side effects is
not an inventory. The AST walk sees every module-level assignment to a name
ending in ``PROMPT`` whose value is a plain string, which is the shape
Conventions has every agent declare.

**Inventory, not a source of truth.** This counts and locates prompts; it does
not edit them and there is no surface that does. A prompt is DNA, and DNA is
edited by a person in a file, then committed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from genesis.dna.genome import REPO

__all__ = ["Prompt", "inventory"]

#: Where prompts live. The orchestrator and the agents; nothing else should
#: hold one, and if something does this is how it becomes visible.
PROMPT_DIRS = ("src/genesis/agents", "src/genesis/orchestrator", "src/genesis/voice")


@dataclass(frozen=True)
class Prompt:
    """One prompt gene: where it lives, how big it is, and what it opens with."""

    name: str
    file: str
    line: int
    chars: int
    lines: int
    #: Its first sentence -- "You are the Market Analyst inside Genesis" -- which
    #: is how a person recognises which cell type this gene is expressed in.
    opening: str

    @property
    def est_tokens(self) -> int:
        """Rough, and labelled rough. Four characters to a token is close enough
        to answer "is this prompt 200 tokens or 2,000", which is the only
        question an inventory needs to answer."""
        return round(self.chars / 4)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "file": self.file,
            "line": self.line,
            "chars": self.chars,
            "lines": self.lines,
            "est_tokens": self.est_tokens,
            "opening": self.opening,
        }


def _opening(text: str) -> str:
    first = " ".join(text.strip().split())
    cut = first.find(". ")
    return (first[: cut + 1] if 0 < cut < 160 else first[:160]).strip()


def inventory(root: Path = REPO) -> list[Prompt]:
    """Every module-level ``*PROMPT`` string under :data:`PROMPT_DIRS`."""
    out: list[Prompt] = []
    for directory in PROMPT_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # a file mid-edit must not break the readout
                continue
            for node in tree.body:
                if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                    continue
                if not isinstance(node.value.value, str):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.endswith("PROMPT"):
                        text = node.value.value
                        out.append(Prompt(
                            name=target.id,
                            file=str(path.relative_to(root)),
                            line=node.lineno,
                            chars=len(text),
                            lines=text.count("\n") + 1,
                            opening=_opening(text),
                        ))
    return sorted(out, key=lambda p: (-p.chars, p.file))


if __name__ == "__main__":
    found = inventory()
    assert found, "no prompts found — the AST walk or PROMPT_DIRS is wrong"
    total = sum(p.est_tokens for p in found)
    for p in found:
        print(f"{p.est_tokens:>6} tok  {p.name:<16} {p.file}")
    print(f"{total:>6} tok  across {len(found)} prompts")
