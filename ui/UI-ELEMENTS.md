# Genesis UI — element sheet

A flat reference for every element currently on the surface, so a change can be
described by ID instead of by pointing. Not a spec — the spec is the vault. If
this sheet and the code disagree, the code is what shipped; if this sheet and
the vault disagree, the vault wins.

IDs are stable. Say "change **PNL-3**" and I'll know what you mean.

---

## 1. Shell chrome — `ui/src/App.tsx`

Everything here is always on screen, in this paint order. The top three rows
never scroll and never unmount.

| ID | Element | What it is |
|---|---|---|
| **SHELL-1** | Top bar | A 40px row holding identity, page nav, workspace switcher, search, connection dot, voice and kill switch. Fixed height because the kill switch is two lines and may never be clipped. |
| **SHELL-2** | Safety floor | The plain-DOM strip under the top bar: approval mode, portfolio heat, daily-loss headroom, open positions, feed status. Wrapped in its own error boundary so it survives anything the workspace does. |
| **SHELL-3** | Voice reply strip | A one-line bar that appears only when Genesis has said something — what it heard, what it replied, why it wasn't spoken aloud, and a dismiss button. Absent when idle. |
| **SHELL-4** | System health bar | A 20px strip showing six organs, each `ok` / `degraded` / `down` / `unknown`. `unknown` renders distinctly from `ok` on purpose. |
| **SHELL-5** | Workspace region | The remaining space, filled by the Dockview workspace for the current page. Falls back to "no workspace defined for this page" if a page has no preset. |
| **SHELL-6** | Command palette (⌘K) | A centred overlay over everything. Detail in section 3. |
| **SHELL-7** | Keyboard shortcuts | ⌘K toggles the palette; ⌘1–⌘8 jump to the eight pages. Bound on `window`, so focus doesn't matter. |
| **SHELL-8** | URL hash routing | The page is mirrored to `#page`, and back/forward or a hand-typed hash changes it. Preset selection is *not* in the URL. |
| **SHELL-9** | Surface boundary | The outermost error boundary. If the whole app throws, it renders the safety floor and kill switch and says the rest is gone — never a blank apology page. |

---

## 2. Top bar contents — `ui/src/shell/TopBar.tsx`

| ID | Element | What it is |
|---|---|---|
| **TOP-1** | Core sigil + "GENESIS" | A 17px animated glyph of the core's state, beside the wordmark in wide letterspacing. The only animated thing in the chrome. |
| **TOP-2** | Page nav | Eight text buttons, uppercase, active one marked by a 2px rule underneath. Never compresses — the workspace switcher gives way instead. |
| **TOP-3** | Dimmed page | A page whose capability probe returned `built: false` renders in ghost ink but stays clickable, with the reason in its tooltip. Dimmed, never hidden. |
| **TOP-4** | Workspace switcher | Small ghost buttons naming the presets for the current page, plus a `reset`. Only rendered when the page has more than one preset. |
| **TOP-5** | Search button | `⌕ search` with a `⌘K` key cap. Opens SHELL-6. |
| **TOP-6** | Connection dot | A 6px dot: green connected, amber connected-with-a-gap, red not connected. Tooltip names the state and suggests `genesis serve`. |
| **TOP-7** | Tap to speak | Push-to-talk button — hold to record, release to send. Nothing listens until pressed; audio is transcribed locally. |
| **TOP-8** | Kill switch | Inline arm-then-fire, never a modal. Posts direct HTTP to a separate process, and says plainly when no endpoint is configured rather than faking success. |

---

## 3. Command palette — `ui/src/shell/CommandBar.tsx`

| ID | Element | What it is |
|---|---|---|
| **CMD-1** | Query field | One input, focused on open, placeholder "search, or type a command and press ⌘↵". |
| **CMD-2** | Result rows | Pages, held series, MCP tools and discovered agents in one list, each with a colour dot for its kind, a label, a hint and a right-aligned kind tag. Everything is real data; no placeholder rows. |
| **CMD-3** | Ranking | Prefix match beats substring beats hint match, capped at 40 rows. An empty query shows the pages only. |
| **CMD-4** | Command escape hatch | ⌘↵ sends the raw text to `POST /v1/command` — the same endpoint voice uses — and the daemon's reply lands in SHELL-3. |
| **CMD-5** | Footer legend | `↑↓ move · ↵ open · ⌘↵ run as command · esc close`. |

---

## 4. Pages — `ui/src/shell/pages.ts`

Eight, declared once. Nav, palette, presets and shortcuts all read this list.

| ID | Page | Requires | What it is for |
|---|---|---|---|
| **PAGE-1** | Overview | — | The landing page: what this system currently is — organs present, data held, work done. Deliberately not a positions dashboard, because that would imply Genesis trades. |
| **PAGE-2** | Charting | `marketdata.bars` | Price, the series Genesis holds, and the charts it has drawn. |
| **PAGE-3** | Research | — | Companies, filings, and the tool surface available to answer a question. |
| **PAGE-4** | Backtest | `backtest.engine` | Run a strategy over stored bars and read the result. |
| **PAGE-5** | Journal | `journal.store` | Trades, lessons and the graph between them. |
| **PAGE-6** | Automation | `automation.workflows` | Workflows Genesis can run on a cadence or an event. Currently shows the cadences that exist; the builder does not. |
| **PAGE-7** | Fleet | — | The organism: agents, traces, memory and the execution path. |
| **PAGE-8** | Settings | — | Microphone, data, agents, tools and approval mode. |

---

## 5. Workspace presets — `ui/src/workspace/presets.ts`

A preset is a name plus a list of panels; Dockview owns the geometry after
that, and a person's arrangement is saved to `localStorage` per preset.

| ID | Preset | Page | Panels |
|---|---|---|---|
| **WS-1** | Focus | Charting | Chart + Series |
| **WS-2** | Analysis | Charting | Chart, Series, Instrument, Coverage/Markup tabbed |
| **WS-3** | Report | Backtest | Equity, Strategy, Statistics, Trades, History |
| **WS-4** | Compare | Backtest | History, Equity, Statistics |
| **WS-5** | Company | Research | Company + Tools |
| **WS-6** | Canvas | Research | Canvas + Company |
| **WS-7** | Graph | Journal | Graph, Entries, Patterns |
| **WS-8** | Ledger | Journal | Entries + Patterns |
| **WS-9** | Organism | Fleet | Body map, Inspector, Events |
| **WS-10** | Forensics | Fleet | Trace, Memory, Execution, Events |
| **WS-11** | System | Settings | Agents, Voice, Approval, Tools |
| **WS-12** | Data | Settings | Data + Coverage |
| **WS-13** | Schedule | Automation | Running cadences + Workflow builder |
| **WS-14** | System | Overview | Capabilities, Data held, Recent runs, Events |

---

## 6. Panels

Twenty-eight, registered in `ui/src/workspace/panels.tsx`. Each is wrapped in
its own error boundary — one bad series blanks one rectangle.

### Charting — `workspace/panels/charting.tsx`

| ID | Panel | What it is |
|---|---|---|
| **CHT-1** | Series (`watchlist`) | The list of series Genesis actually holds bars for, and clicking one selects it everywhere. There is deliberately no "add symbol" box — the universe is whatever has been ingested. |
| **CHT-2** | Chart (`chart`) | Lightweight Charts candles for the selected series. The right edge is the last *closed* bar, never extrapolated, and tier-3 vendor data draws behind a stale hatch. |
| **CHT-3** | Instrument (`symbol-detail`) | Two dense sections — `window` (the bar range on screen) and `identity` (what the symbol is). Empty until a series is picked. |
| **CHT-4** | Coverage (`coverage`) | A table of every ingested series: bar count, date range, source and trust tier. Says "nothing ingested yet" rather than showing zeros. |
| **CHT-5** | Markup (`markup-specs`) | Chart annotations Genesis produced — levels, patterns, structure. Empty until an analysis has been asked for. |

### Backtest — `workspace/panels/backtest.tsx`

| ID | Panel | What it is |
|---|---|---|
| **BT-1** | Strategy (`backtest-runner`) | Pick a series, pick a strategy template, edit its parameters, run. Blocks with an explanation if no bars are on disk. |
| **BT-2** | Equity (`backtest-equity`) | uPlot equity curve from Nautilus' account report, with the drawdown band drawn underneath at the same scale. The band is the point of the chart, not decoration. |
| **BT-3** | Statistics (`backtest-stats`) | Nautilus' own three-way split kept intact — PnLs, returns, general — plus a `run` section and anything the strategy raised. Caveats are printed above the numbers, in prose, never collapsed. |
| **BT-4** | Trades (`backtest-trades`) | Tabbed tables of the rows the run produced — fills, positions, orders — with per-tab columns. |
| **BT-5** | History (`backtest-history`) | Every past run, kept so a strategy can be compared to itself later. Click one to open it in BT-2/3/4. |

### Research — `workspace/panels/system.tsx`

| ID | Panel | What it is |
|---|---|---|
| **RES-1** | Company (`company-profile`) | Cached filings and fundamentals for one issuer, read from the local store. Opening the panel fetches nothing — asking Genesis about a company is what populates it. |
| **RES-2** | Tools (`tool-surface`) | The configured MCP catalogue as a table, with each tool's capability and whether it mutates. Afferent and efferent are distinguished, not mixed. |
| **RES-3** | Canvas (`research-canvas`) | Not built. Renders the unbuilt state with a pointer to the note that specifies it. |

### Journal — `workspace/panels/journal.tsx`

| ID | Panel | What it is |
|---|---|---|
| **JRN-1** | Graph (`journal-graph`) | A canvas force graph of entries, lessons and symbols. Edges are recorded provenance — a lesson points at the entries it was drawn from — never similarity scores. |
| **JRN-2** | Entries (`journal-entries`) | The ledger: every closed trade as a row, with the plan it was meant to follow. |
| **JRN-3** | Patterns (`journal-patterns`) | Patterns the insight miner has drawn from the entries. |

### Automation — `workspace/panels/automation.tsx`

| ID | Panel | What it is |
|---|---|---|
| **AUT-1** | Workflow builder (`workflow-builder`) | Not built — `automation.workflows` probes false, so the canvas is not drawn and the unbuilt state names the note instead. |
| **AUT-2** | Running cadences (`cadence`) | The automation that *does* exist: agents with declared cadences (`market-open: 30s`, `on event: agent.down`). This is what a workflow builder would eventually author. |

### Settings — `workspace/panels/settings.tsx`

| ID | Panel | What it is |
|---|---|---|
| **SET-1** | Voice (`settings-audio`) | Three sections — `microphone` (devices enumerated from this machine), `transcription`, and `speech`. Nothing is a plausible-looking default. |
| **SET-2** | Agents (`settings-agents`) | A table of the agents whose modules actually import, with family and tier. |
| **SET-3** | Data (`settings-data`) | `series held` and `feeds` — what is on disk and which feed it came from, read from the effective config the daemon loaded. |
| **SET-4** | Approval (`settings-approval`) | Shows the current mode (advisory / confirm / auto / halt) with what it means, and the other modes for reference. Read-only by design: loosening autonomy may not happen through a select box. |

### Fleet & shared

| ID | Panel | What it is |
|---|---|---|
| **FLT-1** | Body map (`body-map`) | React Flow: Genesis at the centre, five family bands orbiting it, MCP outside, memory below. Nodes are not draggable and there is no start/stop/restart — the canvas shows, it does not control. |
| **FLT-2** | Events (`event-stream`) | The live feed, and the audit surface: every line carries its `trace_id` and clicking one focuses the graph on that trace. `critical` is never deduplicated away; fleet telemetry rides the low lane. |
| **FLT-3** | Inspector (`agent-inspector`) | Everything known about one agent — and, as loudly, everything not known. A field with no event behind it says "no telemetry" rather than rendering a zero. |
| **FLT-4** | Memory (`memory-fabric`) | The five memory layers with live read/write traffic, labelled by the *question* each answers. Marks the ledger as exact and the vector store as never authoritative, and names the single writer per namespace. |
| **FLT-5** | Execution (`execution-path`) | The three legs — `propose_order` → approval → `place_approved` — as a three-leg type, so a fourth leg is not expressible. Placement is claimed only on the broker's acknowledgement. |
| **FLT-6** | Trace (`trace`) | Select an event and the surface filters to one `trace_id`: the causal chain from your words to every task, tool call and memory write, on a scrub bar. A task with a missing parent shows as an orphan rather than being reparented. |
| **FLT-7** | Capabilities (`capability-map`) | Renders `/v1/capabilities` — every probe the daemon ran, what it found, and the vault note for anything missing. The most important panel in the app and deliberately the least exciting. |

---

## 7. Graph pieces — `ui/src/graph/`

| ID | Element | What it is |
|---|---|---|
| **GR-1** | Agent node | One node per agent, visual weight tracking activity rather than importance, so "where is the work" reads pre-attentively. Carries a `tier: none` badge marking the parts that cannot hallucinate. |
| **GR-2** | Core node | The centre of the body map. No click handler — the core may never be a control. |
| **GR-3** | Spinal node | The Pre-Trade Risk Engine and the Kill Switch, in the reflex palette with a hard border. |
| **GR-4** | MCP node | The tool surface, split afferent (sense) from efferent (hand) and drawn as two different things. |
| **GR-5** | Memory node | One node per memory layer. |
| **GR-6** | Fleet edges | Three kinds at three weights, distinguishable without the legend: lineage solid and animated, memory dashed and fading, event dotted and fanning. There is no agent-to-agent edge, because there is no agent-to-agent call. |
| **GR-7** | Force graph | The canvas d3-force renderer used by the journal. Selection is subtractive — it dims everything unconnected and eases the camera in, rather than lighting the target up — and the simulation halts when it settles. |

---

## 8. Shared primitives — `ui/src/components/`

| ID | Element | What it is |
|---|---|---|
| **PRM-1** | `Num` | Every figure on the surface: monospaced, tabular-aligned, and an em dash for a missing value — never `0`, `N/A` or blank. |
| **PRM-2** | `Metric` | A labelled figure, the standard stat tile. |
| **PRM-3** | `Section` | A titled block inside a panel, with a `dense` variant used by most settings and detail panels. |
| **PRM-4** | `Table` | The generic column-driven table behind coverage, trades, entries, tools and agents. |
| **PRM-5** | `Caveats` | A prose caveat block in warn or info tone, used above numbers rather than under them. |
| **PRM-6** | `Chip` | A small inline tag — kinds, tiers, states. |
| **PRM-7** | `PanelBody` | The standard padded panel wrapper. |
| **PRM-8** | `Loading` | Skeleton rows: the answer is coming. |
| **PRM-9** | `Empty` | The store exists, was queried, and holds nothing — with a hint saying how to populate it. |
| **PRM-10** | `Absent` | The store does not exist on this machine, with the reason and a retry. |
| **PRM-11** | `Unbuilt` | The *code* does not exist, with a pointer to the vault note that specifies it. Distinct from `Empty` on purpose. |
| **PRM-12** | `PhaseMark` | The activity phase glyph — a distinct shape per phase, not just a colour, so it survives greyscale and colour deficiency. |
| **PRM-13** | `GenesisCore` | The animated presence: five states, identifiable in a still frame by shape and value. `pointerEvents: none` — never a control, never a number. |
| **PRM-14** | `CoreSigil` | The 17–22px rendering of the same five states, used in TOP-1. |
| **PRM-15** | `PanelBoundary` | Per-panel error boundary. Reports what threw rather than saying "something went wrong". |

---

## 9. Whole-surface states

| ID | State | What it does |
|---|---|---|
| **SUR-1** | Approval mode | `data-approval` on `<html>` restyles every panel border and number colour from one place. `LIVE` is a different colour scheme, not a badge. |
| **SUR-2** | Halted | `data-halted` on `<html>`, same mechanism. |
| **SUR-3** | Stale | Past the staleness threshold a number is struck through and labelled `STALE — not confirmed`. A confident-looking number from a dead socket is the failure this prevents. |
| **SUR-4** | Mock feed | The feed cell reads `MOCK DATA` in its own colour, in the safety floor, not in a corner. |
| **SUR-5** | Motion | `--motion-scale: 0` makes every transition instant without changing behaviour. |
