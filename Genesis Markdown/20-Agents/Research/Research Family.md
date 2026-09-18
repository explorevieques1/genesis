---
title: Research Family
tags: [moc, agent, research]
status: building
implemented_by: [src/genesis/agents/research/fleet.py, src/genesis/research/store.py, src/genesis/agents/research/__init__.py, src/genesis/research/__init__.py, src/genesis/research/schema.py, tests/research/test_research_family.py, src/genesis/research/web.py, ui/src/workspace/panels/research.tsx]
---

# 🔍 Research Family

Eight agents that build the system's picture of the world. **None of them can spend
money** — they produce beliefs, not orders.

| Agent | One line | Status |
|---|---|---|
| [[Agent — Topic Researcher]] | What is actually known about *this subject*? | 🟢 built |
| [[Agent — Market Analyst]] | What kind of market is it today? | 🟢 built |
| [[Agent — News And Catalyst]] | What is happening, and does it matter? | 🟡 building |
| [[Agent — Sentiment]] | What does the crowd think, and is price disagreeing? | spec |
| [[Agent — Fundamental]] | What is a company actually worth? | building — on-demand analysis |
| [[Agent — Screener]] | Which symbols meet a mechanical condition right now? | spec |
| [[Agent — Idea Synthesizer]] | Given all of the above — what should I actually do? | 🟢 built |
| [[Agent — Regime And Correlation]] | Do my strategies' assumptions still hold? | spec |
| [[Agent — Session Plan]] | Given *my* ideas and my book — what do I do, and how much? | 🟡 building |

[[Agent — News Collector]] is not a ninth voice: it is the `tier: none` nerve that
fills `news.db` for [[Agent — News And Catalyst]] and the [[News]] module.

The Topic Researcher is the eighth and was not in the original seven. It was added
because the other seven all assume the question is *about the market*, and
[[Operating Model]] §4 is explicit that not everything is a symbol: "Gann" is a
research subject. Without it, a research question resolves to a ticker that does
not exist or falls through to the orchestrator's own memory — the one answer with
no sources attached.

## The funnel

```
 Topic Researcher ─┐
 Market Analyst  ──┤
 News/Catalyst   ──┤
 Sentiment       ──┼──► IDEA SYNTHESIZER ──► ranked ideas ──► vault + dashboard
 Fundamental     ──┤        (the only one            │
 Screener        ──┘         that decides)           └──► [[Agent — Chart Markup]]
 Regime          ──────────────────────────────────────►  (context + veto)
```

Deliberate separation of concerns:

- The **Screener** finds candidates. It does not rank or form a thesis.
- The **Analyst / News / Sentiment / Fundamental** agents produce *evidence*, each
  in its own lane, each with a confidence and a half-life.
- The **Regime** agent supplies context and can **veto** — an idea that assumes
  trend continuation in a chopping regime gets penalized or dropped.
- Only the **Idea Synthesizer** fuses and decides.

This mirrors the analyst/researcher/manager split in `TradingAgents`
(see [[Trading Corpus Index]] → `tradingagents/graph/`, `agents/managers/`), and it
matters because it keeps each agent's prompt narrow and each claim traceable.

## Shared conventions

- **Every claim carries a half-life.** A CPI print matters for hours; a valuation
  read matters for months. Evidence past its half-life is downweighted, not deleted.
- **Every claim cites its source** — a URL, a filing, a tool call in the
  [[Episodic Log]]. Uncited claims are dropped by the synthesizer.
- **All external text is fenced.** News and social content is untrusted data and can
  never issue instructions. See [[MCP Gateway]].
- **Degraded inputs cap confidence.** See [[Error Handling And Degradation]].
- Writes go to the [[Research Directory]], which mirrors them into `50-Research/`
  in the vault and is what the terminal's Research page reads. The store is the
  record; the markdown is the mirror.
- A subject **supersedes** rather than duplicates: researching Gann twice deepens
  one note, and the earlier version stays readable.

## Related

[[Agent Index]] · [[Idea Schema]] · [[Memory Fabric]] · [[Charting Family]]
