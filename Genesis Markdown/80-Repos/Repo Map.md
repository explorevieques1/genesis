---
title: Repo Map
tags: [repo, moc]
---

# Repo Map

Everything relevant on this machine, and what each contributes to Genesis.

| Path | Role | Note |
|---|---|---|
| `/home/gzacc2002/Projects/Genesis Agent/` | **This project.** Corpus index + this vault. | [[Trading Corpus Index]] |
| `/home/gzacc2002/Work/jarvis/` | Voice-assistant reference architecture | [[Repo — jarvis]] |
| `/home/gzacc2002/Projects/gensis-agents/` | "Trading OS" prototype — orchestrator + agent base + alert agent | [[Repo — gensis-agents]] |
| `/home/gzacc2002/Projects/Gensis Terminal Official/` | Widget-grid terminal UI, Electron | [[Repo — Gensis Terminal Official]] |
| `/home/gzacc2002/Projects/Lithium Codebase/` | Local-first knowledge base + hybrid search + MCP (Rust) | [[Repo — Lithium Codebase]] |
| `/home/gzacc2002/Projects/Nautilus/nautilus_trader/` | Vendored nautilus_trader | execution/risk/portfolio patterns |
| `/home/gzacc2002/Projects/backtrader-ide/` | Node — backtrader IDE | charting/IDE patterns |
| `/home/gzacc2002/Projects/pine-forge/` | Node — Pine tooling | PineScript generation |
| `/home/gzacc2002/Projects/red_diamond/` | Node | adjacent; UI components |
| `/home/gzacc2002/Projects/Vieques AI/`, `Vieques-AI/` | Node | adjacent |
| `/home/gzacc2002/Projects/Zillow Sheets/`, `Cyber Safely/` | | unrelated to Genesis |

## What Genesis takes from each

```
     jarvis ────────► the orchestrator shell
                      (listening, planner, tool registry + selection,
                       MCP runtime, memory graph, recall gate, TTS,
                       desktop app, evals harness)

  gensis-agents ────► the agent fleet
                      (orchestrator dashboard, agent-base contract,
                       task queue, alert agent condition builder,
                       PineScript compilation)

 Gensis Terminal ──► the UI
                      (widget grid, price chart, trade calendar,
                       account stats, consistency calc, Obsidian
                       vault prompt, design system)

   Lithium ────────► retrieval
                      (corpus indexing, hybrid search, MCP server —
                       already built, in Rust, local)

  Nautilus ────────► execution correctness
                      (order lifecycle, pre-trade risk, portfolio
                       accounting)

  the corpus ──────► the math
                      (vectorbt, freqtrade, empyrical, Riskfolio,
                       PyPortfolioOpt, qlib, TradingAgents, PropForge)
```

## The reuse principle

Four of these repos already solve problems Genesis has. Before writing a component,
check whether one of them has it:

| Need | Look at |
|---|---|
| Wake word, intent, barge-in, echo | jarvis `listening/` |
| Tool registry without context rot | jarvis `tools/selection.py` |
| Persistent MCP sessions | jarvis `tools/external/mcp_runtime.py` |
| Memory graph + recall gate | jarvis `memory/` |
| Agent base class, task queue | gensis-agents `shared/` |
| Condition builder, PineScript | gensis-agents `agents/alert-agent/` |
| Any dashboard widget | Gensis Terminal `widgets/` |
| Corpus search | Lithium |
| Order lifecycle, risk engine | Nautilus |
| Any risk or performance formula | empyrical, Riskfolio, PyPortfolioOpt |

## The rule that applies to all of them

From [[Trading Corpus Index]] and inherited into [[Conventions]]:

> Never load a whole repo, notebook, or README into context. Index → targeted grep →
> read one file → stop. Delegate deep digging to a subagent. **Never modify a cloned
> repo** — new code lives in the Genesis project tree.

## Related

[[Trading Corpus Index]] · [[Repo — jarvis]] · [[Repo — gensis-agents]] ·
[[Repo — Gensis Terminal Official]] · [[Repo — Lithium Codebase]] · [[Build Order]]
