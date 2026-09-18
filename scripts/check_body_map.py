#!/usr/bin/env python3
"""Does the vault still describe the system that exists?

Biological Design calls the vault the body map and spec drift *proprioceptive
drift*: a note that describes an organ the system does not have makes the
system reason confidently about itself and be wrong. Hard rule 6 says spec and
code move in the same commit. This is the test for it, because a rule with no
test is a preference.

Three kinds of drift, all of them silent without this:

1. **A cut forward nerve.** Code carries `# Spec: <note>` and the note does not
   list that file in `implemented_by:`. The organ points at the map; the map
   does not point back. This is how `MCP Gateway.md` sat at `status: spec` with
   3,859 lines of `src/genesis/mcp/` behind it.
2. **A phantom limb.** `implemented_by:` names a file that does not exist.
3. **A stale status.** `status: spec` while `implemented_by:` is populated, or
   `status: built`/`building` with nothing behind it.
5. **A dangling pointer.** Code carries `# Spec:` for a note that does not
   exist -- a renamed note, a typo, or an organ written before its map. The
   first four checks walk the vault and never see it.
4. **A doubled nerve.** Two `implemented_by:` keys in one frontmatter. YAML
   keeps the last, so the first list silently stops existing. This checker's
   own first version made fifteen of these on 2026-09-17: it read only the
   inline `[a, b]` form, saw nothing in a block-form note, and appended a
   second key. `--fix` merges them into one block list.

    python3 scripts/check_body_map.py          # report, exit 1 on drift
    python3 scripts/check_body_map.py --fix    # repair 1 and 3, then report

`--fix` only ever adds what the code already proves: a file whose spec pointer
names a note is appended to that note's `implemented_by:`, and a note with code
behind it is moved off `spec`. It never invents a status of `built` -- "done" is
a human judgement, so the most it claims is `building`. Phantom limbs are never
auto-removed: a missing file is either a deletion nobody recorded or a typo,
and guessing which one silently is the failure this script exists to catch.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "Genesis Markdown"

#: Where a spec pointer may live. Conventions puts it on line 1 of every source
#: file; the UI carries the same pointer in a `//` comment.
SOURCE_DIRS = ("src", "ui/src", "scripts", "tests", "evals")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".sh", ".yaml"}

POINTER = re.compile(r"^(?:#|//|--)\s*Spec:\s*(.+?)\s*$", re.MULTILINE)
FM = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)
STATUS = re.compile(r"^status:\s*(\S+)", re.MULTILINE)
#: Both spellings of a YAML list, because both are in the vault: the inline
#: `[a, b]` the notes mostly use and the block form `- a` on following lines.
#: Parsing only one of them reports every note using the other as an organ
#: with nothing behind it -- a checker that lies about the map it is checking.
IMPL_INLINE = re.compile(r"^implemented_by:\s*(\[.*?\])\s*$", re.MULTILINE | re.DOTALL)
IMPL_BLOCK = re.compile(r"^implemented_by:\s*$\n((?:[ \t]*-[ \t]*\S.*\n)+)", re.MULTILINE)


def _pointers() -> dict[Path, list[str]]:
    """note path -> the source files whose first lines point at it."""
    out: dict[Path, list[str]] = defaultdict(list)
    for d in SOURCE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in SOURCE_SUFFIXES or "__pycache__" in path.parts:
                continue
            # The pointer is a header, not a mention. Only the first 40 lines
            # count, so prose about another note's spec is not a claim to
            # implement it.
            head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:40])
            for line in POINTER.findall(head):
                # One pointer may name several notes, separated by the vault's
                # `·`: `Spec: 60-UI/Workspaces.md · 60-UI/Terminal.md`. Only the
                # first is repo-relative; the rest are relative to the vault.
                for target in (t.strip() for t in line.split("·")):
                    if not target.endswith(".md"):
                        continue
                    out[_resolve(target)].append(str(path.relative_to(ROOT)))
    return out


def _resolve(target: str) -> Path:
    """A pointer target, as a note path. Three spellings are in use.

    Repo-relative (``Genesis Markdown/40-Memory/X.md``), vault-relative
    (``40-Memory/X.md``) and a bare name (``X.md``) -- the last valid because
    note names are unique (CLAUDE.md, Wikilinks are real files). An
    unresolvable target is returned as written, repo-relative, so the report
    names what the code actually says.
    """
    for candidate in (ROOT / target, VAULT / target):
        if candidate.exists():
            return candidate.resolve()
    if "/" not in target:
        found = list(VAULT.rglob(target))
        if len(found) == 1:
            return found[0].resolve()
    base = ROOT / target if target.startswith(VAULT.name + "/") else VAULT / target
    return base.resolve()


KEY = re.compile(r"^implemented_by:", re.MULTILINE)


def _impl_list(fm: str) -> list[str]:
    """Every path any ``implemented_by:`` key names, in order, de-duplicated.

    Reads *all* occurrences, not the first: a doubled key is drift to repair,
    and the repair must not lose the half a parser would have ignored.
    """
    out: list[str] = []
    for m in IMPL_INLINE.finditer(fm):
        inner = m.group(1).strip()[1:-1]
        out += [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    for m in IMPL_BLOCK.finditer(fm):
        out += [ln.strip().lstrip("-").strip().strip("'\"") for ln in m.group(1).splitlines() if ln.strip()]
    return list(dict.fromkeys(out))


def _rewrite_impl(fm: str, paths: list[str], *, block: bool) -> str:
    """Remove every ``implemented_by:`` key and write exactly one back."""
    for pattern in (IMPL_BLOCK, IMPL_INLINE):
        fm = pattern.sub("", fm)
    fm = re.sub(r"^implemented_by:\s*$\n?", "", fm, flags=re.MULTILINE)
    rendered = (
        "implemented_by:\n" + "".join(f"  - {p}\n" for p in paths)
        if block
        else "implemented_by: [" + ", ".join(paths) + "]\n"
    )
    return fm.rstrip("\n") + "\n" + rendered


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="repair cut nerves and stale statuses")
    args = ap.parse_args()

    pointers = _pointers()
    cut: list[tuple[Path, list[str]]] = []
    phantom: list[tuple[Path, list[str]]] = []
    stale: list[tuple[Path, str, int]] = []
    doubled: list[Path] = []

    for note in sorted(VAULT.rglob("*.md")):
        text = note.read_text(encoding="utf-8")
        m = FM.match(text)
        if not m:
            continue
        fm = m.group(1)
        declared = _impl_list(fm)
        status = (STATUS.search(fm).group(1) if STATUS.search(fm) else "")

        missing = [p for p in pointers.get(note.resolve(), []) if p not in declared]
        if missing:
            cut.append((note, missing))

        gone = [p for p in declared if not (ROOT / p).exists()]
        if gone:
            phantom.append((note, gone))

        # `spec | building | built` is the template line in Conventions, not a
        # status. Notes that are not components have no status at all.
        if status in ("spec", "building", "built"):
            has_code = bool(declared) or bool(pointers.get(note.resolve()))
            if status == "spec" and has_code:
                stale.append((note, status, len(declared) + len(missing)))
            elif status in ("building", "built") and not has_code:
                stale.append((note, status, 0))

        keys = len(KEY.findall(fm))
        if keys > 1:
            doubled.append(note)

        needs = missing or keys > 1 or (status == "spec" and (declared or missing))
        if args.fix and needs:
            new_impl = list(dict.fromkeys(declared + missing))
            block = bool(IMPL_BLOCK.search(fm)) or not IMPL_INLINE.search(fm) and len(new_impl) > 3
            new_fm = _rewrite_impl(fm, new_impl, block=block)
            if status == "spec" and new_impl:
                new_fm = STATUS.sub("status: building", new_fm, count=1)
            note.write_text("---\n" + new_fm + "---\n" + text[m.end():], encoding="utf-8")

    def rel(p: Path) -> str:
        return str(p.relative_to(ROOT))

    if cut:
        print(f"\n🔌 cut forward nerve — code points at the note, the note does not point back ({len(cut)})")
        for note, files in cut:
            print(f"  {rel(note)}")
            for f in files:
                print(f"      + {f}")
    if phantom:
        print(f"\n👻 phantom limb — implemented_by names a file that does not exist ({len(phantom)})")
        for note, files in phantom:
            print(f"  {rel(note)}")
            for f in files:
                print(f"      ? {f}")
    if stale:
        print(f"\n🕰️  stale status ({len(stale)})")
        for note, status, n in stale:
            why = f"{n} file(s) behind it" if n else "nothing behind it"
            print(f"  {rel(note)}  status: {status} — {why}")

    dangling = sorted(
        (note, files) for note, files in pointers.items() if not note.exists()
    )
    if dangling:
        print(f"\n🧷 dangling pointer — code names a note that does not exist ({len(dangling)})")
        for note, files in dangling:
            print(f"  {note.relative_to(ROOT) if note.is_relative_to(ROOT) else note}")
            for f in files:
                print(f"      ← {f}")

    if doubled:
        print(f"\n🪢 doubled nerve — two implemented_by keys; YAML keeps only the last ({len(doubled)})")
        for note in doubled:
            print(f"  {rel(note)}")

    drift = len(cut) + len(phantom) + len(stale) + len(doubled) + len(dangling)
    if not drift:
        print(f"✅ body map is honest — {len(pointers)} notes have code pointing at them")
        return 0
    print(f"\n{drift} note(s) drifting. The map may not lie — CLAUDE.md hard rule 6.")
    if not args.fix:
        print("Run with --fix to repair cut nerves and stale statuses.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
