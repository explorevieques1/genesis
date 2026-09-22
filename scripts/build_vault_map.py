#!/usr/bin/env python3
# Spec: Genesis Markdown/00-Meta/Vault Map.md
"""Regenerate `Genesis Markdown/00-Meta/Vault Map.md`.

    python3 scripts/build_vault_map.py

The rendering lives in `genesis.dna.vault_map`, so the map, `genesis dna map`
and the `DNA` module are all one reading of the genome rather than three.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from genesis.dna import vault_map  # noqa: E402


def main() -> int:
    count, collisions = vault_map.write()
    print(f"wrote {vault_map.OUT.relative_to(Path(__file__).resolve().parent.parent)} — {count} notes")
    if collisions:
        print(f"WARNING: {len(collisions)} name collision(s); wikilinks are ambiguous")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
