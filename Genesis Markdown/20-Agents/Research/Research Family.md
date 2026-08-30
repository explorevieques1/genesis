---
title: Research Family
tags: [moc, agent, research]
status: spec
implemented_by: []
---

# 🔍 Research Family

Seven agents that build the system's picture of the world. **None of them can spend
money** — they produce beliefs, not orders.

| Agent | One line |
|---|---|
| [[Agent — Market Analyst]] | What kind of market is it today? |
| [[Agent — News And Catalyst]] | What is happening, and does it matter? |
| [[Agent — Sentiment]] | What does the crowd think, and is price disagreeing? |
| [[Agent — Fundamental]] | What is a company actually worth? |
| [[Agent — Screener]] | Which symbols meet a mechanical condition right now? |
| [[Agent — Idea Synthesizer]] | Given all of the above — what should I actually do? |
| [[Agent — Regime And Correlation]] | Do my strategies' assumptions still hold? |

## The funnel

```
 Market Analyst ──┐
 News/Catalyst  ──┤
 Sentiment      ──┼──► IDEA SYNTHESIZER ──► ranked ideas ──► vault + dashboard
 Fundamental    ──┤        (the only one            │
 Screener       ──┘         that decides)           └──► [[Agent — Chart Markup]]
 Regime         ──────────────────────────────────────►  (context + veto)
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
- Writes go to `50-Research/` in the vault and the `shared` memory namespace.

## Related

[[Agent Index]] · [[Idea Schema]] · [[Memory Fabric]] · [[Charting Family]]
