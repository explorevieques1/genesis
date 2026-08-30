# Genesis Agent

A voice-driven, multi-agent autonomous trading system. Roughly 30 agents in five
families, an always-on daemon, a five-layer memory fabric, and an unbypassable
pre-trade risk gate.

**The specification lives in `Genesis Markdown/` — an Obsidian vault, 91 notes.**
It is not background reading. It is the source of truth for what gets built.

---

## The vault is the brain. Read it before you write.

Three rules, in order of importance.

### 1. The spec wins

If code and its note disagree, the code is wrong — *or* the design genuinely
changed, in which case **update the note first, in the same commit**. Never let
them drift silently. A spec that lies is worse than no spec.

### 2. Read the note for the thing you are building. Not the vault.

57,000 words will not fit and should not try. Route with the table below, read
one or two notes, stop. If you need breadth rather than depth, delegate to the
`vault-librarian` subagent so exploration tokens stay out of this conversation.

### 3. Wikilinks are real files

`[[Risk Envelope]]` is a note at a real path. Note names are unique, so resolve
with `Glob **/Risk Envelope.md`, or look it up in
`Genesis Markdown/00-Meta/Vault Map.md` — a generated name → path table for all
91 notes. `[[Note|display text]]` links to `Note`; the part after `|` is only a
label. Inside markdown tables the pipe is escaped as `\|`.

A note's **Related** line at the bottom is a curated list of what else matters
for that component. Treat it as the next-steps index, not decoration.

---

## Routing table

| If you are… | Read |
|---|---|
| Starting any session | `Genesis Markdown/Genesis Agent — Home.md` |
| Deciding what to build next | `00-Meta/Build Order.md` |
| Building an agent | `20-Agents/<Family>/Agent — <Name>.md` — and only that one |
| Adding *any* new agent | `10-Architecture/Agent Contract.md` first |
| Touching orders, sizing, or fills | `50-Risk/Pre-Trade Risk Engine.md` + `50-Risk/Safety Invariants.md` — **non-negotiable** |
| Changing a data shape | `70-Schemas/` — authoritative, update in the same commit |
| Wiring a tool or MCP server | `30-MCP/MCP Gateway.md` |
| Writing anything that stores or recalls | `40-Memory/Memory Fabric.md` |
| Building UI | `60-UI/Dashboard.md`, `60-UI/Widget Catalog.md` |
| Voice, wake word, TTS | `10-Architecture/Voice Stack.md` + `60-UI/Voice UX.md` |
| Picking a model tier | `10-Architecture/LLM Model Tiers.md` |
| Reusing prior work | `80-Repos/Repo Map.md` |
| Naming, style, file layout | `00-Meta/Conventions.md` |
| Blocked on a design decision | `00-Meta/Open Questions.md` — ask, don't guess |

---

## Bidirectional binding

Every source file opens with a spec pointer:

```python
# Spec: Genesis Markdown/20-Agents/Research/Agent — Screener.md
```

Every buildable note carries the reverse in its frontmatter:

```yaml
status: spec | building | built
implemented_by: [src/genesis/agents/screener.py]
```

When you finish a component, **update both sides** and run
`python3 scripts/build_vault_map.py`. The vault then doubles as a live build
tracker — `00-Meta/Vault Map.md` shows at a glance what is spec, what is in
flight, and what is done.

---

## Hard rules

These come from `50-Risk/Safety Invariants.md`, which states each one with its
violation test. Summarised here because they constrain code you might write
before you think to open that note:

1. **No order reaches a broker without passing the pre-trade risk engine.** Not a
   policy — a structure. There is no `place_order` tool. Only
   `propose_order` → approval → `place_approved`, with signed, single-use,
   order-bound tokens.
2. **The risk engine fails closed.** Uncertain input, missing data, exception →
   reject. Never "assume fine and continue".
3. **Nothing safety-critical or arithmetic runs on an LLM.** The whole execution
   family, plus backtest, metrics, allocation and level-watch, are `tier: none`.
   A language model never sizes a position or computes a stop.
4. **The kill switch is a separate process** and must work when everything else
   is broken.
5. **Default approval mode is `confirm`.** Never ship a default that trades
   unattended.

If a task seems to require breaking one of these, stop and say so.

---

## Trading corpus

`INDEX.md` is a curated index of open-source trading repos — the reference
library for patterns and implementations, **not code to paste**.

- Read `INDEX.md` first; it points at specific `repo/path/file.py` entries.
- Delegate digging to the `trading-researcher` subagent. Ask for concrete file
  references and short snippets — never file dumps.
- Cite `repo/path/file.py` when you borrow an idea.
- **Never modify a cloned repo.** They are read-only reference.
- `80-Repos/Trading Corpus Index.md` maps each Genesis component to the corpus
  repo it should learn from.

⚠️ **Most of the corpus is not cloned on this machine yet.** Only
`~/Projects/Nautilus/` is present. Before relying on an `INDEX.md` path, check it
exists. `bash build_index.sh` regenerates `INDEX.auto.md` after cloning.

---

## Layout

```
Genesis Agent/
├── CLAUDE.md              you are here — the router
├── ARCHITECTURE.md        the original single-file design doc
├── INDEX.md               trading corpus index (curated)
├── Genesis Markdown/      the vault — THE SPEC
├── scripts/               vault map + frontmatter maintenance
└── .claude/
    ├── agents/            vault-librarian, trading-researcher
    └── commands/          /spec, /impl
```

## Conventions

- Python for the core (see `00-Meta/Open Questions.md` §3 — not yet decided).
- Source under `src/genesis/`, tests mirroring it under `tests/`.
- Every module gets a spec pointer comment. See `00-Meta/Conventions.md`.
