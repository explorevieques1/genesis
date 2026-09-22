---
title: Web Access
tags: [architecture, core, data]
status: building
implemented_by: [src/genesis/browser/__init__.py]
---

# 🌐 Web Access

How Genesis reaches the internet — and the distinction that governs everything
else here: **fetching a fact and showing a page are not two settings of one
feature. They are two subsystems.**

This is the most-used surface in the system. Nearly every question in a session
touches it, so its latency, its restraint, and its failure modes are felt more
than any other component's.

## The two planes

| | **Retrieval** | **Presentation** |
|---|---|---|
| Question it answers | *"Who is Apple's CEO?"* | *"Show me the Wikipedia page for crude oil."* |
| Consumer | a **model** | a **human's eyes** |
| Surface | headless, no window, ever | a visible panel |
| Trust handling | fenced as `<untrusted>` ([[MCP Gateway]]) | **not fenced — and does not need to be** |
| Who may invoke | any agent with the capability | the [[Orchestrator]] only, never an agent |
| Mechanism | a capability behind the gateway | an **event** to the UI |
| Frequency | constant — hundreds of calls a night | rare — a few a day, always human-initiated |
| Default | **on** | **off unless asked** |

The trust row is the one worth sitting with. The `<untrusted>` fence exists to stop
web text from issuing instructions to a model. When a page is rendered for a human
to read, **no model reads it** — so there is nothing to inject into, and no
summarisation step to distort it. The human gets the primary document, unmediated,
which is strictly better than a paraphrase.

That inverts the usual intuition: displaying a page is the *safer* of the two
operations from a prompt-injection standpoint. Its risks are different ones,
handled in [[#Why display is orchestrator-only]].

> [!important] Retrieval is a data path. Presentation is an actuation.
> This is the same split that [[Market Data Plane]] draws between the data plane
> and the tool-plane façade, and it resolves the same way: the high-volume,
> machine-facing path is plumbing, and the rare, human-facing path is an action
> with a confirmation protocol around it.

## Deciding which — deterministically, before any model

The classification is **verb-driven and lives in `orchestrator/intent.py`**, next
to the existing reflexes in `answers.py` and `verbosity.py`. No model call. Two
reasons this must be deterministic:

1. **Latency.** The wake → first-word budget is 1.5 s ([[Orchestrator]]). A model
   round-trip to decide *whether to open a window* spends a third of it deciding.
2. **Predictability.** *"Show me"* meaning "open the page" must be true every
   single time, or the user stops trusting the verb and starts over-specifying.
   A feature used fifty times a day has to be boring.

| Utterance shape | Plane |
|---|---|
| `show me` · `pull up` · `open` · `bring up` · `display` · `let me see` · `put ... on screen` | **presentation** |
| `what is` · `who is` · `when did` · `how much` · `look up` · `check` · `find out` · `tell me` | **retrieval** |
| `read me` · `summarise` · `what does ... say` | **retrieval** — the human wants the content, not the page |
| everything else | **retrieval**, with the offer protocol below as the escape hatch |

Retrieval is the default because it is the cheap, silent, reversible one. A wrong
guess toward retrieval costs a follow-up sentence; a wrong guess toward
presentation puts a window over the trading platform.

> [!note] The one genuine ambiguity
> *"Look up the Fed statement"* could be either. It resolves to retrieval, and the
> offer protocol catches the miss in one turn: Genesis answers, then asks whether to
> pull it up. That is a better outcome than a window the user did not want, and it
> is why the offer exists at all.
>
> `show me` and its family are never ambiguous in the other direction — nobody says
> "show me" when they want a spoken sentence.

## The retrieval ladder

Cheapest rung that can answer, per the *default down* rule in [[LLM Model Tiers]].
Most questions never reach the network at all.

| # | Rung | Cost | Example |
|---|---|---|---|
| 0 | **Memory / vault / store** | none | "What was my thesis on NVDA?" — [[Memory Fabric]] |
| 1 | **Deterministic answerer** | none | "What time does the market open?" — `answers.py` |
| 2 | **Known primary source** | none | a filing → EDGAR; a rate → FRED; an entity fact → Wikidata |
| 3 | **Self-hosted search + extraction** | none | "Why is crude down today?" |
| 4 | **Direct fetch** of a known URL + markitdown | none | a PDF, an IR page |
| 5 | **Headless browser render** | seconds, fragile | JS-only pages, last resort ([[Market Data Catalog]] rule 6) |

> [!important] Search is the fallback, not the main path
> The instinct is that a research system lives on web search. It does not. A trading
> system **knows its sources**: filings are EDGAR, macro is FRED, prices are the
> store, news arrives by RSS from publishers chosen in advance. Those are rungs 0–2,
> they are free by mandate ([[Market Data Catalog]] rule 1), and they answer most of
> what the fleet asks.
>
> Rung 3 exists for the genuinely unknown question — *"why is crude down today"* —
> which is a far smaller share of traffic than it first appears. Sizing the search
> layer as though it carried the whole load is what makes people buy a subscription
> they do not need.

### Rung 2 — the free-by-mandate shortcut

Entity questions are the ones that *feel* like web search and are not.
*"Who is the CEO of Apple?"* is a **Wikidata** query: a free SPARQL endpoint,
structured, exact, no ranking to second-guess and no page to parse. Same doctrine
as EDGAR and FRED — primary, structured, free because publishing is the point.
Route entity lookups here before touching a search engine.

### Rung 3 — self-hosted, not subscribed

Two components, both open source, together doing what a hosted "AI search API"
sells as one product:

| Piece | What it does |
|---|---|
| **SearXNG** (Docker, local) | Metasearch across Google/Bing/DDG/Wikipedia etc. JSON output is opt-in — enable `json` in `settings.yml` formats and disable the bot limiter, then `GET /search?q=…&format=json`. Unlimited at your own infrastructure cost, and engines are selectable per query. |
| **trafilatura** (Python) | The part that is actually hard: clean article text out of HTML, stripping nav, ads and cookie banners, with title/date/author metadata. Best-in-class at boilerplate removal and native to the Python core. `readability-lxml` as the lighter fallback. |

Structured results carrying source URLs are what make the `<untrusted>` fence
mechanical rather than an HTML-parsing exercise, and what give the offer protocol a
URL without a second round-trip. That property is the requirement — it does not
have to be bought.

> [!warning] Free is not zero-maintenance, and this is the honest trade
> SearXNG depends on upstream engines that actively block scrapers. Instances get
> rate-limited; occasionally an engine starts returning captchas and has to be
> rotated out in config. Money is being traded for maintenance, not eliminated.
>
> So rung 3 needs a **health check feeding [[Agent — Watchdog]]** — a silent search
> outage that surfaces as a thin morning brief is worse than a loud one. And the
> hosted adapter below exists precisely so a bad week is a config key, not a rewrite.
>
> What self-hosting cannot replicate is neural search over a vendor's own crawled
> index — querying by *meaning* ("companies doing X"). For sourcing a claim and
> answering "what's the latest on X", keyword search is sufficient. That gap is
> real but narrow.

**Never** scrape Google directly, and avoid the libraries that hit unofficial
search endpoints. Same fragility class as yfinance ([[Market Data Catalog]] §1):
works until it does not, blocks without warning, and the discovery happens at
06:45 during the brief.

**Every retrieved claim keeps its URL.** Not for citation formality — because
*"shall I pull up the source?"* is unanswerable otherwise, and because the advice
ledger ([[Market Data Catalog]] §17) grades ideas against evidence that has to
still be reachable months later.

### Latency and the acknowledgement

A search is 1–3 s. The first spoken word is due in 1.5 s. These are reconciled the
way [[Voice UX]] already reconciles them: the **soft rising earcon** ("heard you,
working on it") fires the moment the plane is chosen, which is immediate because
the choice is deterministic. Speech follows when the answer does.

No filler sentences. *"Let me look that up for you"* is a second of latency spent
on nothing, every single time, and it ages badly by the fiftieth repetition.

## The presentation surface

**A Dockview panel inside the Genesis shell, not a separate browser window.**
[[UI Stack]] §3 already establishes Dockview for exactly this mechanic — *"summon a
screen and put it next to the other one"*.

Reasons it is a panel:

- It participates in the layout, so *"put it next to the chart"* resolves to a
  named module in a named category ([[UI Stack]] §3) rather than window
  arithmetic.
- It is closable by voice — *"close that"* — without hunting for a window.
- It does not steal focus from the platform where the human is actually trading.
  A window that grabs focus mid-order is a genuine hazard, not an annoyance.
- ~~The Tauri Rust host owns its lifecycle~~ — **built differently, 2026-09-20.**
  There is no Tauri host, and the shell is a page served by vite, which cannot
  frame an arbitrary site: `X-Frame-Options` and `frame-ancestors` are set by
  TradingView, Google, X and every broker portal, so an iframe panel renders a
  blank box for most of what anyone would open.

  So the pixels travel the other way. A headless Chromium runs beside the
  daemon and the panel shows a `multipart/x-mixed-replace` JPEG stream of its
  viewport, with clicks and keys posted back over HTTP — a remote desktop of
  one browser window. Worse than a native WebView at one measured thing: text
  is JPEG rather than subpixel. Better at the one that decides it: it works in
  the shell that exists.

  Frames are **pushed** by `Page.startScreencast` over a socket of their own,
  not pulled by screenshots. The first build pulled, and it was visibly laggy:
  `Page.captureScreenshot` costs a full compositor frame and readback every
  call — 115 ms on a TradingView chart, an 8.7 fps ceiling — and clicks queued
  behind it on the one shared socket. Measured after the change, same page and
  machine: **37 fps**, and input off the frame queue entirely. An idle page now
  sends nothing at all, which is the other thing a push model gets right. Lifecycle is the daemon's — the browser is one process per daemon,
  closed by the panel's button or by `POST /v1/browser/close`, and an orphan
  is possible if the daemon is killed, which the Tauri host would have
  prevented. See `src/genesis/browser/session.py`.

> [!warning] The profile is persistent, reversing `partition: ephemeral`
> The ephemeral partition below suits a page summoned to be read once, which is
> what this note was written for. It cannot deliver a **logged-in** charting
> platform — which is what the surface was actually asked for on 2026-09-20:
> *"my TradingView account, their drawing tools, my live data subscription."*
> A browser that forgets the session on close delivers none of that.
>
> So the browser keeps its own profile at `~/.genesis/browser`, separate from
> the operator's daily Chrome, and logins survive a restart. The cost is real
> and is the reason the original posture was ephemeral: session cookies for
> every site visited now sit on disk, in a directory readable by whatever can
> read the operator's home. That is the same trade every browser on the machine
> already makes, made once more, knowingly.

**External browser** is the right answer for exactly two cases: a page needing a
real logged-in session (a broker portal), and anything the human wants to keep
after closing Genesis. Both are explicit — *"open that in my browser"* — never the
default.

> [!note] On this machine
> Hyprland window rules can float and place the shell, so the panel behaviour is a
> config concern rather than a code one. Worth a `windowrulev2` entry so a summoned
> page lands somewhere predictable instead of tiling the trading layout apart.

### No display action ever originates from a scheduled task

An invariant, and the one that makes the whole feature safe to leave enabled:
**only a live conversational turn may open a panel.** The overnight research pass
in [[Market Data Plane]] reads hundreds of pages and opens exactly zero windows.

Without this rule the first unattended night ends with forty tabs. With it, the
default posture the user asked for — *never show me the browser unless I say* —
is structural rather than a setting that something can flip.

## The offer protocol

The bridge between the planes: Genesis answered from the web, and the source might
be worth the human's own eyes.

### Shape

**Answer first. Offer second. Never block.**

```
👤 "Hey Genesis, who's the CEO of Apple?"
🤖 "Tim Cook."
```

```
👤 "Hey Genesis, why is crude down today?"
🤖 "Reuters has it on an unexpected inventory build — up 4.2 million barrels
    against a draw expected. Shall I pull up the source?"
👤 "Yes."
   [panel opens]
```

The answer never waits on permission. The offer is a trailing clause on a sentence
that was already useful, so declining costs nothing and silence costs nothing.

### When to offer — and mostly, when not to

The governing principle, which is narrower than "offer when there's a URL":

> **Offer when the value is in the human's judgment of the source. Not when the
> value is in the fact.**

*"Tim Cook"* needs no judgment — it is a fact, it is not contested, and a window
would be noise. *"Analysts think NVDA is expensive"* is nothing **but** judgment,
and the human is better at that judgment than Genesis is.

| Situation | Offer? |
|---|---|
| Single uncontested fact, high confidence | **No.** Just answer. |
| A claim that is somebody's opinion, forecast, or analysis | **Yes** |
| Sources disagree | **Yes**, and say that they disagree |
| The content is visual or tabular — a chart, a filing table, a curve | **Yes** |
| Answer is degraded, stale, or low-confidence | **Yes**, and say why |
| It feeds a trading decision | **Yes** — always offer the primary document |
| A primary document exists and Genesis paraphrased it | **Yes** |
| The human said "show me" | **No** — that is not an offer, that is an instruction |
| Unprompted / scheduled output | **No.** See the invariant above. |

This is the same restraint [[Voice UX]] applies to unprompted speech, for the same
reason: *an assistant that talks too much gets muted*. An assistant that offers a
window after every sentence gets its offers ignored, and then the offer is worthless
on the one occasion it mattered.

**Rate-limit it.** At most one offer per turn, and suppress the offer entirely for
the rest of a turn-chain where the human already declined once. Two "no"s in a row
on the same topic sets the session default to no-offer until asked otherwise.

### How "yes" resolves

The offer stores a **pending display handle** — URL, title, the answer it came
from — in [[Working Memory]] with a **60-second expiry**, matching the proposal
expiry already in [[Voice UX]].

Resolvers: `yes` · `yeah` · `sure` · `go ahead` · `do it` · `pull it up` · `show me`
· `let's see it` · `open it`. Decliners: `no` · `nope` · `not now` · `I'm good`.
Anything else is a new turn, and the handle expires quietly.

**Never re-asks.** Same rule as trade proposals — *"never asks twice for the same
proposal"*. A declined offer is gone.

> [!important] Why a bare "yes" is fine here, when it is forbidden for a trade
> [[Voice UX]] requires that a trade confirmation **name the ticker**, because a
> misheard "yes" would place an order. Opening a web page is the opposite kind of
> action: reversible, costless, and visibly wrong the instant it happens.
>
> Stating this explicitly matters, because the naming rule looks like a general
> confirmation convention and is not one — it is a response to irreversibility.
> Applying it here would make a fifty-times-a-day interaction tedious for no safety
> gain, and tedious safety rituals are how people learn to say the magic word
> without listening. [[Safety Invariants]] is protected by keeping its rules
> proportionate to their hazards.

### Phrasing

Short, and a real question rather than a menu. *"Shall I pull up the source?"* ·
*"Want to see it?"* · *"There's a chart on the filing — shall I show you?"*

The honorific is a config toggle (`voice.honorific`), not baked into the prompt.
[[Voice UX]]'s persona is *a capable colleague*, and "sir" is a taste the user
should be able to set once and change without touching a prompt.

## Worked dialogues

**Fact, no offer** — the common case, and the one that must stay fast:
```
👤 "Genesis, who's the CEO of Apple?"
🤖 "Tim Cook."
```

**Explicit presentation** — no offer, no question, no model in the decision:
```
👤 "Genesis, show me the Wikipedia page for crude oil."
🔔 [rising earcon]
   [panel opens, docked right]
🤖 "Up on the right."
```

**Retrieval that earns an offer:**
```
👤 "What's the latest on the NVDA export licences?"
🤖 "Reuters reported approval for the H20 line on Tuesday; Bloomberg frames it as
    partial. The two don't agree on scope. Want to see both?"
👤 "Yeah."
   [two panels, tabbed]
```

**Declining costs nothing:**
```
🤖 "...shall I pull up the filing?"
👤 "No, that's fine."
🤖 [low neutral earcon — acknowledged, no action]
```

**Escalating to a real browser:**
```
👤 "Open that in my browser."
   [external browser, default profile]
```

**Showing the work, on request** — the *"unless I say"* half of the default:
```
👤 "Genesis, show me what you're reading."
   [panel opens on the live retrieval feed: URLs, snippets, what was kept]
```
Debug affordance, off by default. Useful the first week and after any answer that
felt wrong, and it is the honest way to audit what the fence actually let through.

## Why display is orchestrator-only

Displaying a page cannot be prompt-injected, but a browser that an agent can drive
is a different object entirely, and it is a genuine exfiltration path: an agent
reading untrusted text, able to navigate a session that holds the user's cookies,
can be instructed to put private data into a URL. That is the classic exfiltration
shape, and it does not require the agent to be "compromised" in any deeper sense.

Three structural answers:

1. **`display.*` is never in an agent allow-list.** It is not a gateway capability
   at all — see the wiring below. An agent cannot request it, so no injection can
   reach it.
2. **The display WebView runs in an ephemeral, cookie-less partition** by default.
   No logged-in sessions, no stored credentials, cleared on close. Logging in is an
   explicit human act in the external browser, not something the panel can hold.
3. **Retrieval keeps the SSRF guard** already required by [[MCP Gateway]] — no
   internal addresses, no file schemes, no redirects into private ranges.

This is the same structural argument as [[MCP Gateway]]'s: the agent that ingests
the most untrusted text is kept furthest from anything dangerous, and the
restriction lives outside the model where no prompt can move it.

## Wiring

The retrieval plane is a gateway capability. The presentation plane is **not a
tool** — it is an event on the existing daemon → UI channel.

That distinction keeps [[Orchestrator Tools]] at sixteen. Its own governing
constraint is that the list stays small and fixed because the planner weighs every
tool on every utterance; adding `display.page` there would tax every request in
the system to serve a handful a day. And presentation genuinely *is* UI transport:
it belongs with [[Event Schema]], next to every other thing the daemon tells the
shell to render.

| Piece | Where |
|---|---|
| Plane classifier | `src/genesis/orchestrator/intent.py` — deterministic, extends the existing reflexes |
| Offer decision + phrasing | `src/genesis/orchestrator/answers.py` — sits alongside the trivial-answer path |
| Pending display handle | `src/genesis/memory/working.py` — 60 s TTL |
| Yes/no resolver | `src/genesis/orchestrator/intent.py` — pattern table, no model |
| `web.search` / `web.fetch` / `web.extract` | gateway capabilities, `trust: untrusted`, fenced |
| `display.requested` / `display.closed` | [[Event Schema]] events, daemon → shell — **not yet wired**; the panel is opened by hand as `WEB` |
| The browser itself, and the CDP into it | `src/genesis/browser/session.py` — reuses the hand-written CDP client in `tradingview/cdp.py` |
| The frame pump | `src/genesis/browser/screencast.py` — `Page.startScreencast` on a second socket, so frames and input never queue behind each other |
| Frame stream, navigation, input | `src/genesis/server/browser_routes.py` — five routes, **no tool and no capability** |
| The panel | `ui/src/workspace/panels/browser.tsx` — module `WEB` ([[Widget Catalog]]) |

Config, per [[Config And Secrets]] — behaviour in the file, never in the model's
reach:

```yaml
web:
  search:
    provider: searxng           # searxng | hosted — one only, see the adapter rule
    endpoint: http://localhost:8080
    extractor: trafilatura
    entity_lookup: wikidata     # rung 2 — bypasses search for entity facts
    hosted_fallback:
      enabled: false            # written, disabled, on the shelf
      provider: exa
  display:
    default: never              # the asked-for posture, and the shipped default
    surface: panel              # panel | external
    partition: persistent       # was `ephemeral` -- see the warning above
    offer:
      enabled: true
      max_per_turn: 1
      expiry_sec: 60
      suppress_after_declines: 2
  show_work: false              # the retrieval feed panel
```

## Acceptance criteria

- *"Who is the CEO of Apple?"* answers in one sentence and opens nothing.
- *"Show me the Wikipedia page for crude oil"* opens a panel and never asks a
  clarifying question.
- The plane decision costs no model call — provable by asserting zero LLM
  invocations on both paths above.
- A full overnight research pass opens zero panels.
- A declined offer is never repeated for the same handle.
- ~~The display WebView holds no cookies across a close.~~ **Reversed** — the
  profile is persistent, so a subscription logged into once stays logged in.
- An agent declaring `display.*` in its allow-list **fails at boot**, the way
  [[MCP Gateway]] already refuses to grant an untrusted tool before the fence exists.
- **No agent can reach the browser at all.** Held structurally rather than by
  the check above: the package registers no MCP server, no capability and no
  orchestrator verb, so the only hand on the mouse is the operator's. This is
  also the whole of why a browser that can open a broker portal does not
  violate [[Safety Invariants]] §1 — Genesis is not the one clicking. **Wiring
  an agent to `/v1/browser/input` would break that invariant**, and is the one
  change that needs this note reopened first.
- Ten minutes of ambient conversation produces zero panels and zero offers.

## Open decisions

> **Decision (2026-09-02): self-host.** `web.search` is a **capability with an
> adapter behind it**, exactly as [[Market Data Plane]] treats a vendor: SearXNG +
> trafilatura primary, Wikidata for entity facts, and a hosted adapter (exa)
> *written but disabled* so an outage is one config key rather than a rewrite.
>
> The reasoning is the same one that shapes [[Market Data Catalog]]: a subscription
> is a recurring cost **and** a dependency on somebody else's pricing page. Brave
> removed its free Search API tier in February 2026 and moved existing developers
> from thousands of free monthly queries onto metered billing — which is the failure
> mode, not a hypothetical. Sources that are free by mandate do not do that, and a
> service running on hardware that is already always-on does not either.
>
> Remaining sub-decision: **who runs SearXNG's health check**, and what the brief
> says when search is down. Leaning [[Agent — Watchdog]] plus an explicit degraded
> label rather than silent omission ([[Error Handling And Degradation]]).

> [!warning] Conflicts with a decision already in the code — reconcile before building
> [[MCP Server Catalog]] §Web was updated **2026-09-02** to supersede exa/tavily with
> `@brave/brave-search-mcp-server`, and it is already wired and `enabled: true` in
> `src/genesis/mcp/default_servers.yaml` (three tools registered: `web.search`,
> `news.search`, `web.summarize`).
>
> That decision was made against a free tier that **no longer exists**. Brave removed
> the free Search API tier in February 2026 and moved developers onto metered
> billing — new accounts get ~$5/month in credits, roughly 1,000 queries, then the
> card is charged. The comment in `default_servers.yaml` line 111 and the note in
> `.env.example` both still describe the old free tier and are now stale.
>
> Two paths, and the operator picks:
> 1. **Keep Brave** — check first whether the existing key is grandfathered (prior
>    free-plan subscribers retained up to 2,000 queries/month). If it is, this is
>    free today and metered the moment the key lapses.
> 2. **Move to SearXNG per this decision** — Brave becomes the `hosted_fallback`
>    adapter rather than the primary, keeping the wiring already done.
>
> Either way the capability names do not change, which is the point of putting an
> adapter behind `web.search` in the first place.
- **Does the panel persist across sessions?** A summoned page is probably ephemeral,
  but a filing the human is mid-way through reading is not.
- **Reading long documents aloud.** Currently out of scope — `read me the 8-K` hits
  retrieval and gets a summary. Whether full read-aloud is wanted is a [[Voice UX]]
  question, not a web one.
- **Honorific.** `voice.honorific` default: on or off.

## Related

[[Orchestrator]] · [[Orchestrator Tools]] · [[Voice UX]] · [[UI Stack]] ·
[[Dashboard]] · [[MCP Gateway]] · [[MCP Server Catalog]] · [[Event Schema]] ·
[[Working Memory]] · [[Market Data Catalog]] · [[Market Data Plane]] ·
[[Config And Secrets]] · [[Safety Invariants]]
