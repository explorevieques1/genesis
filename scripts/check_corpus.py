#!/usr/bin/env python3
"""Verify the trading corpus is mounted and that INDEX.md still tells the truth.

The corpus lives on an external SSD, reached through the `corpus/` symlink in the
repo root. When the drive is unplugged that symlink dangles and every corpus path
silently fails — so check before relying on it:

    python3 scripts/check_corpus.py           # mount + repo presence
    python3 scripts/check_corpus.py --paths   # also verify every INDEX.md citation

INDEX.md citations are *repo-relative*: under the `### vectorbt` heading, the
entry `vectorbt/portfolio/` means `corpus/vectorbt/vectorbt/portfolio/` — the
first segment is the package inside the repo, not the repo itself.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
INDEX = ROOT / "INDEX.md"

HEADING = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
CITATION = re.compile(r"`([A-Za-z0-9_.\-]+/[A-Za-z0-9_./\-]*)`")

# The legend's illustrative example, not a real path.
IGNORE = {"repo/path/file.py"}


def fail(msg: str) -> int:
    print(f"\n  ✗ {msg}")
    return 1


def resolve_repo(heading: str, dirs: dict[str, Path]) -> Path | None:
    # Headings carry an attribution suffix: "qlib (Microsoft)" -> "qlib"
    name = re.sub(r"\s*\(.*?\)\s*$", "", heading).strip()
    return dirs.get(name.lower())


def main() -> int:
    if not CORPUS.is_symlink():
        return fail(
            f"{CORPUS} is not a symlink. Recreate it:\n"
            f'    ln -sfn "/run/media/gzacc2002/Extreme SSD/Github Repos/Trading" '
            f'"{ROOT}/corpus"'
        )

    target = Path(CORPUS.readlink())
    if not CORPUS.exists():
        return fail(
            f"corpus/ points at {target} but nothing is there.\n"
            f"    The external SSD is probably unplugged. Plug it in, open the drive\n"
            f"    once so udisks mounts it, then re-run."
        )

    dirs = {p.name.lower(): p for p in CORPUS.iterdir() if p.is_dir()}
    print(f"  ✓ corpus mounted — {len(dirs)} repos at {target}")

    if "--paths" not in sys.argv:
        print("\n  run with --paths to verify every INDEX.md citation resolves")
        return 0

    if not INDEX.exists():
        return fail(f"{INDEX} missing")

    text = INDEX.read_text(encoding="utf-8")

    # Split the index into (repo heading, body) chunks.
    marks = [(m.group(1), m.end()) for m in HEADING.finditer(text)]
    bounds = [m.start() for m in HEADING.finditer(text)][1:] + [len(text)]

    unknown_repos: list[str] = []
    missing: list[tuple[str, str]] = []
    checked = 0

    for (heading, start), end in zip(marks, bounds):
        repo = resolve_repo(heading, dirs)
        if repo is None:
            unknown_repos.append(heading)
            continue
        for cite in CITATION.findall(text[start:end]):
            if cite in IGNORE:
                continue
            checked += 1
            if not (repo / cite).exists():
                missing.append((heading, cite))

    print(f"  checked {checked} citations across {len(marks)} repo entries")

    if unknown_repos:
        print(f"\n  ⚠ {len(unknown_repos)} repo(s) in INDEX.md are not on the drive:")
        for h in unknown_repos:
            print(f"    - {h}")

    if missing:
        print(f"\n  ✗ {len(missing)} citation(s) no longer resolve — the upstream")
        print("    project probably renamed or moved the file. Fix INDEX.md rather")
        print("    than letting an agent guess:\n")
        for heading, cite in missing:
            print(f"    - {heading}: {cite}")
        return 1

    if not unknown_repos:
        print("  ✓ every cited path resolves")
    return 1 if unknown_repos else 0


if __name__ == "__main__":
    sys.exit(main())
