#!/usr/bin/env python3
# Spec: Genesis Markdown/00-Meta/Conventions.md
"""Does the vault still describe the system that exists?

    python3 scripts/check_body_map.py          # report, exit 1 on drift
    python3 scripts/check_body_map.py --fix    # repair cut nerves and stale statuses

The six kinds of drift, why each one is silent, and what `--fix` is allowed to
touch all live in `genesis.dna.drift` -- which is also what `genesis dna check`
and the `DNA` module read, so the pre-commit run and the panel cannot disagree
about whether the body map is honest. This file is the pre-commit door to it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from genesis.dna import drift as dna_drift  # noqa: E402
from genesis.dna import load  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="repair cut nerves and stale statuses")
    args = ap.parse_args()

    if args.fix:
        repaired = dna_drift.repair()
        for rel in repaired:
            print(f"  ✎ {rel}")
        if repaired:
            print(f"repaired {len(repaired)} note(s)\n")

    genome = load()
    findings = dna_drift.check(genome)
    for kind, (glyph, why) in dna_drift.KINDS.items():
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        print(f"\n{glyph} {kind} — {why} ({len(group)})")
        for finding in group:
            print(f"  {finding.note}  {finding.detail}")
            for path in finding.files:
                print(f"      + {path}")

    if not findings:
        print(f"✅ body map is honest — {len(genome.pointers)} notes have code pointing at them")
        return 0
    print(f"\n{len(findings)} note(s) drifting. The map may not lie — CLAUDE.md hard rule 6.")
    if not args.fix:
        print("Run with --fix to repair cut nerves and stale statuses.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
