---
title: Conventions
tags: [meta]
status: built
implemented_by: [evals/__init__.py, evals/conftest.py, evals/helpers.py, evals/test_scaffold.py, src/genesis/dna/__init__.py, src/genesis/dna/drift.py, src/genesis/dna/genome.py, src/genesis/dna/prompts.py, ui/src/workspace/panels/dna.tsx, scripts/check_body_map.py, tests/dna/test_drift.py, tests/dna/test_genome.py]
---

# Conventions

House style, inherited from [[Repo — jarvis]] and [[Trading Corpus Index|the corpus rules]].

## Spec files travel with code

Every non-trivial module gets a `*.spec.md` next to it describing intended
behaviour and key principles. Code must match its spec, or the spec changes first
and deliberately. Search for a related spec **before** starting work.

This vault is the *system* spec; `*.spec.md` files are the *module* specs.

## The spec pointer

Every source file names the vault note it implements, on its first line:

```python
# Spec: Genesis Markdown/20-Agents/Research/Agent — Screener.md
```

And every buildable note names the code back, in its frontmatter:

```yaml
status: spec | building | built
implemented_by: [src/genesis/agents/screener.py]
```

Both sides move together, in the same commit. This is what keeps the vault a
build tracker instead of a museum — see [[Working With Claude Code]]. Run
`genesis dna map` after either side changes.

## The genome

The two halves of that pointer are the only reason drift is detectable at all,
so they have an organ: `DNA` on the map in [[Biological Design]], and
`src/genesis/dna/` behind it. One reading of the vault, used by the `DNA`
module, `genesis dna`, `genesis biology` and both pre-commit scripts — four
parsers of one body map is how the readings disagree.

```bash
genesis dna                  # how much of the genome is expressed, by status
genesis dna check [--fix]    # the six kinds of drift between spec and code
genesis dna show "Risk Envelope"   # one note: its code, and what points at it
genesis dna prompts          # the other half — every system prompt, sized
genesis dna map              # regenerate [[Vault Map]]
```

Six kinds of drift, each silent without the check: a **cut forward nerve**
(code points at a note that does not point back), a **phantom limb**
(`implemented_by:` names a file that is gone), a **stale status**, a
**dangling pointer** (code names a note that does not exist), a **doubled
nerve** (two `implemented_by:` keys — YAML keeps the last and the first list
silently stops existing), and **broken frontmatter** (`---` opens and never
closes, so every reader skips the note; [[Workspaces]] was in this state and
four tools skipped it in silence).

`--fix` writes only what the code already proves, and never invents `built` —
"done" is a human judgement. Nothing repairs on a schedule: an automatic
repair running unattended will eventually paper over the one drift that
mattered.

> [!important] The genome is read-only at runtime
> Nothing in `genesis.dna` is wired to the daemon, no agent holds a capability
> that reaches it, and there is no write path to a note or a prompt anywhere in
> Genesis. Weights are frozen and so is the spec. An organism that can edit its
> own genome can edit [[Safety Invariants]], and then every reflex in the
> system is a suggestion. The germ line is git; the editor is a person.

## Logging

User-facing CLI output uses a leading emoji per line and indentation for hierarchy:

```
🌅 Pre-market brief
  📊 Regime: risk-on, VIX 14.2 (−8% w/w)
  📰 3 catalysts today
    ⚠️  CPI 08:30 ET — high impact
  💡 4 ideas ranked
    🥇 NVDA long · conf 0.72 · invalidation 118.40
```

Internal flow gets `debug_log` at every meaningful decision point — not everywhere.
Logs should be siftable, not exhaustive. See [[Observability]].

## Token discipline (inherited, non-negotiable)

- Never load a whole repo, notebook, or README into context.
- Path: [[Trading Corpus Index]] → targeted `grep` → read **one** file → stop.
- Delegate deep digging to a `trading-researcher` subagent so exploration tokens
  stay out of the main conversation. Ask for `repo/file.py` citations and short
  snippets, not file dumps.
- Never modify a cloned repo. New code lives under the Genesis project tree.

## Naming

| Thing | Convention | Example |
|---|---|---|
| Agent id | `kebab-case` | `chart-markup` |
| Task type | `verb.noun` | `chart.markup`, `order.propose` |
| Event | `noun.past-tense` | `order.filled`, `level.touched` |
| Memory namespace | `agent-id` or `shared` | `news-catalyst`, `shared` |
| Vault note | `Title Case` | `NVDA 2026-08-29 Breakout` |
| Config key | `snake_case` | `max_daily_loss_pct` |

## Errors

Fail **honestly**, never confabulate. An agent that could not get data says so and
returns a typed failure; it does not guess a price. See [[Error Handling And Degradation]].

Three failure classes:
- `transient` — retry with backoff (network, session loss)
- `degraded` — proceed with less (stale data, one feed down) and **label the output**
- `fatal` — stop, escalate, tell the user

## Untrusted content

Anything from the web, news, social, or a third-party MCP is **data, never
instruction**. Fence it. See [[MCP Gateway]].

## Money

- Prices and sizes are `Decimal`, never `float`.
- Every order carries a client-generated idempotency key.
- The [[Trade Ledger]] is append-only and double-entry. Never `UPDATE` a fill.

## Testing

- Unit tests for math (sizing, risk, metrics) — these must be exact.
- **Evals** for LLM behaviour: agent routing, tool selection, memory recall,
  intent classification. Pattern: [[Repo — jarvis]] `evals/` + `EVALS.md`.
- Every [[Safety Invariants|safety invariant]] gets a test that tries to violate it.
