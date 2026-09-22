# IB Gateway, headless

Spec: `Genesis Markdown/10-Architecture/Market Data Plane.md`, Open Questions §1 and §6.

The tier-1 feed runs here. Genesis never talks to IBKR's servers directly — it
talks to a gateway on loopback, and that gateway holds the session.

## Why a container and not the desktop app

IB Gateway is a Java desktop application that must stay logged in. Running it
by hand means someone has to be there for the login, the daily forced restart,
and the API-permission dialog. The `gnzsnz/ib-gateway` image bundles **IBC**,
which handles all three, so the thing that must run for months can actually run
for months.

The daily restart is not optional and not a bug: IBKR disconnects every session
once per day. A system that treats that as an outage pages you at the same time
every morning forever. Here it is a scheduled event at 04:00 ET, before the
pre-market pass.

## One-time setup

**1. Credentials into `~/.genesis/.env`** — never into this directory, never
into git:

```bash
cat >> ~/.genesis/.env <<'EOF'
IB_USERID=your_ibkr_username
IB_PASSWORD=your_ibkr_password
IB_TRADING_MODE=paper
EOF
chmod 600 ~/.genesis/.env
```

**2. Start it:**

```bash
cd deploy/ib-gateway
docker compose --env-file ~/.genesis/.env up -d
docker compose logs -f          # watch the login; expect a few minutes
```

**3. Configure the API.** Usually unnecessary — the image applies `READ_ONLY_API` and the socket settings headless. Only if `genesis ibkr check` fails at the API step, use the GUI once. Uncomment the VNC port in
`docker-compose.yml`, set `VNC_SERVER_PASSWORD` in your env file, restart, and
connect a VNC client to `127.0.0.1:5900`. Then in
**Configure → Settings → API → Settings**:

| Setting | Value | Why |
|---|---|---|
| Enable ActiveX and Socket Clients | ✅ on | Without it there is no socket to connect to. |
| Socket port | `4002` | Paper. Live is 4001. TWS, if ever, is 7497/7496. |
| Trusted IPs | `127.0.0.1` | The container talks to itself; the published port is loopback-bound. |
| **Read-Only API** | paper: **off** · live: ✅ **on** | See below. Set by `IB_READ_ONLY_API`. |
| Read-Only API confirmation | ✅ on | |

## Read-Only API is the point, not a precaution

With Read-Only on, this connection **cannot place an order**. Not "is not
supposed to" — cannot. The broker refuses it.

That is `afferent ≠ efferent` from `Biological Design.md` enforced at the socket
rather than in a code convention, and it is strictly stronger than the same rule
written in Python, because it survives a bug in our code. The Market Data Plane
is a read-only plane; it has no reason to ever turn this off.

**2026-09-13: flipped for paper, and only for paper** (Open Questions §1).
The Phase 7 order path is that separate connection — its own client id
(`execution.client_id`), in `src/genesis/execution/`, where every order spends
a pre-trade risk engine approval. Saving a **paper** login from the Connections
panel writes `IB_READ_ONLY_API=no`; saving a **live** login writes `yes`, so a
live account stays unable to trade until Paper To Live Promotion is a decision
someone made. The data connections still connect with `readonly=True`.

After changing it, recreate the container so IBC applies it:
`docker compose --env-file ~/.genesis/.env up -d` (logs show
`Read-Only API checkbox is now set to: false`).

## Ports

| Port | Mode | Note |
|---|---|---|
| 4002 | Gateway paper | What Genesis uses (container 4004, via socat). Leave it here until Phase 7. |
| 4001 | Gateway live | Not used. |
| 7497 / 7496 | TWS paper / live | Only if you ever run the desktop app instead. |

All published on `127.0.0.1` only. A bare `4002:4002` would publish on every
interface, and an unauthenticated broker API socket reachable from the LAN
exposes account state even in read-only mode.

## Delayed data works with no subscription

`reqMarketDataType(3)` gives free delayed futures data on an unfunded paper
account. Every line of the adapter — connection, contract qualification, bar
parsing, store writes, rate limiting, the handoff to the Charting Engine — is
exercised by delayed data. When the CME bundle (~$10/month, often waived by
commissions) clears, the market data type changes and nothing else moves.

## Before IBKR is promoted to tier 1

Connecting successfully is **not** evidence that a feed is execution truth.
Tier 1 is the tier `Pre-Trade Risk Engine` reads in Phase 7 and nothing else, so
promoting on the basis of "it connected" is exactly the drift between believed
and actual state that *proprioception before ambition* warns about.

The cutover requires a reconciliation: pull the same ES session from Databento
and from IBKR, diff them, decide the tolerance, **write the number into
`Market Data Sources.md`, and make it a test**. They will not match exactly —
different aggregation and session handling. Measure it once, record it, then
promote.

Until that happens the IBKR adapter is tier 3 like everything else.

## Health

`docker compose ps` shows the healthcheck, which only proves the port is open.
That is a weak signal and it is deliberately not described as more: a real
readiness check ("the API answers `reqCurrentTime`") needs a client library and
belongs in the adapter.

## Checking it from Genesis

```bash
genesis ibkr check          # connect, report what actually works
genesis chart ESZ5 1H       # bars through the store, IBKR first in the chain
genesis ibkr reconcile ESZ5 1H --days 2    # the tier-1 gate
```

`genesis ibkr check` is layered on purpose — library, then socket, then a real
API round trip — because "IBKR is down" is four different problems with four
different fixes, and a single boolean would be the kind of self-knowledge that
is worse than none.

Enable it first: `marketdata.adapters.ibkr.enabled: true` in
`~/.genesis/config.yaml`.

## Reconnect: what Watchdog does here, and what it does not

`ib_async`'s `Watchdog` normally starts and kills a local Java app through IBC.
Under Docker that is wrong in both directions — IBC already runs inside the
container, and this process has no business terminating it.

So Genesis uses Watchdog with a `DockerGatewayController` that **waits for the
container's gateway instead of launching one**, and never terminates it. What
that keeps is the part that matters: the soft-timeout probe. When the API goes
quiet, Watchdog issues a historical request and rebuilds the connection if it
does not answer.

That is the defence against the failure that actually bites — a `keepUpToDate`
subscription wedging after a network blip while the client still believes it is
subscribed. No error, no disconnect, just a market that appears to have gone
quiet. Indistinguishable from a slow session until someone checks.

## Paper account and live futures data

1. **Paper account.** Client Portal → *Settings → Account Settings → Paper
   Trading Account → Configure*. IBKR creates a separate **paper username**
   (and you set its password) with a `DU…` account id. Allow up to a day.
2. **Futures data.** Client Portal → *Settings → User Settings → Market Data
   Subscriptions*, on the **live** login. For NQ/ES, the non-professional
   *CME Real-Time (NP, L1)* is enough; the *US Futures Value Bundle* covers
   CME, CBOT, NYMEX and COMEX. Answer the professional-status questionnaire
   honestly — non-pro is far cheaper.
3. **Share it with paper.** *Paper Trading Account* settings → *Share real-time
   market data subscriptions with paper trading account* → yes. Takes effect
   after the next login, sometimes 24h.
4. **Credentials** — easiest from the Genesis UI: `CON` (or `ACC` → setup) saves the login, starts this container, picks the contracts and runs a test. The *paper* username/password go into `~/.genesis/.env` as
   `IB_USERID` / `IB_PASSWORD` with `IB_TRADING_MODE=paper`. No API key exists
   for this API — the gateway login is the credential.
5. **Realtime.** Once the subscription shows as shared, set
   `market_data_type: realtime` for `marketdata.adapters.ibkr` in
   `~/.genesis/config.yaml`.

One login, one market data session: a live-login TWS or mobile session that
is also pulling CME data can bump the gateway's data. If bars stop and the
`ACC` panel says `quiet`, check for another session first.

## Status

**2026-09-04:** adapter and container landed, tested against a fake client.
**2026-09-12:** the live session (`marketdata/ibkr_live.py`) streams
`marketdata.live` series into the store while `genesis serve` runs, backfills
gaps on start, and feeds the `ACC` account panel. Also fake-client tested only.

**2026-09-13: first contact with a real gateway (paper account).** Proven:
IBC login in paper mode, the socat relay on 4004, the account sync (balances
and buying power arrive at connect), contract qualification for NQZ6 and
ESU6, and **free delayed CME futures bars over the API on an unsubscribed
paper account** — the 1m/5m/1H NQ backfill wrote ~11k bars in ~34s.

Found and fixed on the way: `TWS_COLD_RESTART: 0400` made IBC exit before
logging in (it wants `hh:mm`, and conflicts with `AUTO_RESTART_TIME`); an
already-open paper session parked the login on a dialog
(`EXISTING_SESSION_DETECTED_ACTION`); and a one-day window was requested as
`86401 S`, which IBKR rejects silently.

Still unproven: the daily auto-restart cycle, realtime data, pacing under a
long backfill, and the reconciliation number.
