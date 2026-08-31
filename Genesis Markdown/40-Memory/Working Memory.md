---
title: Working Memory
tags: [memory]
status: built
implemented_by: [src/genesis/memory/working.py]
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
- A follow-up referencing ambient context is understood correctly.
- Restart expires all pending confirmations, tested.
- Working memory never exceeds its token cap, even under a burst of agent results.

## Related

[[Memory Fabric]] · [[Episodic Log]] · [[Recall Pathways]] · [[Orchestrator]] · [[10-Architecture/Voice Stack]]
