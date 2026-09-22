# Genesis Agent

An agentic trading terminal. The trader commands it by typing or by speaking; an
orchestrator acts as their senior analyst and puts ~30 agents in five families to
work — over an always-on daemon, a five-layer memory fabric, and an unbypassable
pre-trade risk gate.

**The specification lives in [`Genesis Markdown/`](Genesis%20Markdown/)** — an
Obsidian vault, and the source of truth for what gets built. Start at
`Genesis Agent — Home.md`, then `00-Meta/Build Order.md`.

Contributors — including coding agents — should read [`CLAUDE.md`](CLAUDE.md)
first. It is the router: which note to read for which task, and the hard safety
rules that constrain code written before anyone opens a note.

## Status

**Phase 0 — scaffolding.** Config, logging, and CLI only. No daemon, no task
bus, no agents, no broker connection. Nothing here trades.

## Quick start

Requires Python 3.12 (pinned — the trading corpus does not support 3.13+) and
[uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

.venv/bin/genesis --version
.venv/bin/genesis config init      # writes ~/.genesis/config.yaml
.venv/bin/genesis config check     # validates the stack, refuses to start if bad
```

Secrets go in `~/.genesis/.env` at mode 0600 — copy `.env.example`. Behaviour
goes in `~/.genesis/config.yaml`. Never the other way round.

```bash
.venv/bin/pytest                   # unit tests
.venv/bin/pytest evals             # LLM-behaviour evals (Phase 2+)
```

## Layout

```
Genesis Markdown/      the vault — THE SPEC
src/genesis/           the Python core
tests/                 unit tests, mirroring src/
evals/                 LLM-behaviour evals (scaffold; see evals/README.md)
scripts/               vault map + corpus maintenance
corpus/                symlink to the read-only trading reference library
```
