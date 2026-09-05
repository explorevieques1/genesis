# Genesis UI

The command surface. React 18 + TypeScript + Vite + Tailwind v4, per
`Genesis Markdown/60-UI/UI Stack.md`.

## Running it

```bash
genesis serve                     # the daemon, on 127.0.0.1:8765
cd ui && npm install && npm run dev
```

Point the UI elsewhere with `VITE_GENESIS_HTTP=http://127.0.0.1:8766 npm run dev`.

Everything the surface shows comes from that daemon. There is no fixture data
and no mock transport — with the daemon down, every panel says so.

## The one rule

**The UI cannot display a number the daemon has not vouched for.**

This is structural rather than a habit. `/v1/capabilities` probes what exists by
importing modules and checking files, and the shell reads the answer before any
page renders. A page whose capability reports `built: false` can only render
`<Unbuilt/>`, which names the missing module and the vault note that specifies
it.

That is why the Journal page says *"journal database not created yet
(~/.genesis/memory/journal.db)"* instead of showing an empty trade table, and
why the Automation page shows the eleven agent cadences that really run instead
of a workflow builder that does not exist.

The same discipline applies to values:

| State | Rendered as |
|---|---|
| Loading | a skeleton the shape of what is coming |
| Empty | "queried, and there is nothing in it" |
| Absent | the store is not on this machine, with the reason verbatim |
| Unbuilt | the code does not exist, with the spec note |
| Missing value | an em dash — never `0`, never `NaN` |

## Layout

```
src/
├── api/          the read layer — client, useRead, capability gate, fleet reconciliation
├── shell/        pages, top bar, ⌘K palette
├── workspace/    Dockview host, presets, panel registry, panels/
├── components/   primitives, states, charts/, graph/
├── views/        the fleet surfaces (body map, trace, memory, execution)
├── graph/        React Flow nodes, edges, elk layout
├── store/        the event fold — a projection, never a store of record
└── transport/    the WebSocket
```

## Conventions worth knowing before editing

**Money is a string, all the way to the pixel.** Prices and P&L arrive as
strings and stay strings; `Number()` appears only where a charting library
demands it, and those places are commented. `lib/format.ts` formats without
parsing.

**The formatters are total.** They accept `undefined` and return an em dash. A
missing snapshot field once reached `money()`, threw, and unmounted the entire
tree — including the safety floor and the kill switch.

**Charting libraries reject `color-mix()`.** Lightweight Charts throws and
renders nothing, with no visible error. Use `format.withAlpha()` for any colour
handed to a canvas library.

**Nothing polls.** Reads run on mount; movement arrives on the event socket. The
render clock drops to 1 Hz when nothing is in flight — an organism at rest costs
nothing.

**Every panel has its own error boundary.** One panel failing shows one failed
rectangle. It must never blank the risk numbers beside it.

## Scripts

```bash
npm run dev        # vite, port 5273
npm run build      # tsc -b && vite build
npm run typecheck
npm run lint
```
