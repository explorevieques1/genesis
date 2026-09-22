---
title: Working Memory
tags: [memory]
status: built
implemented_by: [src/genesis/memory/working.py, src/genesis/orchestrator/record.py, tests/orchestrator/test_record.py, tests/test_working_memory.py]
---

# Working Memory

What the system is thinking about *right now*. Fast, small, and disposable.

## Contents

| Item | Detail |
|---|---|
| Conversation turns | Last N exchanges with you, full text |
| **Ambient buffer** | Rolling ~30 s of un-addressed speech — what you were talking about before you said "Genesis" |
| Current task list | The plan the [[Orchestrator]] is executing |
| Active context | What's on the [[Dashboard]], the last chart shown, the symbol under discussion |
| Pending confirmations | Order proposals awaiting your spoken yes, with their expiry |
| Recent agent results | Last few results, so a follow-up doesn't re-run everything |

## The ambient buffer

The feature that makes Genesis feel like a third person in the room rather than a
command line with a microphone.

You and a colleague discuss whether semis are extended. Two minutes later you say
"Genesis, what do you think?" — and it already knows what "this" is, because it has
been buffering.

Rules:
- Buffered **but not acted on**. Ambient speech never triggers work.
- Rolls off by time (~30 s of speech) and by size.
- Cleared on wake, after the relevant portion is handed to intent classification.
- **Never persisted** unless a directed utterance references it. Conversation you
  didn't address to the system does not end up on disk.

Pattern: [[Repo — jarvis]] `listening/transcript_buffer.py`.

## Lifetime and rolloff

```
 turn arrives ──► working memory
                       │
                       ├── age > N minutes, or
                       ├── size > threshold, or
                       └── topic changed
                       │
                       ▼
              summarise ──► [[Episodic Log]]
                       │
                       ▼
              durable facts ──► [[Knowledge Graph]]
```

**Built** — `orchestrator/record.py` is the other end of the `on_rolloff` hook,
and of `restore()`. Two things are deliberate:

*The summary is built deterministically, not by a model.* Rolloff happens inside
`add_turn`, on the voice path; a hosted call there would put a network round trip
between hearing you and answering. A restart summary that is dull but instant and
always correct is the better trade.

*Ambient speech is never written down.* Not the text, not a word count, not a
timestamp — the acceptance criterion below says **zero disk writes**, and the
recorder returns before the append rather than filtering fields on the way past.

The first implementation kept a per-utterance word count "for observability" and
a review caught it against that criterion. The count is not content, but it is a
conversation's *cadence*: how many people are in the room, when they arrived,
when they went quiet. That is a lot to learn from a field nobody thought of as
data, and it would sit beside the [[10-Architecture/Voice Stack]] privacy line —
audio leaves the machine only after the local wake gate fires — quietly
undermining it. A session-local counter serves the [[Dashboard]] without any of
that, and a restart forgets it.

Rolloff is summarisation, not deletion. What was said is preserved in the episodic
log; what it *meant* is preserved in the graph.

## Restart behaviour

Working memory is **deliberately not fully durable**. On restart:

- Conversation turns: restored from the last summary, not verbatim — a fresh start
  is usually correct after a restart
- Task list: restored from the [[Task Bus]], which is durable
- **Pending confirmations: expired.** Never restored.

That last rule is a safety property ([[Task Bus]], [[Approval Modes]]) — a restart
must never resurrect a stale trade confirmation, because the price has moved and you
are not there.

## Size discipline

Working memory is in the hot path of every utterance. It must stay small.

- Hard cap on turns and on total tokens
- Agent results stored as summaries plus a reference, not full payloads
- Chart images referenced by path, never inlined
- Exceeding the cap triggers immediate summarisation, not growth

## Acceptance criteria

- Ambient conversation for 10 minutes produces zero actions and zero disk writes.
  Both halves are tested: no task is dispatched, and the [[Episodic Log]] row
  count is unchanged.
- A follow-up referencing ambient context is understood correctly.
- Restart expires all pending confirmations, tested.
- Working memory never exceeds its token cap, even under a burst of agent results.

## Related

[[Memory Fabric]] · [[Episodic Log]] · [[Recall Pathways]] · [[Orchestrator]] · [[10-Architecture/Voice Stack]]
