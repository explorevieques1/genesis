---
title: Ask Genesis
tags: [ui]
status: building
implemented_by:
  - src/genesis/server/conversation_routes.py
  - ui/src/workspace/panels/ask.tsx
  - ui/src/workspace/panels/help.tsx
  - ui/src/api/client.ts
  - src/genesis/memory/conversations.py
---

# 💬 Ask Genesis

The command line, as a module.

[[Terminal]] built three ways in — `⌘K`, a typed command, voice — and all three
are **transient**: they answer once, into the shell's reply strip, and forget.
`Ask Genesis` is the same input with a memory. It is a module (`AI`) that docks
into any [[Workspaces|workspace]] like a chart or the body map, and the
conversation it holds is saved on the daemon, so it survives a refresh and a
reopen.

## It is not a second command path

Every message posts to `POST /v1/command` — the exact endpoint `⌘K` and voice
post to. The deterministic table in `genesis/commands.py` still runs first, so
*"chart NVDA"* still costs no model call; an unmatched sentence still falls
through to the analyst ladder (`_ask_the_analyst`). The **only** thing the
panel adds to the request is a `conversation` id, and that is the whole of what
makes the exchange persist.

The [[Operating Model]] parity rule holds by construction: there is no
capability here that `⌘K` does not also have, because it is the same call.

## The model is not a knob here

There is no model selector. The orchestrator answers on the tier configured in
`Settings → Model Tiers`, and that is the only place the setting lives. A
per-message override would be a second source of truth for which model runs,
and — per [[LLM Model Tiers]] and the Settings panel's own rule — changing the
tier is a deliberate act with a restart behind it, not something you flick
mid-sentence. The composer shows which tier is answering; it does not let you
change it.

## Shape

- **A conversation rail**, collapsible, on the left — every saved conversation
  newest-first, a *New conversation* button, and a delete affordance per row.
  The rail is the only place a conversation can be thrown away.
- **A transcript** — operator turns and Genesis turns, each Genesis turn
  carrying the `command` that answered and any `detail`, so the work behind the
  answer stays attached ([[Operating Model]] §"an answer arrives with the work
  behind it").
- **A composer** — `↵` sends, `⇧↵` is a newline.

A data-carrying reply (a `canvas_id`) opens its panel through the same
`openPanel` the shell uses — the one sanctioned unasked-for appearance, and the
same one [[Fleet View]] and the voice path already rely on.

## Persistence

See [[Conversation Store]]. A small SQLite database, **deletable** — which is
what keeps it out of the [[Episodic Log]], whose whole contract is that it is
append-only and forever. Losing the conversation store costs the trader their
scrollback and nothing else; every answer was already emitted to the
[[Task Bus]] and, in Phase 1, the log.

## Help — the map for the command line

`HLP` is a sibling module: every module short code (grouped by category, read
from `MODULES`) and every command the deterministic table knows (read from
`GET /v1/commands`, so it cannot drift from what the daemon matches). It is how
the command line stays discoverable without a person having to already know
what to search for. [[Operating Model]] §3 keeps the Home canvas empty; this is
the thing you open when you want the map.

## Related

[[Terminal]] · [[Operating Model]] · [[Workspaces]] · [[Voice UX]] ·
[[Conversation Store]] · [[LLM Model Tiers]] · [[Episodic Log]] · [[UI Stack]]
