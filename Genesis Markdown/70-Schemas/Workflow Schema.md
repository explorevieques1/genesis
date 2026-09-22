---
title: Workflow Schema
tags: [schema, automation]
status: built
implemented_by: [src/genesis/automation/workflow.py, src/genesis/automation/store.py, src/genesis/automation/actions.py, ui/src/components/automation/wiring.check.ts, ui/src/components/automation/wiring.ts, tests/automation/test_workflow.py]
---

# ⚙️ Workflow Schema


One workflow body, as stored in a `workflow_versions.body` row and as posted by
the `WB` panel. Validated by a strict pydantic model (`extra="forbid"`): an
unknown key is a typo, and a typo in a step is a silent no-op.

```json
{
  "id": "tesla-morning-synopsis",
  "name": "Tesla news synopsis",
  "trigger": { "type": "cron", "at": "07:00" },
  "start": "news",
  "steps": [
    { "id": "news", "kind": "gather", "next": "has-news",
      "capability": "news.search", "args": { "query": "Tesla", "limit": 20 } },
    { "id": "has-news", "kind": "check", "next": "synopsis",
      "input": "news", "predicate": "non_empty" },
    { "id": "synopsis", "kind": "run", "input": "news",
      "agent": "topic-researcher", "args": { "subject": "Tesla news today" } }
  ],
  "layout": { "news": { "x": 240, "y": 80 } }
}
```

## Fields

| Field | Type | Rule |
|---|---|---|
| `id` | kebab-case string | unique; compiles to agent id `wf-<id>` |
| `name` | string | display only |
| `trigger` | `Cadence` | the [[Agent Contract]] model, unchanged — `on-demand`, `market-open`, `market-closed`, `cron`, `event` |
| `start` | step id or null | the step the trigger connects to; null = nothing runs |
| `steps` | list, 0–40 | step ids unique; `trigger` is reserved |
| `layout` | object | canvas positions, notes, groups; never read by the runtime |

## Steps

Every step has `id` and `kind`, and may have `next` (one step id) and `input`
(an **earlier step on its path**, or `trigger` — the data the run started
with). Only a `check` or an `action` whose node branches may have `on_fail`. No
step may be the target of two edges, and no loops.

| Kind | Fields | Rule |
|---|---|---|
| `gather` | `capability`, `args: object`, `each?`, `each_arg?` | `capability` must match `WORKFLOW_GRANT`; refused at save otherwise. With `each`, needs `input` and `each_arg` — the argument each input item fills. String args accept date slots. |
| `check` | `input`, `predicate`, `field?`, `op?`, `value?` | `predicate` ∈ `non_empty`, `min_count` (`value`), `compare` (`field` of the input's structured output, `op` ∈ `> < >= <=`, `value`). A missing or non-numeric field fails — closed. |
| `refresh` | `target` | ∈ `vault-map`, `corpus-index` |
| `run` | `agent`, `args: object` | a registered agent whose family is not `execution` |
| `action` | `action`, `params: object`, `each?: bool` | `action` names a node in `automation/actions.py`; `params` must match its declared settings (unknown refused, required present, selects in range); `each` only on nodes that declare one, and needs `input` |

### Step output

Every step produces `{text, structured, items?, untrusted?}`. A tool's JSON text
is parsed into `structured`; `untrusted` marks a fenced source, whose parsed
fields never reach an agent. `items` is the list a later
step iterates, filters or counts; it is taken from `items`, a list payload, or
the first list inside a dict payload.

## Run record

Each fire appends one row to `workflow_runs(run_id, workflow_id, version,
started_at, finished_at, status, steps)` where `steps` is the per-step outcome:
`ok | failed | skipped`, the gateway result (fenced, truncated) or the failure
reason, and for `run` the submitted task id. A failed step stops the run; later
steps are `skipped` — unless the failed step is a `check` with `on_fail`, which
is a branch, not a failure. A failed run is `degraded` and not retried; the bus
does not loop on a flaky source and the supervisor does not count it as a crash.

## Alerts

`workflow_alerts(alert_id, workflow_id, run_id, step_id, at, title, message,
urgency)`, append-only, written by the *Send alert* node and mirrored to the
Episodic Log as `automation.alert`. `urgency` is Voice UX's tier
(`always | if-present | never`); nothing speaks it yet.

## Versions

`workflow_versions(workflow_id, version, body, author, at, note)`, append-only.
A tombstone is a row with `body = null`. See [[Automation]] Q1.

## Related

[[Automation]] · [[Agent Contract]] · [[Daemon And Cadence]] · [[MCP Gateway]]
