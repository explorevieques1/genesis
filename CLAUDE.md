# Genesis Agent

An agentic trading terminal. The trader commands it by typing or by speaking;
an orchestrator acts as their senior analyst and puts roughly 30 agents in five
families to work — over an always-on daemon, a five-layer memory fabric, and an
unbypassable pre-trade risk gate.

**The specification lives in `Genesis Markdown/` — an Obsidian vault.**
It is not background reading. It is the source of truth for what gets built.

---

## Genesis is built as an organism

Read `10-Architecture/Biological Design.md` before designing anything. It is the
organising metaphor for the whole system, and it changes what you build, not
just how you describe it.

**The LLM is one organ. The agent is the whole loop** — perception, memory,
rhythm, reflex, action, homeostasis. Most agent failures are not reasoning
failures; they are missing reflexes, memory that was never written, a tool that
lied about succeeding, or a loop with no circuit breaker. None of those are
fixed by a better prompt, so don't reach for one.

Three principles constrain code directly:

1. **The reflex arc.** The fast path never waits for the slow path. A limit
   check, a retry decision, a kill switch are *spinal* — deterministic code,
   sub-millisecond, incapable of hallucinating. `tier: none` components are not
   "agents without a model yet"; they are spinal cord, and giving one a model is
   the bug. **A reflex cannot be talked out of firing by a persuasive prompt** —
   which is the entire reason safety lives there and not in an instruction.
2. **Afferent ≠ efferent.** Read paths and write paths are structurally
   different, like sensory and motor nerves. Reads are cheap, safe, retryable,
   parallel. Writes need idempotency keys, authorisation, ordering, and complete
   audit. Never put them in one undifferentiated tool list.
3. **Proprioception before ambition.** Never build an actuator before the sense
   that verifies it acted. A system that can act but cannot perceive its own
   state is the dangerous configuration, and its failure mode — drift between
   believed and actual state — is the one that loses money *quietly*.

Four places the metaphor breaks, each a real constraint: weights are frozen (no
self-improvement — the feedback loop is explicit and runs outside the daemon);
amnesia is the default (continuity is manufactured, memory is a feature you
build); there is no self-preservation drive (the kill switch must be external and
outside the agent's control); process death is not cell death (one daemon dying
takes everything down).

**The metaphor is a heuristic, not an argument.** A design is not correct because
it is biological. Where it conflicts with `50-Risk/Safety Invariants.md`, the
invariants win.

When you add a component, place it on the map first: *which organ is this, and is
it reflex or judgement?* If it has no biological role, question whether it should
exist.

---

## The human commands. Genesis advises.

Read `10-Architecture/Operating Model.md` before building anything a person
touches. `Biological Design` says what kind of thing Genesis is; this says what
it is *for* and who is in charge of it.

Genesis is a research firm with one client, and the client owns it. The trader is
the **head trader** — they decide, they command, they own the P&L. The
orchestrator is the **senior analyst** — it takes a question, works out what
would answer it, puts the ~30 agents on it, and comes back with a briefing. The
agents are the staff. Build for *"I have thirty analysts on my desk"*, not
*"I have a chatbot with a terminal attached"*.

Four rules constrain code directly, and each has already been violated by
something that shipped:

1. **The parity rule.** Anything Genesis can do, a person can do by hand —
   through the same door, with the same audit line. A capability reachable only
   by saying a sentence and hoping the router picks it **is not shipped**. The
   reason is verification, not convenience: a system where the model reaches
   further than its operator is one where the operator cannot check its work.
2. **The canvas opens empty.** Nothing is on screen that was not asked for, by
   the human or by Genesis acting on the human's request — safety floor
   excepted. Discoverability lives in the command line, not in a pre-populated
   screen. A first screen full of unrequested telemetry teaches the operator
   that things appear on their own.
3. **Typed and spoken are one path.** Both hit the same command table and the
   same orchestrator behind it. Unplugging the microphone must remove no
   capability. Genesis drives the workspace through the *same* dock API the
   human does — one function, two callers, no private channel.
4. **Nobody knows the ticker.** "Nvidia" resolves to `NVDA` by deterministic
   lookup, never by asking a model. Ambiguity is surfaced, never guessed, and
   what got resolved is shown. Not everything is a symbol — "Gann" is a research
   subject.

Data that is merely *presented* is a Bloomberg panel. Genesis **collects,
computes and orchestrates** — an answer arrives with the work behind it
attached: who ran, on what data, as of when.

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
123 notes. `[[Note|display text]]` links to `Note`; the part after `|` is only a
label. Inside markdown tables the pipe is escaped as `\|`.

A note's **Related** line at the bottom is a curated list of what else matters
for that component. Treat it as the next-steps index, not decoration.

---

## Routing table

| If you are… | Read |
|---|---|
| Starting any session | `Genesis Markdown/Genesis Agent — Home.md` |
| Designing *anything* | `10-Architecture/Biological Design.md` — which organ, reflex or judgement? |
| Building anything a person touches | `10-Architecture/Operating Model.md` — who commands, who advises, parity rule |
| Deciding what to build next | `00-Meta/Build Order.md` |
| Building an agent | `20-Agents/<Family>/Agent — <Name>.md` — and only that one |
| Adding *any* new agent | `10-Architecture/Agent Contract.md` first |
| Touching orders, sizing, or fills | `50-Risk/Pre-Trade Risk Engine.md` + `50-Risk/Safety Invariants.md` — **non-negotiable** |
| Changing a data shape | `70-Schemas/` — authoritative, update in the same commit |
| Wiring a tool or MCP server | `30-MCP/MCP Gateway.md` |
| Writing anything that stores or recalls | `40-Memory/Memory Fabric.md` |
| Building UI | `10-Architecture/Operating Model.md` §3–5 first, then `60-UI/UI Stack.md`, `60-UI/Workspaces.md`, `60-UI/Terminal.md`, `60-UI/Widget Catalog.md` |
| Adding a command, a panel, or a tool surface | `60-UI/Terminal.md` — and check the parity rule holds both ways |
| Voice, wake word, TTS | `10-Architecture/Voice Stack.md` + `60-UI/Voice UX.md` |
| Picking a model tier | `10-Architecture/LLM Model Tiers.md` |
| Reusing prior work | `80-Repos/Repo Map.md` |
| Naming, style, file layout | `00-Meta/Conventions.md` |
| Deciding if something needs an LLM | `10-Architecture/Biological Design.md` §reflex arc + `10-Architecture/LLM Model Tiers.md` |
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

**Check it rather than trusting it:**

```bash
python3 scripts/check_body_map.py          # report drift, exit 1 if any
python3 scripts/check_body_map.py --fix    # repair cut nerves and stale statuses
```

It catches three things: code pointing at a note that does not point back, an
`implemented_by:` naming a file that no longer exists, and a status that
disagrees with whether any code exists. Run it before committing — the
discipline was held by hand until 2026-09-17, and by hand is how 65 notes
drifted.

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

6. **The body map may not lie.** Spec and code move in the same commit. Under
   `Biological Design` this is not tidiness — a note that describes an organ the
   system does not have is **proprioceptive drift**, and the system will then
   reason confidently about itself and be wrong. It ranks with reconciliation.

If a task seems to require breaking one of these, stop and say so.

---

## Trading corpus

31 open-source trading repos — the reference library for patterns and
implementations, **not code to paste**.

**Location: `corpus/` in this repo — a symlink to an external SSD**
(`/run/media/gzacc2002/Extreme SSD/Github Repos/Trading`). 22 GB, deliberately
not copied to the internal disk and not in git.

```bash
python3 scripts/check_corpus.py --paths   # is it mounted? do all citations resolve?
bash scripts/link_corpus.sh               # recreate the symlink after a remount
```

**If `corpus/` does not resolve, the drive is unplugged.** Say so and stop — do
not substitute a guess about what the code probably looks like.

- Read `INDEX.md` first; it points at specific files. Citations are
  **repo-relative**: under `### vectorbt`, the entry `vectorbt/portfolio/` means
  `corpus/vectorbt/vectorbt/portfolio/`.
- Delegate digging to the `trading-researcher` subagent. Ask for concrete file
  references and short snippets — never file dumps.
- Cite `repo/path/file.py` when you borrow an idea.
- **Never modify a repo under `corpus/`.** Read-only reference — enforced by a
  deny rule in `.claude/settings.json`.
- `80-Repos/Trading Corpus Index.md` maps each Genesis component to the corpus
  repo it should learn from.
- If a cited path has gone stale (upstream renamed it), **fix `INDEX.md`** rather
  than working around it, then re-run the checker.

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

## Running locally

`./genesis up` — daemon (detached) + vite. After editing Python, run
`./genesis reload`; nothing restarts on save. `./genesis logs | status | down`.

Two doors worth knowing, both parity twins of a UI surface:

```bash
genesis account [--reconcile]      # positions, heat, P&L, ledger vs broker
genesis memory stats | search "…" | consolidate | install-embedder
```

## Conventions

- Python for the core (see `00-Meta/Open Questions.md` §3 — not yet decided).
- Source under `src/genesis/`, tests mirroring it under `tests/`.
- Every module gets a spec pointer comment. See `00-Meta/Conventions.md`.
