---
title: Task Manager
tags: [ui]
status: built
implemented_by:
  - ui/src/workspace/panels/tasks.tsx
  - ui/src/workspace/modules.ts
---

# 🗂 Task Manager

`TM` — what Genesis is working on, from wherever you are standing.

## The bug it closes

A question asked on the Home canvas appeared to **stop** when the operator
changed page. It never stopped. [[Workspaces|The dock]] rebuilds its panels per
page, so the panel holding the in-flight turn unmounted and took the only
evidence of the work with it. The daemon kept running, the answer was still
written, the note was still saved — the surface had simply stopped looking.

That failure mode is the one [[Biological Design]] §3 names: the system acted
and could not perceive that it had. The fix is not to keep the panel alive. It
is to give work in flight **a home that is not a page**.

## It holds no state

Every row comes from the store's task ledger, fed by the event socket at app
level, which outlives any page. Nothing here polls and nothing here remembers:
the panel is a window onto `task.dispatched` / `started` / `completed` /
`failed` as [[Event Schema]] defines them. Close it mid-task and reopen it on
another page — the row is still there, still counting.

In flight sorts above finished, newest first. A running task shows the time it
has been running rather than a blank, because the blank is what made a working
system read as a stalled one.

## It reads. It does not cancel

There is no cancel button. The [[Task Bus]] has no cancel path, and a button
that appeared to stop a task it cannot reach would be a proprioceptive lie —
a worse bug than the one this panel closes. When cancellation exists on the
bus, it earns a button here; not before.

## Parity

`TM` is a module like any other: `open TM`, or by name in the palette
([[Terminal]]). It seeds into no layout — the [[Operating Model]] §3 canvas
opens empty, and this opens when you want to know.

---
Related: [[Fleet View]] · [[Terminal]] · [[Workspaces]] · [[Event Schema]] · [[Ask Genesis]] · [[Biological Design]]
