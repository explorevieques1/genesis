---
title: Config And Secrets
tags: [architecture]
status: built
implemented_by: [src/genesis/config.py, src/genesis/default_config.yaml, tests/test_config.py]
---

# Config And Secrets

## The envelope reloads; everything else does not

**Built 2026-09-17** — `config.LiveConfig`.

Config loads once at start-up, which is right for almost everything: the fleets
bind their model backends at construction, so a tier change *cannot* take
effect without a restart and both doors say so rather than showing a control
that does nothing ([[LLM Model Tiers]]).

The [[Risk Envelope]] is the exception, and it is the one that matters. A limit
you must restart the daemon to tighten is a limit you will not tighten at 15:40
in a drawdown — which is exactly when tightening is the point. Hormones are slow
global state, not a boot argument ([[Biological Design]] §endocrine).

- The [[Agent — Order Manager]] reads the envelope **once per proposal**, from
  one immutable `Config` object, so a reload between two checks of one decision
  is impossible.
- Re-read on `mtime`, on demand. No thread and no `inotify`: a background
  watcher could swap the envelope underneath a half-evaluated proposal.
- **A broken file keeps the limits already in force.** Fail closed here means
  the current envelope stands: a YAML typo must not widen a limit, and must not
  stop the system either. The error is logged once per change, not per read.
- A bad config at *boot* still refuses to start. That has not changed.


## Layers

Later layers override earlier ones:

1. **Defaults** — shipped in code, safe values (`approval_mode: confirm`)
2. **Config file** — `~/.genesis/config.yaml`, human-edited, version-controllable
3. **Environment** — secrets only, never behaviour
4. **Runtime** — [[Dashboard]] toggles; persisted back to the config file with an audit entry

Rule: **secrets in env, behaviour in config.** Never an API key in the YAML.

> [!important] The system-wide default approval mode is `confirm`
> Not `advisory`. This is a [[Safety Invariants|hard rule]]: never ship a default
> that trades unattended. It holds for the shipped defaults, for the template
> written to `~/.genesis/config.yaml`, and for any code path that has to invent a
> mode.
>
> [[Build Order|Phase 7]]'s *"ship in advisory, then confirm"* is a different
> thing — it describes the rollout sequence for [[genesis-execution-mcp]]
> specifically, not the system default. Do not read it as licence to lower this.

## Config sketch

```yaml
identity:
  wake_word: "genesis"
  voice_id: "zmcVlqmyk3Jpn5AVYcAL"   # the configured ElevenLabs voice
  persona: butler        # calm, concise, precise
  verbosity: brief       # terse | brief | full

approval:
  mode: confirm          # advisory | confirm | auto-within-limits | halt
  confirmation_ttl_sec: 60
  require_ticker_in_confirmation: true

risk:                    # the signed envelope — see [[Risk Envelope]]
  max_position_pct: 5.0
  max_portfolio_heat_pct: 6.0
  max_daily_loss_pct: 2.0
  max_correlated_exposure_pct: 10.0
  symbol_allowlist: [NVDA, AMD, AVGO, SPY, QQQ]
  session_window: { start: "09:45", end: "15:45", tz: America/New_York }
  prop_firm: null        # or: { firm: topstep, account_size: 50000 }

brokers:
  primary:
    kind: alpaca
    mode: paper          # paper | live
    # keys come from env

data:
  primary_feed: alpaca
  realtime: false        # see [[Open Questions]] §6
  universe: watchlist    # watchlist | sp500 | custom

llm:
  nano:  { backend: ollama, model: "<small>" }
  small: { backend: ollama, model: "<mid>" }
  large: { backend: anthropic, model: claude-sonnet-5 }
  vision:{ backend: anthropic, model: claude-sonnet-5 }
  embedding: { backend: ollama, model: "<embed>" }
  daily_token_budget: 2000000

memory:
  db_path: ~/.genesis/genesis.db
  vault_path: ~/GenesisVault
  consolidation_hour: 21

agents:
  screener:   { enabled: true, interval_sec: 300 }
  optimizer:  { enabled: true, max_wall_min: 120 }
  ml-signal:  { enabled: false }

voice:
  stt: elevenlabs        # elevenlabs | whisper-local
  tts: elevenlabs        # elevenlabs | piper-local
  fallback_to_local: true
```

## Secrets

| Env var | Used by |
|---|---|
| `ELEVENLABS_API_KEY` | [[10-Architecture/Voice Stack]] |
| `ANTHROPIC_API_KEY` | [[LLM Model Tiers]] large/vision |
| `ANTHROPIC_WORKSPACE_ID` | [[LLM Model Tiers]] — **required** if the Anthropic key is identity-linked |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | [[Agent — Broker Adapter]] |
| `MARKET_DATA_API_KEY` | data MCPs |
| `NEWS_API_KEY` | [[Agent — News And Catalyst]] |

Rules:
- Loaded from a `.env` with `0600` permissions, or the OS keyring.
- **Never** logged, never written to the vault, never sent to an LLM.
- Redaction pass on everything before it's persisted (pattern: [[Repo — jarvis]]
  auto-redaction of sensitive info before disk).
- Live broker keys live in a **separate** env file from paper keys, and switching
  `mode: live` requires both the config change and the live key present. Two
  independent actions to go live — never one flag.

## Settings UI

Generate the settings window from config metadata rather than hand-writing forms:
each key declares type, range, description, and whether it's runtime-editable.
Only non-default values are written back; unknown keys are preserved.

Pattern: [[Repo — jarvis]] `desktop_app/settings_window.spec.md`.

## Guarded keys

Some settings cannot be changed at runtime by voice or by an LLM — only by a human
in the [[Dashboard]], with the change logged to the [[Episodic Log]]:

- anything under `risk:`
- `approval.mode` when loosening ([[Approval Modes]])
- `brokers.*.mode`
- `agents.*.enabled` for execution-family agents

## Validation

Config is validated on boot **and** on every runtime change. Invalid config does not
start the system; it prints exactly which key is wrong and what was expected. A
system that boots with a nonsense risk limit is worse than one that refuses to boot.

## Related

[[Risk Envelope]] · [[Approval Modes]] · [[Safety Invariants]] · [[Dashboard]] · [[Observability]]
