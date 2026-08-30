---
title: Repo — jarvis
tags: [repo]
---

# Repo — jarvis

`/home/gzacc2002/Work/jarvis/`

**The orchestrator shell blueprint.** A private, offline-first AI voice assistant —
wake-word listening, planner, tool registry, persistent MCP runtime, memory graph,
desktop app, and a serious evals harness. Genesis's [[Orchestrator]],
[[Voice Stack]], [[MCP Gateway]], and [[Memory Fabric]] all borrow from it.

## What to take

| Genesis component | jarvis source |
|---|---|
| [[Voice Stack]] | `src/jarvis/listening/` — `wake_detection.py`, `echo_detection.py`, `transcript_buffer.py`, `state_manager.py`, `intent_judge.py` |
| [[Orchestrator]] planner | `src/jarvis/reply/planner.py` + `planner.spec.md` — fail-open, direct-exec for small models |
| [[MCP Gateway]] registry | `src/jarvis/tools/registry.py`, `base.py`, `types.py` |
| **Smart tool selection** | `src/jarvis/tools/selection.py` + `builtin/tool_search.py` + `tool_search.spec.md` |
| **Persistent MCP runtime** | `src/jarvis/tools/external/mcp_runtime.py` + `mcp_runtime.spec.md` |
| [[Knowledge Graph]] | `src/jarvis/memory/graph.py`, `graph_ops.py`, `graph.spec.md` |
| [[Recall Pathways]] gate | `src/jarvis/memory/recall_gate.py` + `recall_gate.spec.md` |
| [[Working Memory]] | `src/jarvis/memory/conversation.py` |
| [[Agent — Digest]] | `src/jarvis/memory/summariser.spec.md` |
| [[Voice UX]] earcons | `src/jarvis/output/tts.py`, `tune_player.py` |
| [[LLM Model Tiers]] | `src/jarvis/llm/tiers.py`, `factory.py`, `backend.py` |
| [[Desktop Shell]] | `src/desktop_app/` — tray, `face_widget.py`, `settings_window.spec.md`, `setup_wizard.spec.md`, `memory_viewer.py` |
| [[Daemon And Cadence]] | `src/jarvis/daemon.py` |
| Untrusted-content fencing | `src/jarvis/tools/builtin/web_search.spec.md` |
| Eval methodology | `evals/` + `EVALS.md` — 40+ behaviour tests |

## The spec-file discipline

jarvis pairs every module with a `*.spec.md` describing intended behaviour and key
principles, with a registry table in `CLAUDE.md`. Code must match its spec, or the
spec changes first, deliberately.

**Adopt this.** It's the single most valuable practice in the repo, and it's why
this vault exists in the shape it does. See [[Conventions]].

## The evals harness

`evals/` contains tests for the things unit tests can't reach: tool routing, intent
classification, memory recall, multi-turn context, knowledge extraction,
recency-superseding, planner personalisation. `EVALS.md` tracks accuracy over time.

Genesis needs the equivalent for: idea quality, confidence calibration, level
selection restraint, prompt-injection resistance, and risk-rejection correctness.

## Where Genesis deliberately diverges

**ElevenLabs.** jarvis's `CLAUDE.md` explicitly forbids vendor-locked cloud services,
ElevenLabs by name, on offline-first principle:

> Do not add integrations that depend on a specific proprietary cloud vendor (e.g.
> ElevenLabs TTS…), not even as an opt-in feature.

Genesis diverges by design — you asked for ElevenLabs voice. The line Genesis holds
instead: **voice and market data may be cloud; strategy, memory, journal, and risk
stay local.** Audio leaves only after the local wake gate fires, and
[[Voice Stack]] degrades to local Whisper/Piper rather than breaking.

See [[Open Questions]] §7. Note this is a *policy* divergence, not an architectural
one — every pattern above still applies.

## Known limitations worth inheriting awareness of

From its README: primary development on macOS (Linux may lag), voice-only with no
text chat, and "stop" during speech sometimes filtered as echo. That last one is a
real bug to avoid — [[Voice Stack]] specifies that `stop` keywords are always
honoured even when they look like echo.

## Related

[[Orchestrator]] · [[Voice Stack]] · [[MCP Gateway]] · [[Memory Fabric]] ·
[[Desktop Shell]] · [[Conventions]] · [[Repo Map]]
