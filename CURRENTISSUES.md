The caveat — Playwright is the wrong client
playwright.chromium.connect_over_cdp("http://localhost:9222") — the literal line in the Transport section — fails. It retrieves the ws URL, connects the socket, then hangs until a 180s timeout. Raw CDP against that same browser endpoint succeeds in milliseconds, so this is Playwright's browser-attach handshake disagreeing with Electron's target model, not a closed door.

So the spike is a YES, and genesis-tradingview-mcp is viable — but the transport should be a direct CDP websocket client, not Playwright. I'd like to record it that way rather than copy a line into the spec that I've just watched fail.

Two things worth flagging:

A trap for the record. My first attempt failed with bad option: --remote-debugging-port=9222, which looks exactly like "Electron disabled remote debugging" — the NO answer. It wasn't. ELECTRON_RUN_AS_NODE=1 is set in this VS Code extension-host shell, so the binary parsed my flag as a Node CLI option. Any Genesis process that spawns TradingView must launch with that variable unset, or it will silently get a Node REPL instead of a chart. That belongs in the note.

TradingView is currently running from my launch (I found no pre-existing instance, so I didn't disturb anything of yours). Say the word if you want it closed.

Before I write anything: do you want me to record the transport as raw CDP and drop the Playwright line, or keep Playwright mentioned as a tried-and-rejected option with the failure noted? I'd recommend the latter — it stops someone re-attempting it in Phase 3.
___________________________________________________________________________

Agreed on all three. Record it as:

1. Transport = direct CDP websocket client, NOT Playwright. In the Transport
   section, replace the connect_over_cdp line with a raw CDP approach (retrieve
   ws URL from http://localhost:9222/json, open the websocket directly).

2. Keep Playwright as a documented tried-and-rejected option, in a short
   "What doesn't work" note: connect_over_cdp retrieves the ws URL, connects,
   then hangs to a 180s timeout — Playwright's browser-attach handshake
   disagrees with Electron's target model. Raw CDP against the same endpoint
   succeeds in milliseconds. This stops a Phase 3 re-attempt.

3. Add the launch trap to the note, prominently — this is a real bug source:
   - Symptom: `bad option: --remote-debugging-port=9222` looks identical to
     "Electron disabled remote debugging" (the NO answer) but is not.
   - Cause: ELECTRON_RUN_AS_NODE=1 is set in the VS Code extension-host shell,
     so the binary parses the flag as a Node CLI option and you get a Node REPL
     instead of a chart.
   - Rule: any Genesis process that spawns TradingView must launch with
     ELECTRON_RUN_AS_NODE explicitly unset from the child env. Note this in
     genesis-tradingview-mcp.md AND as a one-liner in Error Handling And
     Degradation (or wherever process-spawning belongs).

Spike result: YES — genesis-tradingview-mcp is viable, §11 stands. Record the
YES in Open Questions §11 and the MCP note, with "transport: raw CDP" as the
qualifier.

Yes, close TradingView when you're done with the spike — nothing of mine was
running, so there's nothing to preserve.

Then continue with Task 2.

___________________________________________________________________________

10-Architecture/Biological Design.md — the canonical note. Your mapping table, but every row now points at the actual Genesis component, with the four already built in Phase 1 marked in bold. Then the three principles stated as constraints on code, where the analogy breaks stated as four design rules, and acceptance criteria that can actually be checked.

CLAUDE.md — a top-level section, two routing-table rows, and a sixth hard rule. It's in the router because it constrains code written before anyone opens a note, which is the stated bar for what goes there.

System Overview — a callout above the topology, plus a Framing row in the layers table.

Build Order — a callout explaining that the phase order is the biology: spine and heartbeat first, senses before hands, ledger and risk engine before broker code.

Open Questions §12 — the parts of your idea that aren't decided yet.

Three things worth your attention
1. Your framing supplies a justification the design was missing. tier: none was already in Safety Invariants, but the reason was essentially "LLMs are bad at arithmetic." The reflex arc is a much stronger reason: a reflex cannot be talked out of firing by a persuasive prompt. That reframes those components from "agents we haven't given a model to" into spinal cord, where giving one a model is the bug. Same rule, far harder to erode.

2. Spec drift and proprioceptive drift are the same failure. This is the connection I'd flag as the real payoff. A note claiming the risk engine does X while the code does Y is a body map that lies — the system then reasons confidently about an organ it doesn't have. "Code and spec move in the same commit" was housekeeping discipline; under your framing it's a safety property that ranks with reconciliation. I promoted it to hard rule 6.

3. Your trailing question is already answered — the vault is the body map. You asked what if an LLM were wired to a network of text about the body itself. That's what Genesis Markdown/ is. implemented_by: is the nerve from map to organ, the spec-pointer comment is the return nerve, Vault Map is the index. The concrete version of "talking to itself" isn't generated inner monologue — it's a retrieval path into its own documented anatomy, so an agent reads how a component behaves instead of inferring it.

The open sub-questions are in §12. The one I'd steer you on now: default the self-model to read-only for agents. An agent that can edit its own body map can make the map lie, which is proprioceptive drift arriving by a new route. Humans and /impl write it.

One guard I put in deliberately
The note says plainly that the metaphor is a heuristic, not an argument — a design isn't correct because it's biological, and where this conflicts with Safety Invariants, the invariants win. Framings this satisfying tend to start winning arguments they haven't earned, and this one will be load-bearing for a long time. It's most useful for finding missing organs and misplaced intelligence, which it already did in one place: the afferent/efferent split should be explicit at the MCP Gateway for every server, not just the execution path. That's now a concrete Phase 3 change.

Nothing here touched code — 230 tests still pass, all 28 wikilinks resolve.

Phase 2 is next, and §4 (local LLM horsepower) and §7 (ElevenLabs) want deciding first since they set the voice latency budget. When you kick it off, the reflex-arc question applies immediately: wake word and VAD are senses, intent classification is judgement, and "stop" cutting speech mid-word must be a reflex — it can't wait on the brain.