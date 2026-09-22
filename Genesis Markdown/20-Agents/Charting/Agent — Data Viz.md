---
title: Agent — Data Viz
tags: [agent, charting]
family: charting
cadence: on-demand
tier: large
status: built
implemented_by: [src/genesis/agents/charting/data_viz.py, src/genesis/charting/analytics.py, tests/charting/test_analytics.py, tests/charting/test_agents.py]
---

# 📊 Agent — Data Viz

## Purpose

The charts that are not price charts. *"Show me a bar chart of the top performing
sectors this past year"* and *"show me the fed funds rate over the past twenty
years"* are charting questions with no level to draw and no structure to name.
Routed to [[Agent — Chart Markup]] they produce a candle chart of a percentage.

Three jobs, and they are genuinely different:

1. **Get the numbers** — deterministically, through the [[MCP Gateway]], never by
   asking a model for a figure.
2. **Choose the form** — the judged part, and the reason this is an agent rather
   than a function.
3. **Say what it shows** — separated into a *finding* and, on request, a *theory*.

> [!important] Why this is a fifth agent and not a mode of Chart Markup
> [[Agent Contract]]: *"Keep prompts narrow. An agent that can do everything is
> the orchestrator, and we already have one."* Markup restraint and
> visualisation design are opposite skills with opposite failure modes — one is
> "you drew forty lines", the other is "you drew eleven categorical hues when the
> story was one number". One prompt cannot hold both without getting worse at
> each.
>
> It also has a different tool grant. Data Viz reads `macro.*` and batch OHLCV;
> Chart Markup does not, and should not.

## Cadence

- `on-demand` only. There is no such thing as a scheduled sector chart nobody
  asked for.

## Inputs

- A **recipe** and its arguments. The recipe set is closed — a model naming one
  that does not exist gets a typed failure listing the ones that do, rather than
  an agent improvising a data-gathering plan.
- Bars via `market-data.ohlcv`, macro series via `macro.series`.

| Recipe | Answers | Form |
|---|---|---|
| `sector_performance` | "which sectors led / lagged over N days" | ranked bar, signed |
| `macro_series` | "show me the fed funds rate / CPI / 10-year over N years" | line |
| `compare` | "how did these symbols do against each other" | line, indexed to 100 |
| `correlation` | "how much of this basket is really one bet" | heatmap, diverging |

## Outputs

1. A rendered PNG in `20-Charts/`, sourced and dated in the footer
2. The rows the chart was built from, as data
3. A **finding** — what the chart shows, arithmetically
4. A **theory**, only when asked, explicitly labelled as a hypothesis

```yaml
image_path: 20-Charts/us-sector-total-return-trailing-year.png
form: bar
rows: { Utilities: 24.8, Financials: 19.2, ... }
finding: "Utilities led the year at +24.8%, 5.6 points ahead of Financials.
          3 of 11 sectors were negative, worst Cons. Discretionary at -9.4%."
theory: "Rate-sensitive defensives re-rated as the curve steepened ..."
theory_is_hypothesis: true
```

## Finding versus theory — the line this agent must not blur

The finding is arithmetic over rows this system fetched. The theory is the
model's own knowledge, unverified.

Genesis is an advisor, and the honest form of *"why did utilities lead"* is a
**stated hypothesis with a falsifier**, not a fact. The spoken answer prefixes it
— *"As a theory, not something I verified: …"* — and that prefix is added by code
in `VizResult.spoken()`, not left to the model to remember. A model asked to
hedge will mostly hedge, and "mostly" is not a property you want between a trader
and a causal claim.

When a real causal answer is wanted, that is [[Agent — News And Catalyst]] and
[[Agent — Market Analyst]]'s job, and it cites sources. This agent says what it
does not know.

## Design rules, inherited from the visualisation discipline

These are enforced in `analytics.py`, not requested in the prompt.

- **One axis, always.** No chart here can plot two measures on two y-scales. The
  alignment between two such scales is arbitrary, so the chart invents a
  relationship that is not in the data. Two measures → two panels, or index both
  to 100 (`compare` does exactly this).
- **Colour by identity, in fixed slot order.** A series keeps its hue when a
  filter removes its neighbours. Never a value-ramp over unordered categories.
- **Signed magnitude is polarity, two colours and a zero baseline.** Eleven
  sectors in eleven hues is a chart about the palette.
- **A single number is a stat tile, not a one-bar chart.**
- **Eight series maximum**, enforced by a validator. A ninth folds into "Other".
- **Thirty bars maximum**, enforced. Past that it should have been a table, and
  the failure is silent — labels smear into grey.

Palette: the same dark theme as [[Charting Engine]], validated for colour-vision
deficiency (worst adjacent pair ΔE 8.4 against this surface).

## Tools

`market-data.ohlcv` · `market-data.ohlcv-batch` · `market-data.overview` ·
`macro.series` · `macro.search` · `genesis-charting.render_analytics` ·
`obsidian.write`

## Memory namespace

Read: `shared`, `data-viz`, `market-analyst`
Write: `data-viz`

## System prompt sketch

> You are the Data Viz agent. You are given a chart already built from primary
> data — the numbers on it were computed, not written by you — and you say what
> it shows.
>
> **FINDING**: what the chart shows, arithmetically. Only numbers in the data
> below. No causation.
>
> **THEORY** (only when asked): why it might look like this. A hypothesis from
> your own knowledge, not something this system verified, and you must say so.
> Prefer mechanisms a trader can check — rates, positioning, earnings revisions,
> flows — over narrative. Name what would falsify it. If you have no defensible
> theory, say the honest thing: the chart shows the what and you do not know
> the why.
>
> Never invent a number.

## Acceptance criteria

- Every number on a rendered chart traces to a tool result; the agent contributes
  no figures.
- A recipe that is not in the table produces a typed failure naming the ones that
  are, never an improvised fetch.
- A theory is never spoken without its hypothesis prefix.
- An unrecognised macro series name raises rather than guessing a FRED id — a
  guessed id returns a real, well-labelled chart of the wrong series.
- `compare` indexes to 100 on a shared date calendar, so two symbols with
  different holiday sets are not shifted against each other.
- Nine or more series, or thirty-one bars, is a validation error at build time.

## Related

[[Charting Family]] · [[Charting Engine]] · [[Agent — Chart Markup]] ·
[[Agent — Market Analyst]] · [[Market Data Plane]] · [[genesis-charting-mcp]] ·
[[Agent Contract]]
