---
title: Conversation Store
tags: [schema, ui]
status: building
implemented_by:
  - src/genesis/memory/conversations.py
  - tests/memory/test_conversations.py
  - src/genesis/server/conversation_routes.py
---

# 💬 Conversation Store

Saved [[Ask Genesis]] conversations. A local SQLite database at
`<memory_dir>/conversations.db`, opened per request like every other read store.

## Why it is not the Episodic Log

The [[Episodic Log]] is a forever audit trail, append-only by database trigger.
A conversation is the trader's own chat scrollback, and they get to delete it —
a different lifecycle, so a different store. Same reasoning that keeps the
[[Research Canvas]] arrangement out of the [[Knowledge Graph]].

Nothing here is a source of record. Every answer was already emitted to the
[[Task Bus]] and, in Phase 1, written to the Episodic Log with its `trace_id`.
Losing this database loses scrollback and nothing else.

## Tables

```sql
conversations (
  id       TEXT PRIMARY KEY,   -- ULID, prefix "cv"
  title    TEXT,               -- first line of the opening message, ≤80 chars
  created  TEXT,               -- ISO-8601 UTC, ms
  updated  TEXT                -- bumped on every appended turn
)

turns (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation TEXT REFERENCES conversations(id) ON DELETE CASCADE,
  ts           TEXT,
  role         TEXT,           -- 'operator' | 'genesis'
  text         TEXT,           -- operator: the message; genesis: the spoken reply
  ok           INTEGER,        -- genesis turns only
  command      TEXT,           -- the command name that answered
  detail       TEXT,
  data         TEXT,           -- small JSON, inline — CommandResult.data
  trace        TEXT            -- links the turn back to the Episodic Log
)
```

`ON DELETE CASCADE` plus `PRAGMA foreign_keys=ON` (set by `memory/db.connect`)
means deleting a conversation drops its turns in one statement.

## How a turn is written

Exactly one path: `app._run` handles a `POST /v1/command`, and **if** the
request carried a `conversation` field it calls `ConversationStore.append`,
which writes the operator turn and the Genesis turn together and upserts the
conversation row. Voice and `⌘K` send no `conversation` and are not persisted —
they belong to no conversation.

## Routes

| Route | Method | Returns |
|---|---|---|
| `/v1/conversations` | GET | `{ conversations: [{ id, title, updated, turns }] }` |
| `/v1/conversations/{id}` | GET | `{ conversation: { id, title, turns: [...] } \| null }` |
| `/v1/conversations/{id}/delete` | POST | `{ ok }` |

The one write — delete — sits in `conversation_routes.py` beside the reads
rather than in `app.py`, the same call the [[Research Canvas]] routes make: it
removes the trader's own data, imports no execution code, and there is no order
path to route around.

## Related

[[Ask Genesis]] · [[Episodic Log]] · [[Data Model Overview]] · [[Terminal]] ·
[[Task Bus]]
