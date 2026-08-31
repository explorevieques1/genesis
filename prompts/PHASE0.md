We are starting Phase 0 of the Genesis build. Code begins now — this repo is
spec-only so far.

FIRST, read these and nothing else:
- CLAUDE.md (loads automatically)
- Genesis Markdown/Genesis Agent — Home.md
- Genesis Markdown/00-Meta/Build Order.md  (Phase 0 section)
- Genesis Markdown/00-Meta/Working With Claude Code.md
- Genesis Markdown/00-Meta/Conventions.md
- Genesis Markdown/00-Meta/Open Questions.md
- Genesis Markdown/10-Architecture/Config And Secrets.md
- Genesis Markdown/10-Architecture/Observability.md
- Genesis Markdown/30-MCP/genesis-tradingview-mcp.md  (Transport + the CDP spike)

Then confirm back to me your understanding of Phase 0's exit criteria and the
house rules (spec-pointer headers, spec+code move together, build_vault_map.py,
Decimal for money, fail honestly) BEFORE writing anything.

We are doing Phase 0 ONLY. Do not build the daemon, task bus, agents, voice, or
MCP gateway — those are Phase 1+. Nothing in Phase 0 is user-visible; it is all
scaffolding.

── DECISIONS (from Open Questions — use these, and record them) ──
Write each of these into Genesis Markdown/00-Meta/Open Questions.md under the
relevant "> Decision:" line, dated 2026-08-30, in the same commit as the scaffold:
- §1 Broker/asset class: Alpaca paper, US equities, for v1.
- §2 Prop firm: none for v1 (Prop Firm Guard stays Phase 10).
- §3 Language split: Python core + Node/Electron dashboard; HTTP+WebSocket
  boundary per Event Schema.
- §5 Vault location: dedicated vault at ~/GenesisVault/.
Leave §4, §6 (tier 1), §7, §8, §9, §10 open — do not decide those now.
If any of the four above conflicts with something in the specs, stop and tell me
rather than working around it.

── TASK 1: The CDP spike (do this first — it gates a whole component) ──
TradingView Desktop is installed at /usr/bin/tradingview.
- Launch it with: tradingview --remote-debugging-port=9222
- Check whether http://localhost:9222/json/version responds and whether you can
  attach over CDP (a short Python script with playwright's connect_over_cdp, or
  even a plain HTTP GET of the /json endpoints, is enough for a yes/no).
- Record a definite YES or NO, with the evidence, in
  Genesis Markdown/30-MCP/genesis-tradingview-mcp.md under the Transport section
  (replace the "Verify this before building anything else" warning with the
  result). Also note it in Open Questions §11.
- If NO: note that the charting surface falls back to lightweight-charts in the
  Dashboard, per the Build Order. Do not build either path now — just record.

── TASK 2: Repo scaffold ──
Follow Conventions.md for layout and naming.
- pyproject.toml using uv. Target Python 3.12 (NOT system 3.14 — the trading
  corpus libs won't support 3.14 yet; flag it in Open Questions if you disagree).
  Package name: genesis. Console entry point: `genesis`.
- src/genesis/ package, tests/ mirroring it.
- src/genesis/__init__.py with __version__.
- src/genesis/cli.py — a CLI exposing at least `genesis --version`. Use the
  emoji-prefixed, indented console style from Conventions.md / Observability.md.
- src/genesis/config.py — the layered config loader from Config And Secrets.md:
  code defaults → ~/.genesis/config.yaml → env (secrets only) → (runtime later).
  Validate on boot; refuse to start on invalid config and print exactly which
  key is wrong. Ship the config sketch from that note as the default template.
  Prices/limits that represent money must be Decimal.
- src/genesis/logging.py (or observability.py) — the two non-episodic streams
  from Observability.md: emoji console + JSONL structured log with trace_id /
  agent / event fields. No SQLite episodic log yet (Phase 1).
- .env.example listing the secret env vars from Config And Secrets.md. Real .env
  stays gitignored and 0600.
- Every source file starts with its spec-pointer comment, e.g.
  `# Spec: Genesis Markdown/10-Architecture/Config And Secrets.md`

── TASK 3: Test + eval harness ──
Pattern: ~/Work/jarvis — read its EVALS.md and evals/ layout (pytest.ini,
evals/conftest.py, evals/helpers.py) for the structure, don't copy content.
- pytest configured (pytest.ini or pyproject).
- tests/ with at least one real passing test — e.g. config loads the default
  template and rejects a nonsense risk limit.
- An evals/ directory scaffold (with a README pointing at jarvis's EVALS.md
  pattern) ready for Phase 2 LLM-behaviour evals. No LLM evals yet.

── TASK 4: Close the loop ──
- Update the `status:` / `implemented_by:` frontmatter on Config And Secrets.md
  and Observability.md to reflect what now exists (building, with the paths).
- Run: python3 scripts/build_vault_map.py
- Verify Phase 0 exit criteria and show me the evidence:
  1. `genesis --version` runs
  2. config loads
  3. one passing test (paste the pytest output)
  4. the CDP spike has a recorded yes/no
- Commit as logically separated commits, each pairing code with its spec/note
  changes per the house rule. Show me the commit plan before committing.

Work through the tasks in order. After Task 1 and after Task 2, pause and show me
what you found / built before continuing.