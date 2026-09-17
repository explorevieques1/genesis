---
title: Agent — Digest
tags: [agent, journal]
family: journal
cadence: cron
tier: small
status: built
implemented_by: [src/genesis/agents/journal/digest.py, tests/journal/test_agents.py]
---

# 📃 Agent — Digest

## Purpose

Two jobs that turn out to be the same job:

1. **Brief you** — the morning brief and the evening recap, in a form you can
   actually listen to.
2. **Compress memory** — summarise the day's activity so [[Memory Fabric]] doesn't
   bloat into uselessness.

> [!info] 21:00 is the whole nightly memory pass — 2026-09-17
> This agent holds the cron, so it triggers all of [[Memory Consolidation]],
> of which its own `compress()` is pass 6. With no consolidator wired it falls
> back to compaction alone. `genesis memory consolidate` runs the same object
> graph by hand.

Both are summarisation with different audiences: one human, one machine.

Pattern: [[Repo — jarvis]] diary summariser + recall gate.

## Cadence

- `cron` 07:00 ET — morning brief (after [[Agent — Market Analyst]] and
  [[Agent — News And Catalyst]] have run)
- `cron` 16:30 ET — evening recap
- `cron` 23:00 ET — tomorrow's prep note
- `cron` 21:00 ET — memory compression, alongside [[Memory Consolidation]]

## The morning brief

Structured, under 90 seconds spoken, written to `50-Research/daily/YYYY-MM-DD.md`.

```
🌅 Thursday, August 29th. Market opens in two hours twenty.

📊 Regime: risk-on. VIX 14.2, down 8% on the week. Breadth confirming —
   62% of the S&P above its 50-day.

📰 Three catalysts. CPI at 8:30, high impact. NVDA earnings after the close.
   Fed's Williams speaks at 1pm.

💡 Four ideas ranked overnight. Top is NVDA long from 121, invalidation
   118.40, confidence 0.72 — but it's an earnings day, so that's a
   before-the-close trade or nothing.

📓 You're flat. No open positions. Daily loss headroom is full.

⚠️  One thing: lesson four says you oversize after consecutive losses, and
   yesterday was two.
```

Note the structure — regime, catalysts, ideas, your book, and **one warning**. Never
more than one warning; a brief that lists five concerns gets tuned out.

> **Wired 2026-09-14:** the brief reads the last 24h from the research stores —
> regime from the newest [[Agent — Market Analyst]] `regime` note, catalysts from
> the newest [[Agent — News And Catalyst]] brief's headlines, ideas from live
> [[Agent — Idea Synthesizer]] notes by confidence (`DigestAgent.overnight`). A
> missing store contributes nothing. **Still open:** the sentiment line (no
> [[Agent — Sentiment]] yet; [[Open Questions]] §19), and 23:00 prep uses the
> morning format. The job is chosen by the cron's `at` — before this, all four
> cron times produced a morning brief.

## The evening recap

```
🌆 Close. S&P up 0.4%, semis led.

📓 Two trades. NVDA long, plus 1.2R. AMD short, minus 1R. Net plus 0.2R.

📏 Both fills were clean — 3 bps average slippage.

🔍 One note: you exited NVDA at 1.2R against a 2R target. That's the
   fourth time this month. I've logged it as a hypothesis, not a lesson —
   it needs more observations.

🌙 Tonight: backtesting three ideas, re-running the optimizer on nq_orb_v3,
   and the weekly drift check.
```

Honest about the day, specific about what the system will do overnight — so you know
what to expect in the morning.

## Memory compression

The other half of the job, and the reason memory stays usable over years.

- Roll [[Working Memory]] into summarised [[Episodic Log]] entries
- Collapse repetitive agent runs ("screener ran 78 times, 9 unique hits") into one
  record with the details preserved but not indexed
- Extract durable facts into the [[Knowledge Graph]]; discard the transient
- Preserve **all** decisions, orders, fills, and ideas verbatim — these are never
  compressed, ever
- Preserve anything referenced by a [[Trade Journal Schema|journal note]] or lesson

The rule: **compress process, preserve decisions.** You never need the 78 screener
runs; you always need why you took the trade.

## Tools

`memory.read` (broad) · `memory.write` · `obsidian.write` · `tts` (via [[Orchestrator]])

Small tier ([[LLM Model Tiers]]) — summarisation, not reasoning.

## Memory namespace

Read: everything
Write: `digest`, `shared`, vault `50-Research/daily/`

## System prompt sketch

> You are the Digest agent. You brief a busy trader who is about to make decisions
> with money.
>
> **Ruthless brevity.** The morning brief is 90 seconds spoken. If something doesn't
> change what they do today, cut it.
>
> **Lead with the number.** Regime, then catalysts, then ideas, then their book.
>
> **One warning maximum.** Pick the single most important one. A brief that lists
> five concerns gets ignored entirely, which is worse than mentioning none.
>
> Never manufacture significance. "Quiet overnight, nothing changed, two ideas still
> live" is a good brief on a quiet day.
>
> In the recap, report losses in the first sentence with the wins. Do not bury them.

## Acceptance criteria

- Morning brief under 90 seconds spoken; recap under 60.
- Exactly one warning maximum in the brief.
- On a quiet day, the brief is short — no padding.
- Compression never discards a decision, order, fill, idea, or anything a journal
  note or lesson references. Verified by test.
- Daily note is written before 07:15 ET, every trading day.

## Related

[[Memory Consolidation]] · [[Working Memory]] · [[Episodic Log]] ·
[[Agent — Market Analyst]] · [[Voice UX]] · [[Journal Family]]
