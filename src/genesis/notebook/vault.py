# Spec: Genesis Markdown/60-UI/Notebook.md
"""A vault is a directory. That is the whole storage layer.

[[Notebook]] argues the case; the short version is that a notebook note is a
*file*, not a record, so the questions asked of it are ``os.walk``,
``read_text`` and one regex. A database here would be a second copy of prose
that already exists on disk, and it would be wrong the first time somebody
opened the vault in Obsidian -- which they will, because it is a real Obsidian
vault.

It also settles *"Genesis populates the notes"* for nothing: the default vault
is ``config.memory.vault_path``, which the research family already writes into.
One vault, two writers, no sync.

**The one place nothing is lazy is path handling.** Everything below that takes
a path takes it from the browser, and a vault is a directory of the operator's
real files. :meth:`Vault.resolve` is the only door: it joins, resolves symlinks,
and refuses anything that lands outside the root. Nothing in this module opens
a path that did not come through it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from genesis.errors import FatalError, GenesisError

__all__ = ["Entry", "Note", "Vault", "VaultRegistry"]

#: Directories that are never part of a vault's content.
SKIP_DIRS = {".obsidian", ".trash", ".git", "__pycache__", "node_modules"}

#: Everything else is an attachment: listed, never opened as text.
MARKDOWN = {".md", ".markdown"}


# ---------------------------------------------------------------------------
# the registry -- which directories are vaults
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class VaultRef:
    name: str
    path: Path

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "path": str(self.path), "exists": self.path.is_dir()}


class VaultRegistry:
    """The list of known vaults, in one JSON file beside the memory database.

    Obsidian keeps its vault list in its own config; so does this. Not in
    ``config.yaml``, because adding a vault is a thing you do at 2pm on a
    Tuesday and editing validated system config to do it is absurd.

    Seeded from ``memory.vault_path`` on first read, so the list is never empty
    and the module is never a setup wizard.
    """

    def __init__(self, path: Path, *, default: Path | None = None) -> None:
        self.path = Path(path).expanduser()
        self.default = Path(default).expanduser() if default else None

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = {}
        vaults = [v for v in data.get("vaults", []) if isinstance(v, dict) and v.get("path")]
        if not vaults and self.default is not None:
            vaults = [{"name": self.default.name or "Genesis", "path": str(self.default)}]
        active = data.get("active") or (vaults[0]["name"] if vaults else None)
        return {"vaults": vaults, "active": active}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))

    def list(self) -> list[VaultRef]:
        return [VaultRef(v["name"], Path(v["path"]).expanduser()) for v in self._read()["vaults"]]

    def active(self) -> VaultRef:
        data = self._read()
        refs = self.list()
        if not refs:
            raise FatalError(
                "no vault configured and memory.vault_path is unset — "
                "add one, or set memory.vault_path in config.yaml"
            )
        for ref in refs:
            if ref.name == data["active"]:
                return ref
        return refs[0]

    def open(self, name: str | None = None) -> Vault:
        if name:
            for ref in self.list():
                if ref.name == name:
                    return Vault(ref.path, name=ref.name)
            raise GenesisError(f"no vault named {name!r}")
        ref = self.active()
        return Vault(ref.path, name=ref.name)

    def add(self, name: str, path: Path, *, create: bool = True) -> VaultRef:
        target = Path(path).expanduser()
        if create:
            target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            raise GenesisError(f"not a directory: {target}")
        data = self._read()
        data["vaults"] = [v for v in data["vaults"] if v["name"] != name]
        data["vaults"].append({"name": name, "path": str(target)})
        data["active"] = name
        self._write(data)
        return VaultRef(name, target)

    def select(self, name: str) -> VaultRef:
        data = self._read()
        if not any(v["name"] == name for v in data["vaults"]):
            raise GenesisError(f"no vault named {name!r}")
        data["active"] = name
        self._write(data)
        return next(r for r in self.list() if r.name == name)

    def forget(self, name: str) -> None:
        """Remove from the list. Deletes nothing on disk, ever."""
        data = self._read()
        data["vaults"] = [v for v in data["vaults"] if v["name"] != name]
        if data["active"] == name:
            data["active"] = data["vaults"][0]["name"] if data["vaults"] else None
        self._write(data)


# ---------------------------------------------------------------------------
# entries and notes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Entry:
    """One row of the tree: a folder, a note, or an attachment."""

    path: str          # vault-relative, forward slashes, '' for the root
    name: str
    kind: str          # folder | note | attachment
    modified: str | None = None
    size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("path", "name", "kind", "modified", "size")}


@dataclass(frozen=True, slots=True)
class Note:
    path: str
    name: str
    body: str
    modified: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("path", "name", "body", "modified", "size")}


# ---------------------------------------------------------------------------
# the vault
# ---------------------------------------------------------------------------

class Vault:
    """A directory of markdown, read and written through one safe door."""

    def __init__(self, root: Path, *, name: str = "") -> None:
        self.root = Path(root).expanduser()
        self.name = name or self.root.name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Vault({self.name!r}, {self.root})"

    @property
    def exists(self) -> bool:
        return self.root.is_dir()

    def require(self) -> None:
        if not self.exists:
            raise FileNotFoundError(str(self.root))

    # -- the safe door ----------------------------------------------------

    def resolve(self, rel: str, *, must_exist: bool = False, markdown: bool = False) -> Path:
        """Vault-relative string in, absolute path inside the root out.

        Symlinks are resolved **before** the containment check, so a symlink
        pointing out of the vault is refused rather than followed. ``..`` never
        survives ``resolve()``. A write path is additionally required to be
        markdown, because the notebook has no business overwriting a PDF.
        """
        cleaned = str(rel or "").strip().lstrip("/")
        if "\x00" in cleaned:
            raise GenesisError("invalid path")
        root = self.root.resolve()
        target = (root / cleaned).resolve()
        if target != root and root not in target.parents:
            raise GenesisError(f"path escapes the vault: {rel!r}")
        if markdown and target.suffix.lower() not in MARKDOWN:
            raise GenesisError(f"not a markdown file: {rel!r}")
        if must_exist and not target.exists():
            raise FileNotFoundError(cleaned)
        return target

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    # -- reading ----------------------------------------------------------

    def tree(self, rel: str = "") -> list[Entry]:
        """One level. Folders first, then alphabetically, case-insensitively.

        Deliberately not recursive: a vault with four thousand notes must not
        cost four thousand rows to draw a sidebar showing six things.
        """
        self.require()
        directory = self.resolve(rel, must_exist=True)
        if not directory.is_dir():
            raise GenesisError(f"not a folder: {rel!r}")
        out: list[Entry] = []
        for child in directory.iterdir():
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            stat = child.stat()
            if child.is_dir():
                out.append(Entry(self.rel(child), child.name, "folder"))
            else:
                kind = "note" if child.suffix.lower() in MARKDOWN else "attachment"
                out.append(Entry(
                    self.rel(child), child.stem if kind == "note" else child.name, kind,
                    datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(), stat.st_size,
                ))
        out.sort(key=lambda e: (e.kind != "folder", e.name.lower()))
        return out

    def walk(self) -> Iterator[Path]:
        """Every markdown file in the vault, skipping the machinery."""
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
            for filename in files:
                if Path(filename).suffix.lower() in MARKDOWN:
                    yield Path(base) / filename

    def read(self, rel: str) -> Note:
        path = self.resolve(rel, must_exist=True, markdown=True)
        stat = path.stat()
        return Note(
            self.rel(path), path.stem, path.read_text(encoding="utf-8", errors="replace"),
            datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(), stat.st_size,
        )

    def search(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Substring over path and body, title matches first.

        ponytail: full scan per query. It is a few milliseconds over a personal
        vault. Swap to SQLite FTS if a vault ever passes ~5k notes and this
        shows up in a profile — the callers only need this signature back.
        """
        self.require()
        needle = query.strip().lower()
        if not needle:
            return []
        hits: list[tuple[int, dict[str, Any]]] = []
        for path in self.walk():
            rel = self.rel(path)
            in_title = needle in path.stem.lower()
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            found = body.lower().find(needle)
            if not in_title and found < 0:
                continue
            excerpt = ""
            if found >= 0:
                start = max(0, found - 48)
                excerpt = body[start:found + len(needle) + 96].replace("\n", " ").strip()
            hits.append((0 if in_title else 1, {
                "path": rel, "name": path.stem, "excerpt": excerpt,
            }))
        hits.sort(key=lambda h: (h[0], h[1]["path"].lower()))
        return [h[1] for h in hits[:limit]]

    # -- writing ----------------------------------------------------------

    def write(self, rel: str, body: str, *, by: str = "operator") -> Note:
        """Create or overwrite a note.

        ``by`` is recorded by callers that care (an agent), and deliberately not
        forced into frontmatter here: a notebook that demanded frontmatter would
        be a form, not a notebook.
        """
        path = self.resolve(rel, markdown=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return self.read(self.rel(path))

    def create(self, rel: str, body: str = "") -> Note:
        """Create, refusing to clobber. This is what a link click calls."""
        path = self.resolve(rel, markdown=True)
        if path.exists():
            raise GenesisError(f"already exists: {self.rel(path)}")
        return self.write(self.rel(path), body)

    def append(self, rel: str, text: str) -> Note:
        """Add to the end of a note, creating it if absent. `note that ...`."""
        path = self.resolve(rel, markdown=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        joiner = "" if not existing or existing.endswith("\n") else "\n"
        return self.write(self.rel(path), f"{existing}{joiner}{text.rstrip()}\n")

    def mkdir(self, rel: str) -> Entry:
        path = self.resolve(rel)
        path.mkdir(parents=True, exist_ok=True)
        return Entry(self.rel(path), path.name, "folder")

    def delete(self, rel: str) -> str:
        """Remove a note, or an empty folder. Never a folder with content."""
        path = self.resolve(rel, must_exist=True)
        if path == self.root.resolve():
            raise GenesisError("cannot delete the vault root")
        if path.is_dir():
            if any(path.iterdir()):
                raise GenesisError(f"folder is not empty: {rel}")
            path.rmdir()
        else:
            path.unlink()
        return self.rel(path) if path.exists() else str(rel).strip().lstrip("/")

    def move(self, src: str, dst: str) -> str:
        """Rename or move. Link rewriting is the caller's job — see links.py.

        Kept separate on purpose: rewriting the human's own prose is a thing
        they must be shown before it happens, so the preview and the move are
        two calls rather than one helpful function that did both.
        """
        source = self.resolve(src, must_exist=True)
        target = self.resolve(dst)
        if target.exists():
            raise GenesisError(f"already exists: {self.rel(target)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        return self.rel(target)

    def daily_path(self, when: datetime | None = None) -> str:
        """Today's inbox note. `00-Inbox/` per [[Obsidian Vault Schema]]."""
        day = (when or datetime.now(UTC)).date().isoformat()
        return f"00-Inbox/{day}.md"


def registry() -> VaultRegistry:
    """The registry, with paths from config — never a hardcoded directory."""
    from genesis.config import load_config

    config = load_config()
    return VaultRegistry(
        Path(config.memory.db_path).expanduser().parent / "vaults.json",
        default=Path(config.memory.vault_path).expanduser(),
    )
