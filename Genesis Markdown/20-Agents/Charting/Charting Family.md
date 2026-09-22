---
title: Charting Family
tags: [moc, agent, charting]
status: built
implemented_by: [src/genesis/agents/charting/__init__.py, src/genesis/agents/charting/fleet.py, tests/charting/test_agents.py, src/genesis/charting/outcomes.py, tests/charting/conftest.py, tests/journal/test_question_catalogue.py, evals/charting_questions.yaml]
---

# 📈 Charting Family

Four agents that turn price data into structured, re-renderable beliefs about a chart.

| Agent | One line |
|---|---|
| [[Agent — Chart Markup]] | Compute the levels and produce the [[Markup Spec]] |
| [[Agent — Pattern Recognition]] | Name the structure; vision model cross-checked against rules |
| [[Agent — Multi Timeframe]] | Same symbol, several timeframes, one alignment score |
| [[Agent — Level Watcher]] | Watch every level in every active spec, fire when touched |

## The shared object

All four revolve around the [[Markup Spec]] — a declarative object, not an image.
Chart Markup produces it, Pattern Recognition annotates it, Multi Timeframe composes
several, Level Watcher subscribes to it. The [[Charting Engine]] renders it for
humans, for the vault, and for vision models.

```
 OHLCV ──► Chart Markup ──► MARKUP SPEC ──┬──► Charting Engine ──► PNG (vault, dashboard)
                                          ├──► Pattern Recognition (vision reads the render)
                                          ├──► Level Watcher (subscribes to levels)
                                          ├──► Idea Synthesizer (levels → entries/invalidations)
                                          └──► Knowledge Graph (each level is an entity)
```

## Why this family matters more than it looks

Because levels become **graph entities**, the system accumulates an answerable
question no charting tool can answer: *which of my levels actually hold?* After a
few hundred marked levels, [[Agent — Insight Miner]] can tell you that your
anchored-VWAP levels hold 70% of the time and your hand-drawn trendlines hold 40%.

That is a real, personal edge, and it exists only because the markup is structured
rather than drawn.

## Shared conventions

- Specs are **immutable**; re-marking creates a child spec linked to its parent.
- Every annotation carries a `why`. Unexplained lines are forbidden.
- Charts are rendered at a fixed size and theme so vision-model input is consistent.
- Timeframe and date are burned into every render — an undated chart is useless in
  a journal six months later.

## Related

[[Markup Spec]] · [[Markup Spec Schema]] · [[Charting Engine]] · [[Agent Index]] ·
[[Research Family]]
