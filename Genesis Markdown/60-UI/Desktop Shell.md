---
title: Desktop Shell
tags: [ui]
status: optional
---

# 🖲️ Desktop Shell

Optional native wrapper. Makes Genesis feel like a presence on the machine rather
than a browser tab you have to remember to open.

Pattern: [[Repo — jarvis]] `src/desktop_app/` — tray app, animated face widget,
settings window, setup wizard, memory viewer, updater. Electron alternative:
[[Repo — Gensis Terminal Official]].

## Components

### Tray icon
State at a glance, without any window open:

| Icon state | Meaning |
|---|---|
| idle | listening for the wake word |
| listening | actively hearing you |
| working | agents running |
| **position open** | you have live risk |
| **degraded** | something is unhealthy |
| **halted** | kill switch engaged |

The last three matter most — they're the states where you want to know without asking.

### Face widget
A small animated presence: idle, listening, thinking, speaking, alert. Optional and
switchable off, but it does real work — it makes the difference between "is it
listening?" and knowing it is.

Pattern: [[Repo — jarvis]] `desktop_app/face_widget.py`.

### Global hotkeys

| Hotkey | Action |
|---|---|
| Push-to-talk | Bypass the wake word entirely |
| Show/hide dashboard | |
| **Kill switch** | Direct to the kill-switch process ([[Kill Switch]]) |
| Quick P&L | Overlay showing position, P&L, portfolio heat, no window |

The kill-switch hotkey should work when the dashboard is closed, the browser is
gone, and the daemon is wedged.

### Settings window
Generated from config metadata rather than hand-written forms — each key declares
type, range, description, and whether it's runtime-editable. Only non-default values
are written back; unknown keys preserved.

Pattern: [[Repo — jarvis]] `desktop_app/settings_window.spec.md`.
Guarded keys ([[Config And Secrets]]) are visibly locked and require confirmation.

### Setup wizard
First run only, minimal friction: pick an audio device, enter API keys, choose the
voice, set the vault path, connect a broker in **paper** mode, pick an initial
[[Risk Envelope]] from conservative presets.

Ends in `advisory` mode with paper credentials. Getting to live is deliberately a
separate journey ([[Safety Invariants]] #6).

Pattern: [[Repo — jarvis]] `desktop_app/setup_wizard.spec.md`.

### Notifications
OS-native for things that must reach you when no window is focused: fills, risk
breaches, invalidations, halts. Deduplicated, matching [[Agent — Watchdog]]'s
notification discipline.

## Separation

The desktop app is a **client**. The core daemon has no knowledge of it and runs
headless on a server if you want it to. Same principle as [[Repo — jarvis]]'s
desktop/core split.

Consequence: closing the desktop app must never stop trading, and must never leave a
position unmanaged.

## Acceptance criteria

- Tray icon reflects state within 1 s.
- Kill-switch hotkey works with the dashboard closed and the daemon hung.
- Closing the desktop app does not affect the daemon or open positions.
- The wizard ends in `advisory` mode with paper credentials, always.
- Settings preserve unknown keys and write only non-defaults.

## Related

[[Dashboard]] · [[Voice UX]] · [[Config And Secrets]] · [[Kill Switch]] ·
[[Repo — jarvis]]
