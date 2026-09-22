---
title: Master Plan v2
tags: [meta, plan]
---

# Master Plan v2

> [!info] What this is, and what it is not
> [[Build Order]] is the construction sequence — ten phases, spine first, hands
> last. It answers *what do I build next so nothing collapses.*
>
> This note sits above it. It answers *what is Genesis for, and what makes it
> worth more than the sum of its screens.* Build Order's Phases 8–10 are
> absorbed here as Arcs 3–5. Where the two disagree, this note is the intent and
> Build Order is the sequence — fix the sequence, don't abandon the intent.

> [!important] Genesis is a private instrument
> One user, one machine, one book. It is not a product, has no customers, and
> is not going to have any. Every decision in this plan is made for a single
> trader's edge, and the phrase *"but how would that work for other users"*
> never constrains anything here again.
>
> This is a simplification with teeth. It removes multi-tenancy, data
> redistribution rights, onboarding, pricing, support and compliance posture
> from the design space *permanently* — and it unlocks one thing no commercial
> system can ever do, which is Arc 1.

---

## 1. The thesis

**A trader's edge is bounded by attention, and Genesis is not bounded that way.**

A good discretionary trader holds five or ten instruments in genuine attention.
They read maybe fifty headlines a day and absorb twenty. They recall three
months of their own reasoning with any fidelity, and less than that honestly.
They properly test about one idea a week.

Everything outside those limits is invisible to them. The market does not care
that they didn't have time.

Genesis's claim is not that it thinks better than you. It is that **it does not
have to choose what to ignore.** It reads everything, continuously, keeps all of
it, tests a thousand versions of an idea overnight, and interrupts you only when
something crosses a line you drew.

Three promises follow, and they are the whole point:

1. **Nothing got past me.** Coverage, not speed. The value is not "instant
   answers" — it is that the thing you would have missed, you didn't.
2. **I remember what you thought, and what happened.** Continuity across years,
   not sessions. It knows what you believed in March and how it aged.
3. **Here is the work.** Every claim arrives with what was read, and when. An
   answer you cannot check is a rumour with good grammar — and since you are
   the only person who will ever audit this system, checkability is not a
   feature for someone else's benefit. It is the only thing standing between
   you and a confident wrong number costing you money.

### The inversion that makes it work

A human decides what to look at *before* they look. That decision is made on no
information, and it is where most edge is lost.

**Genesis does not triage inputs. It triages outputs.** It reads all of it and
decides afterwards what was worth your attention. That inversion is the core
technical bet of the entire system, and every arc below serves it.

### The feeling to aim for

Not "a machine that trades for me." **A senior analyst who worked while I was
asleep, and is waiting to tell me what they found.**

Both halves matter. Real work happened unprompted — that is the autonomy. It
tells you and waits — that is the safety. A system that acts without telling you
is a liability. A system that only answers when spoken to is a search box.

---

## 2. Where Genesis actually stands

Honest inventory, taken 2026-09-20. A starting position, not a scorecard.

**Strong, and unusually so:**

- The organising ideas are enforced in code, not just written down — reflex
  separated from judgement, reads separated from writes, and a spec-to-code
  binding that a script checks mechanically.
- **20 agents genuinely exist** across Charting, Research and Journal.
- The memory fabric is built through all five layers, with consolidation.
- The order path is shaped correctly: nothing reaches a broker without the gate,
  kill switch as its own process, confirm as the default.
- Real taste in the details — four distinct empty states instead of one lying
  grey box, a panel registry that cannot silently drift.

**The three real holes:**

1. **The compute family does not exist.** Strategy is **0 of 7** — Backtest
   Runner, ML Signal, Optimizer, Portfolio & Allocation, Prop Firm Guard, Risk
   Metrics, Strategy Author. Every one unbuilt. This is exactly where "more
   powerful than a human trader" lives, because it is the work a human
   physically cannot do. Genesis can currently *look* and *remember*. It cannot
   yet *work out*.

2. **The senses are narrow, and the disk is empty.** Four price sources,
   headlines, index membership, a calendar. The market store holds **17 MB**
   against **132 GB free**. That is not a system pushing against its limits.
   That is an archive that was never started.

3. **The surface is unverified.** 59 modules, 141 data endpoints, and almost
   nothing proving the data arrives correctly. A system whose promise is
   *"nothing got past me"* cannot have screens that quietly show nothing.

**And one structural warning:** nine of the 59 modules are Genesis looking at
itself, versus three for trading. Self-knowledge is a principle here. Four
overlapping views of "what exists and what state is it in" is a hobby.

---

## 3. The machine, honestly

This plan is built for specific hardware, so the hardware gets stated plainly.

| | |
|---|---|
| CPU | 12th-gen i5-1235U — 2 performance cores, 8 efficiency cores, 15W mobile |
| **RAM** | **7.5 GB total. ~2.4 GB free with the desk open.** |
| GPU | Intel UHD, no CUDA, no usable VRAM |
| Disk | 175 GB internal, **132 GB free** · external 1 TB SSD for bulk |

**Disk is not your constraint. Memory is.** Right now, with the daemon, an IBKR
gateway, Chromium, VS Code and two browsers open, the machine is at roughly 5 GB
of 7.5 GB before a single agent starts thinking hard. Thirty agents reasoning
simultaneously is not a storage problem and no amount of disk fixes it.

Three consequences that shape everything below:

1. **Hoard on disk, think in bursts.** Storage is nearly free and almost
   entirely unused; working memory is scarce. The architecture should write
   enormous amounts to disk and hold very little in RAM at once. Agents run
   staggered, not all at once.
2. **Rent the heavy thinking.** With no CUDA and 7.5 GB, local models stay out
   of the hot path. API models do judgement; the CPU does deterministic
   arithmetic; the disk does remembering. Embeddings can run locally — they
   already do.
3. **Design for the better machine without waiting for it.** Everything that is
   slow today is slow because of RAM and cores, both of which a future desktop
   fixes. Nothing should be *architecturally* limited to this laptop — see
   Arc 5. The right posture is to build as if the hardware is coming, and stage
   the work so this machine can still run it.

---

## 4. The four capabilities

Everything below serves one of these. A feature serving none of them is a
screen, and screens are not the point.

1. **Perception without triage.** It reads all of it and decides afterwards what
   mattered.
2. **Work that runs while nobody is watching.** Thirty agents is not thirty chat
   windows. It is thirty jobs on different angles of one question, each leaving
   a written record. The measure is *how much happened overnight that you didn't
   ask for and were glad of.*
3. **A memory that makes you better.** *"You have taken this setup fourteen
   times, eleven lost, and all eleven were in the first hour."* Built from your
   history, which is why nothing else can ever say it.
4. **Receipts on everything.** The failure mode of every AI analysis tool is a
   confident wrong number. The answer is structural — agents write down what
   they read, and answers show their working.

---

## 5. The arcs

Six movements. Each has a reason, a shape, a demo that proves it, and a list of
what not to build while inside it.

**Arc 1 starts immediately and runs underneath everything else.** It is the one
piece of work where delay has a permanent, unrecoverable cost. Everything else
can wait its turn.

---

### Arc 1 — The hoard

*Starts now. Never finishes.*

**Why this is first, and why it is the single best idea in this plan.**

Genesis being private rather than commercial removes the one constraint that
stops anybody else from doing this: you are not redistributing anything. You can
keep every byte you touch, forever, for your own use.

And there is a category of data that is *enormously* valuable, that vendors
charge fortunes for, and that **cannot be bought retroactively at any price** —
point-in-time history. Not what the earnings number was revised to, but what it
said on the morning it landed. Not the current analyst consensus, but what
consensus was on the day you took the trade. Not today's version of the filing,
but the one before it was quietly amended. Not the index membership now, but on
the date of the backtest.

Every backtest you will ever run is contaminated without it, because today's
data has tomorrow's knowledge baked in. Vendors sell point-in-time archives for
serious money precisely because maintaining one is expensive and *starting one
late is impossible.*

**You have 132 GB free and you are using 17 MB.** The archive costs almost
nothing to run and its value compounds from the first day. In three years it is
the most valuable thing Genesis owns and nobody can sell you a copy.

**What it is:**

- Every bar Genesis ever sees, kept — not a rolling window.
- A dated snapshot of anything that gets revised: estimates, fundamentals,
  filings, ratings, index membership, sector classification.
- The raw text of everything read — filings, transcripts, headlines — stored as
  received, with its date and source, before anything summarises it.
- Your own decisions at full fidelity, forever. Every proposal, every rejection,
  every mark, every reason you typed.
- Bulk and cold storage to the external SSD; hot working data on the internal
  disk.

**Done when:** you can ask *"what did I know about this on 14 March"* and get
the answer as it stood that day, not as it reads now.

**Do not:** build screens for this. The hoard is plumbing that runs in the
background and writes to disk. It is read by agents, not browsed by you.

---

### Arc 0 — Make it true

*Two weeks. Runs alongside Arc 1. Nothing new gets built.*

**Why it stays in the plan even now that nobody is buying anything.** You are
going to trade your own money on this. A system that renders a blank panel it
believes is full is not slightly flawed — it is the exact failure the whole
design is supposed to be immune to, and it is the kind that loses money quietly
because nothing announces it.

**What it is:**

- Log which screens actually get opened, and by whom — you, or Genesis. Two
  weeks of real use turns *"which of these matter"* from an opinion into a fact.
- One sweep that hits every data endpoint and proves it answers with something
  real.
- Every module opened cold on an empty system, then again with the data
  deliberately taken away. The question is not *does it crash*. It is **does it
  tell the truth about why it is empty** — a screen saying *there is nothing
  here* when the truth is *this was never connected* is proprioceptive drift
  wearing a nice interface.
- Merge the self-inspection screens. Four views of the system's own anatomy
  become one.
- Delete or demote anything with no reason to exist. Demoted means Genesis can
  still open it; you are no longer expected to remember it.

**Done when:** you can boot cold, type every code, and nothing lies to you.

**Do not:** add a single module. The reason this arc is needed is that building
a new screen here is *fast*, and low friction is exactly why fifty-nine exist.

---

### Arc 2 — Widen the senses

**Why.** This is the thesis. Genesis is worth more than a terminal only if it
reads things you cannot get through, and right now it reads prices and
headlines — which is what everyone reads.

**The selection rule.** A source qualifies if you *could* read it but never
would, and if what it says can be checked. Public record, voluminous,
verifiable. The edge is not secret data — exotic feeds fail the checkability
test and cost money you should be spending on compute. **The edge is reading the
public record exhaustively while everyone else samples it.**

**What it is:** filings in full, including which risk-factor language changed
since last quarter · earnings calls — what was said, what was asked, what was
dodged, and how tone moved against the last four · options positioning and fund
flows · insider and institutional transactions · the macro calendar as something
Genesis *acts on* · cross-asset context from rates, the dollar and credit.

Everything ingested lands in the hoard first, dated and unprocessed, then gets
read.

**The demo that proves it:** *"What changed about NVDA today?"* answered from
five independent sources, with **where they disagreed** named rather than
averaged away. Disagreement between sources is not noise to smooth over — it is
the single most valuable output, because it is where the information is.

**Do not:** build a screen per source. Sources feed agents, agents produce
conclusions, conclusions get one place to live. A panel per feed is how you got
fifty-nine modules.

---

### Arc 3 — The engine room

**Why.** This makes "thirty traders" literally true rather than aspirational. A
human tests one idea a week and — being human — remembers the tests that worked.
Genesis tests a thousand overnight and, more importantly, **is honest about how
many it tested.** Seven agents specified, zero built. It is the largest gap
between what Genesis is and what it is for.

**What it is:** the Strategy Family — idea authoring, signal discovery,
parameter search, portfolio construction, risk measurement, and the guard that
keeps all of it inside an envelope. Running against the hoard, which by then
holds point-in-time data, which is the difference between a backtest and a
fantasy.

**The discipline to be uncompromising about.** A system that runs ten thousand
backtests and reports the best one has discovered *nothing* — it found the
luckiest coin in a bucket of coins. Held-out data, walk-forward testing, and an
explicit penalty for how many things were tried are the difference between
research and an expensive way to lose money with confidence. The trading corpus
already has production implementations of all of it.

And none of this family reasons with a language model. Sizing, statistics and
stops are arithmetic, and arithmetic that can hallucinate is not a feature. The
model proposes ideas and explains results; the machinery between is
deterministic and boring on purpose.

**On this hardware:** heavy searches run overnight, staggered, one at a time.
This is the arc that will most want the better machine — and it is designed so
that the better machine simply makes it faster, not newly possible.

**Done when:** you describe an idea in a sentence before bed, and by morning
there is an honest verdict — including *"this looked good, and here is the
specific reason not to believe it."* A system that talks you out of your own
ideas is worth having.

**Do not:** build an optimiser before the honest-validation harness exists. That
ordering is the whole ballgame. An optimiser without it manufactures false
confidence at scale, which is strictly worse than nothing.

---

### Arc 4 — The long memory

**Why.** The memory fabric is built. The question is whether it is *earning.*
Storage is not memory. Memory is the system noticing something across time that
you could not have noticed yourself — and the hoard from Arc 1 is what makes it
possible.

**What it is:** turning years of your own decisions into something that talks
back. Not a log you can search — a system that volunteers patterns: which setups
you actually make money on versus which ones you enjoy, what time of day you are
reliably wrong, the thesis you wrote in March that stopped being true in May and
that you are still trading.

**Done when:** the morning briefing contains at least one thing that is true,
about you, and that you did not know.

**Do not:** build more memory *layers*. Five exist and five is enough. This arc
adds no storage. It adds the agents that read what is already there and have the
nerve to tell you something unflattering.

---

### Arc 5 — Genesis speaks first

**Why.** This is the autonomy the whole project reaches for, and the arc most
likely to ruin it — which is why it comes last. Proactivity is only tolerable
from something that has already proven it is right.

**The tension, named and resolved.** The operating model says the canvas opens
empty. A system that speaks first appears to break that. It does not, under one
rule:

> **Genesis interrupts through a narrow channel — a sentence, a voice, a
> notification — never by filling your screen.** Proactivity is a *sentence*,
> not a dashboard. The screen stays yours.

**The interruption budget.** A system that speaks forty times a day is noise,
gets muted in week one, and is then worth zero. Genesis gets a small number of
interruptions per day — start at three — and must spend them well. That single
constraint is what makes it feel like a senior colleague rather than a needy
one, because seniority *is* knowing what is not worth saying.

Spend them on: something crossing a line you drew · a source contradicting a
position you hold · evidence that just undermined a thesis of yours · overnight
work that changes today.

**Done when:** you look back over a week and would have wanted every single
thing it told you unprompted.

**Do not:** let autonomy drift toward execution. Genesis proposes and waits, by
default, always. Unattended trading is something you switch on for a proven
setup inside an envelope — never the default, and never because the system
seemed confident.

---

### Arc 6 — Room to grow

*Small, and mostly about not painting yourself into a corner.*

**Why.** You will eventually move Genesis to a better machine. That is a far
weaker requirement than running it for other people, and it needs almost none of
the work that would have implied. But it needs a little, and the cost of
ignoring it is discovering on moving day that the system is welded to this
laptop.

**What it is:** all state in one place that can be copied · no path hardcoded
anywhere · a backup that has actually been restored at least once · heavy work
able to use more cores and more memory when they exist, without redesign · the
external SSD treated as cold storage rather than a thing Genesis breaks without.

**Done when:** you can copy Genesis to a new machine in an evening and it wakes
up with its entire memory intact.

**Do not:** build for the cloud. Do not build for other users. Do not abstract
anything "in case it needs to run elsewhere." This is a copy job, not an
architecture.

---

## 6. The real risks

Four, in order of how much they would cost you.

### Risk 1 — One disk holds everything

Genesis's entire value, once Arc 1 has been running a year, is **an archive that
cannot be rebuilt or repurchased.** Your trade history, your reasoning, your
point-in-time snapshots — none of it exists anywhere else, and none of it can be
recovered from a vendor.

A failed drive does not set you back a week. It sets you back to zero and you
can never catch up, because the missing history is the part you cannot buy.

**This is the highest-consequence risk in the entire plan and it is solved by
boring, unglamorous backups.** Automatic, versioned, off this machine, and
restored once to prove they work. Do it in Arc 1, not later. A backup that has
never been restored is a belief, not a backup.

### Risk 2 — The machine is the ceiling

7.5 GB of RAM with 2.4 GB free is the binding constraint on everything
ambitious. The symptom will not be a clean error — it will be things getting
slower, agents quietly failing, and the daemon dying under load. That failure
mode has already happened once here: a single oversized summary silently killed
the whole autonomous loop.

**Mitigations are design choices, not fixes:** stagger agents instead of running
them together, stream large reads instead of loading them, keep the Chromium
browser panel closed unless in use, and make the daemon report its own resource
state so degradation is visible rather than mysterious.

### Risk 3 — Thirty agents thinking is a real bill

Continuous analysis on frontier models costs meaningful money per day, and it is
your money with no revenue on the other side. Left unexamined, this is what
makes the system too expensive to leave running at exactly the moment it starts
being useful.

Two levers, both already in the architecture: the reflex/judgement split means
most work should not touch a model at all, and the tier system means the work
that does can use a cheap one. **Every agent needs its tier justified, and cost
per day needs to be a number you look at weekly.**

### Risk 4 — Trusting a tool you can no longer check

You are the only auditor this system will ever have. The moment Genesis becomes
fast and confident at the cost of being checkable, it becomes a machine for
making expensive mistakes on your behalf, and you will not catch them because
you stopped being able to.

**The receipts are the product.** Any feature that trades checkability for speed
or polish is a bad trade, every time.

---

## 7. How to work on this with Claude Code

The existing discipline is the mechanism — the spec-and-code binding, the
vault-first rule, the drift checker. What follows is how to point it here.

**One arc at a time, one slice per session.** An arc is months; a slice is an
afternoon. Never open a session against "Arc 3" — open it against one agent, one
source, one screen.

**Every session has the same shape:**

1. Open the note for the thing being built. Not the vault — the note.
2. State which arc the slice serves and which capability it advances. If it
   serves none, that is the finding; stop and say so.
3. Build the slice.
4. Update the note and the code together, in the same commit.
5. Run the drift checker before committing.

**Delegate the reading.** Exploration goes to the librarian and the corpus
researcher, so the main conversation stays about decisions. Ask for specific
references and short extracts, never file dumps.

**A good session prompt looks like this:**

> *Arc 2, slice: filings ingestion. Capability 1 — perception without triage.
> Read the relevant note first, check the corpus for how this is done in
> production, then propose the smallest version that gets real filings into the
> hoard dated and unprocessed. Tell me what you are deliberately leaving out,
> and what it costs in RAM while it runs.*

Note what that asks for: the smallest version, what was skipped, and the memory
cost. All three matter. The failure mode of an ambitious plan handed to a
capable assistant is forty new modules by Friday.

**Four standing rules:**

- **Nothing new during Arc 0.** The arc exists because building is too easy here.
- **Anything new is reachable by hand.** If it only works by saying a sentence
  and hoping, it is not shipped — and you cannot check its work.
- **Name what you skipped.** A slice that reports only what it built is hiding
  the interesting half.
- **Say what it costs to run.** On this machine, a feature's memory footprint is
  part of whether it is a good idea.

---

## 8. What "working" looks like

Six demos, one per arc. Each is a thing you could show someone in ninety
seconds — which matters because a capability you cannot demonstrate quickly is
usually one you have not really got.

| Arc | The demo |
|---|---|
| 1 | *"What did I know about this on 14 March?"* — answered as it stood that day. |
| 0 | Boot cold, type every code, nothing lies. |
| 2 | *"What changed about NVDA today?"* — five sources, and where they disagreed. |
| 3 | An idea described in a sentence at night; an honest verdict by morning, including why not to believe it. |
| 4 | The briefing tells you something true about your own trading that you did not know. |
| 5 | A week where every unprompted interruption was one you wanted. |
| 6 | Copied to a new machine in an evening, memory intact. |

---

## 9. What not to do

- **Do not build a module because it is easy.** It is easy here. That is the
  problem, not the justification.
- **Do not build a screen that only presents.** Genesis gathers, computes and
  concludes. Presentation without computation is a worse Bloomberg.
- **Do not delay the hoard.** It is the only work in this plan where waiting
  destroys value permanently. Every day unstarted is a day you can never buy.
- **Do not run without backups once the hoard matters.** One disk holding
  something unrepurchasable is the worst risk here.
- **Do not let an optimiser exist before honest validation does.** It
  manufactures confidence, and confidence is the expensive kind of wrong.
- **Do not put arithmetic, sizing or safety on a language model.** Ever.
- **Do not buy exotic data.** It fails the checkability rule and spends money
  better spent on compute. The public record, read exhaustively, is the edge.
- **Do not ship autonomy before the interruption budget is earned.** A muted
  system is worth zero.
- **Do not architect for other users, other machines, or the cloud.** One user,
  one book, forever. Arc 6 is a copy job, not a redesign.
- **Do not let the biological metaphor generate features.** It is a design
  filter — *reflex or judgement* — and a good one. It does not need its own
  screens, and it currently has four.

---

**Related:** [[Build Order]] · [[Biological Design]] · [[Operating Model]] ·
[[Safety Invariants]] · [[Open Questions]] · [[LLM Model Tiers]] ·
[[Memory Fabric]] · [[Trade Ledger]] · [[Trading Corpus Index]]
