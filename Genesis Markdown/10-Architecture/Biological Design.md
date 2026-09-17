---
title: Biological Design
tags: [architecture, moc, philosophy]
status: building
implemented_by: [src/genesis/voice/reflex.py, ui/src/components/PhaseMark.tsx, tests/test_reflex.py, ui/src/workspace/panels/system.tsx]
---

# 🧬 Biological Design

**The organising metaphor for the whole system.** Genesis is built as an
organism, not as a chatbot with tools bolted on. This note is the map from
biology to architecture, and the three principles that make the metaphor
load-bearing rather than decorative.

> [!important] The LLM is not the agent
> A brain in a vat is not an organism. The LLM is **one organ**. The agent is the
> whole loop — perception, memory, rhythm, reflex, action and homeostasis
> together.
>
> This is the metaphor's biggest payoff, because it relocates where you look for
> bugs. People say *"the agent decided to…"* when what happened is that a token
> sampler produced text and some code executed it. Most agent failures are not
> reasoning failures. They are **missing reflexes, memory that was never
> written, a tool that lied about succeeding, or a loop with no circuit
> breaker.** None of those are fixed by a better prompt.

---

## The map

| Biology | Genesis | Where |
|---|---|---|
| Brain | The LLM — *only* for genuinely ambiguous judgement | [[LLM Model Tiers]] |
| Working memory | Context window, conversation buffer, ambient buffer | [[Working Memory]] |
| Long-term memory | Episodic log, graph, vectors, ledger | [[Memory Fabric]] |
| **Muscle memory** | Hardcoded logic, rules, guards — `tier: none` | [[Pre-Trade Risk Engine]] · [[Safety Invariants]] |
| Hands | Tools and function calls, behind the strictest guards | [[MCP Gateway]] · [[genesis-execution-mcp]] |
| Senses | Feeds, retrievers, API and file reads | [[Market Data Sources]] · [[genesis-tradingview-mcp]] |
| **Nervous system** | Message bus, lanes, event loop | [[Task Bus]] |
| **Heartbeat** | The daemon loop and scheduler | [[Daemon And Cadence]] |
| Endocrine system | Config, budgets, mode flags — slow global state | [[Config And Secrets]] · [[Approval Modes]] · [[Risk Envelope]] |
| **Pain** | Typed errors, alerts, validation failures | [[Error Handling And Degradation]] |
| Immune system | Guardrails, fencing, sanitisation, allow-lists | [[MCP Gateway]] · [[Agent Contract]] |
| Homeostasis | Health checks, circuit breakers, kill switch | [[Kill Switch]] · [[Agent — Watchdog]] |
| **Proprioception** | Observability, tracing, reconciliation, self-state | [[Observability]] · [[Trade Ledger]] |
| Metabolism | Token and compute cost, rate limits, capital at risk | [[LLM Model Tiers]] · [[Risk Envelope]] |
| DNA | System prompts **and** this vault | [[Conventions]] · [[Vault Map]] |
| Learning | Evals, consolidation, prompt and memory updates | `evals/` · [[Memory Consolidation]] · [[Agent — Insight Miner]] |

Bold rows are the ones already built in [[Build Order|Phase 1]].

---

## Three principles that carry weight

### 1. The reflex arc — the fast path never waits for the slow path

Your hand leaves a hot stove before your brain knows about it. The signal goes
spine → muscle, and only *then* reports upward. That is not a limitation of the
design, it **is** the design.

Most bad agentic systems route everything through the LLM. *"Should I retry this
failed HTTP call?"* does not need a language model. Neither does *"is this order
size above my position limit?"* Those are **reflexes**: deterministic,
sub-millisecond, and incapable of hallucinating.

For a trading system this is not an efficiency argument, it is a **safety
requirement**. A max-position check, a fat-finger guard, a drawdown kill switch
must all be reflexes — because *a reflex cannot be talked out of firing by a
persuasive prompt.*

This is why [[Safety Invariants]] §3 puts the entire execution family, plus
backtest, metrics, allocation and level-watch, at `tier: none`. Those are not
"agents we haven't given a model to yet". They are **spinal cord**, and giving
one a model would be the bug.

> [!tip] The test for a reflex
> If the answer is wrong when a clever attacker writes the input, it must not be
> a reflex. If the answer is wrong when a *language model* writes the input, it
> **must** be one.

### 2. Afferent and efferent are physically different pathways

Sensory nerves run inward, motor nerves run outward, and they are not the same
wires. Worth copying exactly: **keep the read path and the write path
structurally separate.**

| | Afferent (read) | Efferent (write) |
|---|---|---|
| Cost of being wrong | low | catastrophic |
| Retryable | freely | never blindly — query by idempotency key first |
| Parallelisable | yes | ordered per symbol |
| Needs authorisation | no | always, single-use and signed |
| Needs audit | light | complete, or it is a bug |

When reads and writes sit in one undifferentiated tool list, you end up applying
write-level caution to reads (slow) or read-level casualness to writes
(catastrophic).

Genesis already does this in the place it matters most: there is no
`place_order` tool at all, only `propose_order` → approval → `place_approved`,
and [[genesis-tradingview-mcp]] defines **no** order tool so an automation server
that can click cannot click *Buy*.

**What this principle adds:** the split should be explicit at the
[[MCP Gateway]] tool surface for *every* server, not just the execution path —
each tool declares itself afferent or efferent, and the gateway applies the
matching policy rather than trusting each server to be careful.

### 3. Proprioception before ambition

Proprioception is knowing where your own limbs are without looking. Its failure
mode is **drift**: you believe your hand is somewhere it is not.

For Genesis, proprioceptive drift is the broker's actual state diverging from
what the system believes — and it is *the failure most likely to lose real money
quietly*. Loudly wrong is survivable. Quietly wrong compounds.

> [!danger] An agent that can act but cannot accurately perceive its own state is
> the dangerous configuration.
> Build the sense before the muscle. This is why [[Build Order]] Phase 7
> constructs the ledger and the risk engine *before* any broker code, and why any
> reconciliation mismatch is `fatal` with no "small" exception.

---

## Interoception: the vault is the body map

Proprioception senses the *body*. **Interoception** senses the internal state of
the organs — and it is the piece that answers *"how do I stop the LLM guessing
about how I work?"*

The answer is that the self-model already exists: **this vault is it.** A graph
of linked notes describing every organ, its interface, its constraints and its
failure modes — not training data the model half-remembers, but a retrievable
map of the actual body, kept in sync with the actual code.

Four mechanisms make it real:

| Mechanism | Biological role |
|---|---|
| `implemented_by:` frontmatter | The nerve from the map to the organ it describes |
| [[Vault Map]] | The index — how a signal finds the right note |
| Spec-pointer comment in every source file | The return nerve, organ back to map |
| `scripts/check_body_map.py` | The reflex test — it fails when the map lies |

> [!warning] The map was lying in 65 places — 2026-09-17
> A rule with no test is a preference. `check_body_map.py` was written to test
> hard rule 6 and immediately found 56 **cut forward nerves** (code carrying
> `# Spec:` for a note whose `implemented_by:` never mentioned it) and 9 stale
> statuses — including [[MCP Gateway]] at `status: spec` with 3,859 lines
> behind it. The discipline had been held by hand, and by hand is how it drifts.
>
> Three kinds of drift, and the third is the one to watch: a **phantom limb**,
> where `implemented_by:` names a file that no longer exists. `--fix` repairs
> cut nerves and stale statuses, because both are provable from the code. It
> never removes a phantom limb: a missing file is either an unrecorded deletion
> or a typo, and silently guessing which is the failure the script exists to
> catch.

> [!important] Spec drift *is* proprioceptive drift
> These are the same failure wearing two names. A note that says the risk engine
> does X while the code does Y is a body map that lies — the system reasons
> confidently about an organ it does not actually have.
>
> This is the deep reason for the house rule that **code and spec move in the
> same commit**. It was already a discipline. Under this framing it is a *safety
> property*, and it ranks with reconciliation.

**What Genesis gains from this that a bare LLM cannot have:** when an agent needs
to know how a component behaves, it *reads* rather than *infers*. The system can
answer questions about itself from a source of truth, which is the concrete
version of "talking to itself" — not an inner monologue of generated text, but a
retrieval path into its own documented anatomy.

Open sub-questions on how far to take this are recorded in
[[Open Questions]] §12.

---

## Where the analogy breaks

Four places, each a real design constraint rather than a caveat.

| Biology has | Genesis does not | Consequence |
|---|---|---|
| **Neuroplasticity** — continuous rewiring from experience | Frozen weights | Everything that *looks* like learning is retrieval (better memory) or offline (you changing prompts and shipping). **Never design as if the system improves on its own.** The feedback loop is explicit, and it runs *outside* the daemon — see `evals/` and [[Memory Consolidation]]. |
| **Continuity by default** | Amnesia by default — every call starts from zero | Continuity is an *illusion you manufacture* by re-injecting context. Memory is a feature you build, not a property you get. See [[Working Memory]], [[Recall Pathways]]. |
| **Intrinsic self-preservation** | Nothing that wants to stop before it destroys something | Homeostasis is entirely bolted on. The [[Kill Switch]] must be **external, and outside the agent's own control** — which is why it is a separate process that works when everything else is broken. |
| **Redundancy — cell death is routine** | One daemon dying takes the system down | Biology tolerates constant local failure because it is massively redundant. Redundancy is a thing you pay for. Until then, supervision and honest degradation are the substitute ([[Daemon And Cadence]]). |

> [!warning] The metaphor is a design heuristic, not an argument
> A design is not correct because it is biological, and "that's not how a body
> works" is not a reason to reject something a trading system needs. Where this
> note and [[Safety Invariants]] disagree, **the invariants win.** Use the
> analogy to *find* missing organs and misplaced intelligence — not to settle
> decisions that evidence should settle.

---

## What this changes going forward

Concrete, and each one is checkable:

1. **Every new component gets placed on the map before it is built.** Which organ
   is this? If it has no biological role, it may not be a component.
2. **Every component declares reflex or judgement.** `tier: none` is the
   architectural statement "this is spinal". A component that wants a model must
   justify why its decision is genuinely ambiguous. Enforced at load time by
   `AgentDeclaration`: `SPINAL_FAMILIES` (execution, whole) plus
   `SPINAL_AGENTS`, the named reflexes that live in families which otherwise
   think. That second list was missing until 2026-09-17, so `level-watcher` —
   family `charting`, and the agent that decides whether a price crossed a line
   — could have been handed a model with nothing objecting.
3. **Every tool declares afferent or efferent**, and the [[MCP Gateway]] applies
   the matching policy.
4. **Proprioception ships before the muscle it monitors.** No actuator without
   the sense that verifies it acted.
5. **The map may not lie.** Spec and code in the same commit, always.

---

## Acceptance criteria

- Every note in `10-Architecture/`, `20-Agents/` and `30-MCP/` maps to a row in
  the table above, or is a deliberate, documented exception.
- No component at `tier: none` acquires a model tier without a note explaining
  what became ambiguous.
- Every tool in the [[MCP Gateway]] registry is labelled afferent or efferent,
  and no efferent tool is reachable without authorisation.
- The [[Kill Switch]] runs in a process the agent cannot signal.
- A reconciliation mismatch halts the system, with no severity threshold below
  which it is tolerated.
- An agent asked how a component behaves cites the note, rather than describing
  it from the model's own prior.

## Related

[[System Overview]] · [[Safety Invariants]] · [[Pre-Trade Risk Engine]] ·
[[Task Bus]] · [[Daemon And Cadence]] · [[Memory Fabric]] · [[Observability]] ·
[[Error Handling And Degradation]] · [[Kill Switch]] · [[MCP Gateway]] ·
[[LLM Model Tiers]] · [[Agent Contract]] · [[Build Order]] · [[Open Questions]]
