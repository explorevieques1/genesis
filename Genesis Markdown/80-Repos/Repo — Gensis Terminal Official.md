---
title: Repo — Gensis Terminal Official
tags: [repo]
---

# Repo — Gensis Terminal Official

`/home/gzacc2002/Projects/Gensis Terminal Official/`

**The UI layer.** An Electron widget-grid trading terminal — main/preload/renderer,
a manifest, and a folder of working widgets. Genesis's [[Dashboard]] and
[[Widget Catalog]] come from here.

## Widgets already built

`widgets/` — each an HTML file with an optional `.json` manifest:

| Widget | Genesis use |
|---|---|
| `price-chart.html` | [[Dashboard]] chart pane; overlay [[Markup Spec]] annotations |
| `ticker-manger.html` | Watchlist, driven by [[Agent — Screener]] |
| `trade-calendar.html` | Journal heatmap by day P&L |
| `account-stats.html` | Positions and P&L from [[Agent — Position And PnL Accountant]] |
| `consistency-calc.html` | Direct fit for the [[Prop Firm Rules]] consistency rule |
| `strategy-library.html` | Browse [[Strategy Schema]] objects |
| `indicator-library.html` | Reusable indicator scripts |
| `calculator V2.html` | Position sizing — wire to [[Agent — Portfolio And Allocation]] |
| `timer.html`, `clock.html`, `timezone.html` | Session awareness |
| `sticky.html` | Quick capture → vault `00-Inbox/` |
| `browswer.html`, `dice.html`, `help.html` | Utility |

Keep the widget + manifest pattern — it's the right shape for a pluggable grid, and
[[Widget Catalog]] extends it rather than replacing it.

## Documents worth reading

| File | Why |
|---|---|
| **`OBSIDIAN-VAULT-PROMPT.md`** | The source for [[Obsidian Vault Schema]] — read before building the vault integration |
| `rewrite.md` | Prior thinking about restructuring this terminal; likely overlaps Genesis's dashboard plans |
| `COMMERCIALIZATION-PLAN.md` | Product direction, if that matters later |
| `QUICKSTART.md`, `README.md` | How the Electron shell is wired |

## Design system

`assets/` holds the branding (`main_logo.png`, `title.png`, icons). The design-system
zips in [[Repo — gensis-agents]] `New Downloads/` carry the visual language —
`Genesis Terminal Design System.zip`.

Genesis should look like this, not like a generic dashboard. Dark theme, matching
[[Charting Engine]] renders.

## Architectural fit

Two options ([[Open Questions]] §3):

1. **Recommended** — Python core daemon + this Electron shell as the [[Dashboard]]
   and [[Desktop Shell]] client, talking over HTTP/WebSocket per [[Event Schema]].
   The core runs headless; the terminal is one of several views.

2. All-Node with a Python sidecar for backtests. Simpler deploy, worse fit with the
   [[Trading Corpus Index|corpus]], which is entirely Python.

Either way, the terminal must be a **client, not an authority** — it holds no state
that isn't in [[Memory Fabric]], so a refresh loses nothing and closing it never
affects trading ([[Desktop Shell]] separation rule).

## What to add

New widgets Genesis needs that don't exist here: agent grid, activity feed, idea
board, approval queue, risk gauges, prop-firm bars, transcript, memory viewer, level
watch, drift monitor, kill switch. See [[Widget Catalog]].

The kill switch widget is not optional and must not live behind a menu.

## Related

[[Dashboard]] · [[Widget Catalog]] · [[Desktop Shell]] · [[Obsidian Vault Schema]] ·
[[Repo — gensis-agents]] · [[Repo Map]]
