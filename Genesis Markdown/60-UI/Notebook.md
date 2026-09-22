---
title: Notebook
tags: [ui, module, memory]
status: built
implemented_by: [src/genesis/notebook/vault.py, src/genesis/notebook/links.py, src/genesis/server/notebook_routes.py, ui/src/workspace/panels/notebook.tsx, src/genesis/notebook/__init__.py, tests/test_notebook.py]
---

# Notebook — `NOT`

Obsidian, inside Genesis. A vault of markdown files, a folder tree down the
side, `[[wikilinks]]` in the body, and a note that does not exist yet gets
created by clicking the link to it.

Home category: [[Workspaces|journal]]. Paired with [[Nodes]] (`NOD`), which
draws the links this module writes.

## Why it is not a database

**The vault is the store. There is no second copy.**

[[Research Directory]] made the opposite choice on purpose, and the reasoning
there does not transfer. A research note is a *record*: it has a subject, a
half-life, a confidence, a supersession chain, and the question asked of it is
*"which notes about semis are still inside their half-life"* — a query, so
SQLite is the record and the vault is the mirror.

A notebook note is a *file*. The questions asked of it are: what is in this
folder, what does this file say, what links to it. `os.walk`, `read_text`, and
one regex. Putting a notebook behind a database would produce a second copy of
prose that already exists on disk, and the first time someone edited the vault
in Obsidian — which they will, because it is a real Obsidian vault — the copy
would be wrong and nothing would say so.

It also settles the hardest requirement for free. *"Genesis should be able to
populate these notes"* needs no new mechanism at all: the research family
already writes `50-Research/**.md` into `memory.vault_path`, so those notes are
in the notebook the moment they are written. One vault, two writers, no sync.

**Default vault is `config.memory.vault_path`** — the vault [[Obsidian Vault
Schema]] describes. Not a new directory, and never a hardcoded `~/.genesis/`;
the store path comes from config like every other store.

## Vaults

A vault is a directory. Choosing one is choosing a directory, and the list of
known vaults is a JSON file beside the memory database:

```json
{ "vaults": [ { "name": "Genesis", "path": "~/GenesisVault" } ], "active": "Genesis" }
```

Seeded from config on first read, so the list is never empty and the module is
never a setup wizard. Adding a vault points at a directory that already exists
or creates it; removing one forgets the path and deletes nothing. A vault
Genesis writes to may be opened in Obsidian at the same time — nothing here
holds a lock or a cache that would make that unsafe.

## The tree

Folders and `.md` files, sorted folders-first then alphabetically, lazily —
one level per request, keyed by path. Not a whole-vault tree in one response: a
vault with four thousand notes should not cost four thousand rows to render a
sidebar with six things in it.

Non-markdown files are listed as attachments and are not openable here. Dot
directories and `.obsidian/` are skipped.

Create folder, create note, rename, move, delete. A rename is the one that is
not trivial — see *Renames* below.

Create sits above the search box; the vault picker sits at the foot of the
sidebar. Rename and delete are on a right-click menu on the row itself — the
same two calls the editor header makes, reached from the tree so a folder can
be renamed without opening anything. Deleting a non-empty folder is refused by
the vault and the refusal is shown on the row.

## Links

One syntax, Obsidian's, parsed by one regex and shared with [[Nodes]]:

| Written | Means |
|---|---|
| `[[Note]]` | link to the note |
| `[[Note\|shown]]` | link, displayed as *shown* |
| `[[Note#Heading]]` | link to a heading inside it |
| `[[Note#^block]]` | link to a block |
| `![[Note]]` | embed its content inline |
| `#tag` | a tag, which [[Nodes]] can show as a node |

**Resolution, in order:** the target as a vault-relative path (with `.md`
appended if absent); then the unique file whose basename matches; then, if
several match, the one nearest the linking note. No match at all is not an
error — it is an **unresolved link**, rendered dimmed, and clicking it creates
the note in the linking note's folder and opens it. That is Obsidian's
behaviour and it is the entire authoring loop: you write the link you wish
existed, then click it into being.

Ambiguity is surfaced, never guessed — the same rule [[Operating Model]] §4
applies to tickers. Two files named `Gann.md` in different folders, linked as
`[[Gann]]`, shows both and asks.

**Backlinks** are computed, not stored: which notes contain a link resolving to
this one. A full vault scan per request today.

> `ponytail: full-vault scan for backlinks and search. Cache the link index by
> directory mtime when a vault passes ~5k notes; SQLite FTS only if that is not
> enough.`

**Search** is substring over path, title and body, capped and ranked
title-first. Same upgrade path.

## Renames

Renaming a note breaks every `[[link]]` to it. Obsidian rewrites them; so does
this, and the rewrite is shown before it happens: *"renaming `Gann.md` updates
7 links in 5 notes"*, with the list. Nothing is rewritten silently, because a
bulk edit of the human's own prose is exactly the thing that must not happen
without them seeing it.

## What the human writes and what Genesis writes

Both go through the same routes. There is no private channel for the agent —
[[Operating Model]] §3. An agent-written note carries frontmatter naming its
writer and trace; a human note need carry nothing at all, and a notebook that
demanded frontmatter would be a form, not a notebook.

The conflict rule is [[Obsidian Vault Schema]]'s and unchanged: **your edit
wins**. An agent appends to its own section and never overwrites human prose.

## Safety

The one hard boundary is path handling, and it is not lazy anywhere. Every path
arriving from the browser is joined to the vault root, resolved, and checked to
be inside it; symlinks are resolved before the check, `..` never survives it,
and writes are `.md` only. A vault is a directory of the operator's real files
and a path traversal here writes anywhere they can write.

Nothing in this module is efferent in the trading sense. It reaches no order
path, no broker, no gate.

## Commands

Parity both ways ([[Operating Model]] §1) — every one of these is also a button:

| Say or type | Does |
|---|---|
| `note` / `NOT` | open the notebook |
| `note <title>` | create it, open it |
| `open note <title>` | find and open |
| `note that <text>` | append to today's daily note in `00-Inbox/` |
| `search notes <text>` | open the notebook filtered |

Deterministic patterns in `commands.py`, `tier: none`. Nothing here is a
judgement, so nothing here gets a model.

## Acceptance criteria

- A note written by the research family appears in the tree with no import step.
- `[[New note]]` clicked creates `New note.md` beside the linking note, and the
  link stops being dimmed.
- Editing the vault in Obsidian and reloading the panel shows the edit.
- A path containing `..` or a symlink out of the vault is refused, by test.
- Renaming a linked note updates its backlinks and shows what it changed first.
- A vault of 5,000 notes opens a folder in under 100 ms.

## Related

[[Nodes]] · [[Obsidian Vault Schema]] · [[Research Directory]] ·
[[Memory Fabric]] · [[Workspaces]] · [[Terminal]] · [[Operating Model]]
