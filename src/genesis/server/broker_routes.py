# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md §Live session · deploy/ib-gateway/README.md
"""Connect a data provider: IBKR login, gateway container, feed, and a test.

Everything here is something a person can do by hand, through the same files
(parity, Operating Model §1):

  save login      ->  edit ``~/.genesis/.env``
  start gateway   ->  ``cd deploy/ib-gateway && docker compose --env-file ~/.genesis/.env up -d``
  save feed       ->  edit ``marketdata`` in ``~/.genesis/config.yaml``
  test            ->  ``genesis ibkr check``

None of it reaches an order path. The gateway keeps Read-Only API on, and
there is no control here to turn it off.

**The password goes in, never out.** It is written to the 0600 env file and no
route returns it -- the settings read reports only whether one is saved.

Every write demands ``content-type: application/json``. That forces a CORS
preflight, so a web page in some other tab cannot post a login to this
loopback server with a "simple" form request.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

ENV_FILE = Path("~/.genesis/.env").expanduser()
GATEWAY_DIR = Path(__file__).resolve().parents[3] / "deploy" / "ib-gateway"
CONTAINER = "genesis-ib-gateway"


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------


def read_env() -> dict[str, str]:
    from dotenv import dotenv_values

    return {k: v or "" for k, v in dotenv_values(ENV_FILE).items()} if ENV_FILE.is_file() else {}


def write_env(updates: dict[str, str]) -> None:
    """Set keys in the env file, keeping every other line as it was. 0600."""
    for key, value in updates.items():
        if "'" in value or "\n" in value:
            raise ValueError(f"{key} cannot contain a single quote or a newline")
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.is_file() else []
    pending = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in pending and not line.lstrip().startswith("#"):
            lines[i] = f"{key}='{pending.pop(key)}'"
    lines += [f"{k}='{v}'" for k, v in pending.items()]
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ENV_FILE.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.chmod(0o600)
    tmp.replace(ENV_FILE)


def user_config_path() -> Path:
    from genesis.config import DEFAULT_CONFIG_PATH

    return DEFAULT_CONFIG_PATH.expanduser()


def write_feed(feed: dict[str, Any]) -> None:
    """Merge the IBKR feed settings into the user config, validated before it sticks.

    # ponytail: yaml round-trip drops comments in ~/.genesis/config.yaml. Use
    # ruamel.yaml if hand-written comments there start to matter.
    """
    from genesis.config import load_config

    path = user_config_path()
    before = path.read_text() if path.is_file() else ""
    doc = yaml.safe_load(before) or {}
    md = doc.setdefault("marketdata", {})
    ibkr = md.setdefault("adapters", {}).setdefault("ibkr", {})
    ibkr.update({
        "enabled": bool(feed["enabled"]),
        "market_data_type": feed["market_data_type"],
        "port": int(feed["port"]),
    })
    md["live"] = feed["live"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    try:
        load_config()
    except Exception:
        path.write_text(before)
        raise


def canonical_series(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """``NQZ6 1m`` -> ``FUT:CME:NQ:2026-12 1m``. A bare ``NQ`` is refused by
    ``resolve_symbol`` with the reason (Open Questions §13) -- surfaced, not guessed."""
    from genesis.marketdata.adapters.ibkr import BAR_SIZES
    from genesis.marketdata.source import resolve_symbol

    out = []
    for row in rows:
        timeframe = str(row.get("timeframe", ""))
        if timeframe not in BAR_SIZES:
            raise ValueError(f"timeframe {timeframe!r}: expected one of {', '.join(BAR_SIZES)}")
        symbol_id = resolve_symbol(str(row.get("symbol_id") or row.get("symbol") or ""))
        entry = {"symbol_id": symbol_id, "timeframe": timeframe}
        if entry not in out:
            out.append(entry)
    return out


# --------------------------------------------------------------------------
# the gateway container
# --------------------------------------------------------------------------


def gateway_state() -> dict[str, Any]:
    try:
        run = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", CONTAINER],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "no-docker", "health": "", "detail": str(exc)}
    if run.returncode != 0:
        return {"status": "absent", "health": "", "detail": "container not created yet"}
    status, _, health = run.stdout.strip().partition("|")
    return {"status": status, "health": health, "detail": ""}


def gateway(action: str) -> dict[str, Any]:
    if not (GATEWAY_DIR / "docker-compose.yml").is_file():
        raise ValueError(f"no docker-compose.yml at {GATEWAY_DIR}")
    args = {
        "start": ["up", "-d"],  # recreates the container if the login changed
        "stop": ["stop"],
    }.get(action)
    if args is None:
        raise ValueError("action must be start or stop")
    run = subprocess.run(
        ["docker", "compose", "--env-file", str(ENV_FILE), *args],
        cwd=GATEWAY_DIR, capture_output=True, text=True, timeout=300,
    )
    log.info("operator: gateway %s -> exit %s", action, run.returncode)
    return {"ok": run.returncode == 0, "output": (run.stdout + run.stderr)[-2000:], **gateway_state()}


# --------------------------------------------------------------------------
# the test — layered, because each layer fails differently
# --------------------------------------------------------------------------


def check_connection() -> list[dict[str, Any]]:
    from genesis.config import load_config
    from genesis.errors import GenesisError
    from genesis.marketdata.adapters.ibkr import IbkrAdapter, IbkrConnection
    from genesis.marketdata.interface import BarRequest

    steps: list[dict[str, Any]] = []

    def step(name: str, ok: bool, detail: str) -> bool:
        steps.append({"step": name, "ok": ok, "detail": detail})
        return ok

    env = read_env()
    if not step("login saved", bool(env.get("IB_USERID") and env.get("IB_PASSWORD")),
                f"{env.get('IB_USERID') or 'no IB_USERID'} · {env.get('IB_TRADING_MODE', 'paper')}"
                if env.get("IB_PASSWORD") else "IB_USERID / IB_PASSWORD missing from ~/.genesis/.env"):
        return steps

    gw = gateway_state()
    if not step("gateway container", gw["status"] == "running",
                f"{gw['status']}{' · ' + gw['health'] if gw['health'] else ''}{' · ' + gw['detail'] if gw['detail'] else ''}"):
        return steps

    config = load_config()
    spec = config.marketdata.adapters["ibkr"]
    host, port = spec.host or "127.0.0.1", spec.port or 4002
    try:
        socket.create_connection((host, port), timeout=3).close()
    except OSError as exc:
        step("api socket", False, f"{host}:{port} — {exc}. Login may still be in progress (a few minutes), or 2FA is waiting on your phone.")
        return steps
    step("api socket", True, f"{host}:{port} open")

    connection = IbkrConnection(
        host=host, port=port,
        # +2: the adapter holds +0 for commands, the live session +1.
        client_id=(spec.client_id if spec.client_id is not None else 17) + 2,
        market_data_type=spec.market_data_type or "delayed",
        use_watchdog=False, connect_timeout=15,
    )
    try:
        ib = connection.connect()
        accounts = list(ib.managedAccounts())
        mode = "paper" if accounts and all(a.startswith("D") for a in accounts) else "live"
        step("logged in", True, f"server time {ib.reqCurrentTime():%H:%M:%S} UTC · {', '.join(accounts)} · {mode}")

        probes = [s["symbol_id"] for s in config.marketdata.live][:1] or [_es_probe()]
        end = datetime.now(UTC)
        bars = IbkrAdapter(connection=connection, tier=spec.tier).fetch(
            BarRequest(probes[0], "5m", end - timedelta(days=3), end)
        )
        if bars:
            step("market data", True,
                 f"{probes[0]} · {len(bars)} 5m bars · last {bars[-1].close} at {bars[-1].ts:%a %H:%M} UTC · {spec.market_data_type}")
        else:
            step("market data", False, f"{probes[0]}: no bars — no data permission for this contract, or the contract has expired")
    except GenesisError as exc:
        step("api", False, exc.reason)
    finally:
        connection.disconnect()
    return steps


def _es_probe() -> str:
    from genesis.cli import _ibkr_probe_symbol
    from genesis.config import load_config

    return _ibkr_probe_symbol(load_config())


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


def broker_routes() -> list[Any]:
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    def refuse(reason: str, status: int = 400) -> JSONResponse:
        return JSONResponse({"ok": False, "reason": reason}, status_code=status)

    async def body(request: Request) -> dict[str, Any] | None:
        if not request.headers.get("content-type", "").startswith("application/json"):
            return None
        return await request.json()

    async def settings(request: Request) -> JSONResponse:
        from genesis.config import load_config

        env = read_env()
        spec = load_config().marketdata
        ibkr = spec.adapters.get("ibkr")
        return JSONResponse({
            "available": True,
            "login": {
                "userid": env.get("IB_USERID", ""),
                "password_saved": bool(env.get("IB_PASSWORD")),
                "trading_mode": env.get("IB_TRADING_MODE", "paper"),
                "env_file": str(ENV_FILE),
            },
            "gateway": await asyncio.to_thread(gateway_state),
            "feed": {
                "enabled": bool(ibkr and ibkr.enabled),
                "market_data_type": (ibkr.market_data_type if ibkr else None) or "delayed",
                "port": (ibkr.port if ibkr else None) or 4002,
                "live": spec.live,
            },
        })

    async def save_login(request: Request) -> JSONResponse:
        data = await body(request)
        if data is None:
            return refuse("content-type must be application/json", 415)
        userid = str(data.get("userid", "")).strip()
        mode = data.get("trading_mode", "paper")
        if not userid or mode not in ("paper", "live"):
            return refuse("userid is required, trading_mode is paper or live")
        # The host port stays 4002 in both modes so Genesis's config never
        # changes; only the container's relay port follows the mode.
        # Orders are open on paper only (Open Questions §1, 2026-09-13). A live
        # login stays read-only: going live is Paper To Live Promotion, a
        # separate decision, never a side effect of saving a login.
        updates = {"IB_USERID": userid, "IB_TRADING_MODE": mode,
                   "IB_READ_ONLY_API": "no" if mode == "paper" else "yes",
                   "IB_API_RELAY_PORT": "4004" if mode == "paper" else "4003"}
        if data.get("password"):
            updates["IB_PASSWORD"] = str(data["password"])
        try:
            write_env(updates)
        except ValueError as exc:
            return refuse(str(exc))
        os.environ["IB_USERID"] = userid
        log.info("operator: saved IBKR login (userid=%s, mode=%s, password %s)",
                 userid, mode, "changed" if "IB_PASSWORD" in updates else "unchanged")
        return JSONResponse({"ok": True})

    async def save_feed(request: Request) -> JSONResponse:
        from genesis.config import load_config
        from genesis.errors import GenesisError
        from genesis.marketdata import ibkr_live

        data = await body(request)
        if data is None:
            return refuse("content-type must be application/json", 415)
        if data.get("market_data_type") not in ("delayed", "realtime"):
            return refuse("market_data_type is delayed or realtime")
        try:
            feed = {**data, "live": canonical_series(list(data.get("live", [])))}
            write_feed(feed)
        except GenesisError as exc:
            return refuse(exc.reason)
        except Exception as exc:  # noqa: BLE001 - a bad symbol or config is the operator's to fix
            return refuse(f"{type(exc).__name__}: {exc}")
        ibkr_live.apply(load_config())
        log.info("operator: saved IBKR feed %s", feed)
        return JSONResponse({"ok": True, "live": feed["live"]})

    async def gateway_action(request: Request) -> JSONResponse:
        data = await body(request)
        if data is None:
            return refuse("content-type must be application/json", 415)
        try:
            return JSONResponse(await asyncio.to_thread(gateway, str(data.get("action"))))
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            return refuse(str(exc))

    async def test(request: Request) -> JSONResponse:
        if await body(request) is None:
            return refuse("content-type must be application/json", 415)
        return JSONResponse({"ok": True, "steps": await asyncio.to_thread(check_connection)})

    async def refresh(request: Request) -> JSONResponse:
        """Reconnect the live session (backfill the gap, resync the account)
        and validate every layer. The by-hand door is restarting `genesis
        serve` and running `genesis ibkr check`."""
        from genesis.config import load_config
        from genesis.marketdata import ibkr_live

        if await body(request) is None:
            return refuse("content-type must be application/json", 415)
        config = load_config()
        live = ibkr_live.current()
        if live is not None:
            live.reconfigure(config)
        else:
            ibkr_live.apply(config)
        steps = await asyncio.to_thread(check_connection)
        log.info("operator: refreshed IBKR session -> %s", "ok" if all(s["ok"] for s in steps) else "failed")
        return JSONResponse({"ok": all(s["ok"] for s in steps), "steps": steps})

    return [
        Route("/v1/broker/settings", settings),
        Route("/v1/broker/login", save_login, methods=["POST"]),
        Route("/v1/broker/feed", save_feed, methods=["POST"]),
        Route("/v1/broker/gateway", gateway_action, methods=["POST"]),
        Route("/v1/broker/test", test, methods=["POST"]),
        Route("/v1/broker/refresh", refresh, methods=["POST"]),
    ]
