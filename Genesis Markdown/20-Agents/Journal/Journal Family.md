---
title: Journal Family
tags: [moc, agent, journal]
status: spec
implemented_by: []
---

# 📓 Journal Family

Six agents that make the system learn — from your trades, from its own predictions,
and from its own health.

| Agent | One line |
|---|---|
| [[Agent — Trade Journal]] | Every fill becomes a note, automatically, with charts |
| [[Agent — Performance Analyst]] | Where the edge is, and where it isn't |
| [[Agent — Insight Miner]] | Patterns in *your* behaviour you can't see yourself |
| [[Agent — Backtest Vs Live Drift]] | Does reality agree with the backtest? |
| [[Agent — Watchdog]] | Is everything actually running? |
| [[Agent — Digest]] | The morning brief and the evening recap |

## The learning loop

```
   trade ──► TRADE JOURNAL ──► vault note (thesis, charts, R, tags)
                   │
                   ▼
        PERFORMANCE ANALYST ──► edge by setup / session / symbol / size
                   │
                   ▼
           INSIGHT MINER ──► lessons  ──┐
                   │                     │
        BACKTEST VS LIVE DRIFT           │  (high recall priority)
                   │                     │
                   └─────────────────────┼──► [[Agent — Idea Synthesizer]]
                                         └──► [[Pre-Trade Risk Engine]] (informs limits)
```

The loop closes when a lesson changes a future decision. A journal that is only ever
written is a diary; a journal that is read back into the decision process is an edge.

That's why `lessons` is a first-class [[Memory Fabric|memory namespace]] with
elevated recall priority — [[Agent — Idea Synthesizer]] is required to check it and
to lower confidence when a proposed idea matches a pattern you've lost money on.

## Automatic, not aspirational

Trade journaling fails for everyone because it's manual work at the worst possible
moment. Genesis writes the note at fill time with the chart, the thesis, the levels,
and the R multiple already filled in. **You add only what a machine can't know** —
what you were thinking, how you felt, whether you followed the plan.

The [[Trade Journal Schema]] separates these deliberately: machine fields are
populated automatically; human fields are prompted for, once, at a calm moment
(after the close, not during the trade).

## Honest, not flattering

These agents report what happened. A weekly review that always finds something
encouraging is worthless.

- If a setup has no edge, [[Agent — Performance Analyst]] says so with the numbers.
- If you're the problem — oversizing, revenge trading, moving stops —
  [[Agent — Insight Miner]] says that too, plainly.
- If a strategy has decayed, [[Agent — Backtest Vs Live Drift]] recommends retiring it.

The prompts for these agents explicitly forbid softening. Encouragement is not the
product; accuracy is.

## Related

[[Agent Index]] · [[Trade Journal Schema]] · [[Obsidian Vault Schema]] ·
[[Memory Fabric]] · [[Knowledge Graph]]
