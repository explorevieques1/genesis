# Spec: Genesis Markdown/10-Architecture/Observability.md
"""The ``genesis`` command-line entry point.

Console style is the house style from Conventions.md: a leading emoji per line,
indentation for hierarchy. See :mod:`genesis.observability`.

Three commands carry the system: ``config`` proves the loader works and refuses
to start on a bad file, ``daemon`` runs the spine, and ``voice`` is the surface
you talk to.

``daemon`` matters more than its size suggests. The [[Task Bus]] is durable, so
a plan dispatched by voice survives with or without something to run it -- but
survives *unexecuted*. Until this command existed the queue had no consumer
outside the test suite, which meant Phase 1's spine had never actually run.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from genesis import __version__
from genesis.config import (
    DEFAULT_CONFIG_PATH,
    Config,
    ConfigError,
    default_config_text,
    load_config,
    load_secrets,
)
from genesis.observability import Console

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="genesis",
        description="Genesis Agent -- autonomous trading system.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"genesis {__version__}",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        metavar="PATH",
        help=f"config file (default: {DEFAULT_CONFIG_PATH})",
    )

    sub = parser.add_subparsers(dest="command")

    cfg = sub.add_parser("config", help="inspect and manage configuration")
    cfg_sub = cfg.add_subparsers(dest="config_command", required=True)
    cfg_sub.add_parser("check", help="validate the config stack and report")
    cfg_sub.add_parser("show", help="print the effective configuration")
    init = cfg_sub.add_parser(
        "init", help="write the default template to the config path"
    )
    init.add_argument(
        "--force", action="store_true", help="overwrite an existing config file"
    )

    run = sub.add_parser("daemon", help="run the daemon: the forever loop that executes tasks")
    run.add_argument(
        "--tick",
        type=float,
        default=None,
        metavar="SEC",
        help="seconds between ticks (default: the daemon's own cadence)",
    )
    run.add_argument(
        "--once",
        action="store_true",
        help="boot, run a single tick, report, and exit -- a smoke test",
    )

    listen = sub.add_parser("voice", help="run the voice loop (Phase 2)")
    listen.add_argument(
        "--silent", action="store_true", help="run without opening the speakers"
    )
    listen.add_argument(
        "--wake-model", default="tiny.en", help="local wake model size (default: tiny.en)"
    )
    listen.add_argument(
        "--say", metavar="TEXT", help="speak one line and exit -- a voice smoke test"
    )
    listen.add_argument(
        "--no-daemon",
        action="store_true",
        help="do not host a daemon; assume `genesis daemon` is running elsewhere",
    )

    return parser


def _open_bus(config: Config):
    """The one database the daemon and the voice loop share.

    Both processes open the same file. That is the intended arrangement rather
    than a compromise: the bus is the handoff, and a plan dispatched by voice
    is picked up by whichever daemon is running -- or waits durably until one
    is, which is the property Phase 1 was built for.
    """
    from genesis.bus.bus import TaskBus

    config.memory.db_path.parent.mkdir(parents=True, exist_ok=True)
    return TaskBus(config.memory.db_path)


def _build_daemon(config: Config, console: Console, bus):  # noqa: ANN001
    """Assemble the daemon. No agents are registered until Phase 4.

    It runs empty on purpose: the calendar advances, the bus recovers, claims
    expire and are retried, and anything dispatched by voice is claimed and
    fails honestly with *"no agent registered as ..."* rather than sitting
    silently in a queue. An empty fleet that says so beats a queue nobody
    drains.
    """
    from genesis.daemon.calendar import MarketCalendar
    from genesis.daemon.daemon import Daemon

    return Daemon(bus, calendar=MarketCalendar(), console=console)


def _cmd_daemon(config: Config, console: Console, *, tick: float | None, once: bool) -> int:
    from genesis.daemon.daemon import TICK_SEC

    bus = _open_bus(config)
    daemon = _build_daemon(config, console, bus)
    try:
        if once:
            daemon.boot()
            report = daemon.tick()
            with console.nest():
                console.line("\u2705", f"ran {len(report.ran)} task(s), dispatched {len(report.dispatched)}")
            daemon.shutdown()
            return EXIT_OK
        daemon.run_forever(tick_sec=tick if tick is not None else TICK_SEC)
    except KeyboardInterrupt:
        console.info("Stopping.")
    finally:
        bus.close()
    return EXIT_OK


def _cmd_voice(
    config: Config,
    console: Console,
    *,
    silent: bool,
    wake_model: str,
    say: str | None,
    no_daemon: bool = False,
) -> int:
    """Run the voice loop, or speak one line and exit.

    ``--say`` exists because the first question about a voice stack is always
    "does it make sound", and answering it should not require a microphone, a
    wake word, or a quiet room.
    """
    from genesis.orchestrator.build import build_voice_loop

    if say is not None:
        from genesis.voice.player import Player
        from genesis.voice.speaker import Speaker, default_backends
        from genesis.voice.speech import speakable

        backends = default_backends(config.identity.voice_id or "")
        if not backends:
            console.error("No TTS backend. Is ELEVENLABS_API_KEY set?")
            return EXIT_CONFIG_ERROR
        console.info(f"Speaking: {speakable(say)}")
        with Player(sample_rate=24_000) as player:
            result = Speaker(backends, player).say(say)
        console.info(f"Outcome: {result.outcome.value}")
        if result.detail:
            console.warn(result.detail)
        return EXIT_OK if result.ok else EXIT_CONFIG_ERROR

    # The bus the planner dispatches onto, and -- unless told otherwise -- a
    # daemon in this process to drain it. Without one, a dispatched plan is
    # durably queued and never runs, which looks exactly like a hang.
    bus = _open_bus(config)
    daemon = None
    daemon_thread = None
    if not no_daemon:
        daemon = _build_daemon(config, console, bus)
        daemon.boot()
        daemon_thread = threading.Thread(
            target=daemon.run_forever, name="genesis-daemon", daemon=True
        )

    console.info("Loading the local wake model...")
    stack = build_voice_loop(
        config,
        silent=silent,
        wake_model=wake_model,
        on_turn=_print_turn(console),
        bus=bus,
    )
    for note in stack.notes:
        console.warn(note)

    if daemon_thread is not None:
        daemon_thread.start()
        console.info("Daemon running in this process — dispatched plans will execute.")
    else:
        console.warn("No daemon here — plans queue until `genesis daemon` runs.")

    console.info(f"Listening. Say \"{config.identity.wake_word}\" to wake me. Ctrl-C to stop.")
    try:
        stack.loop.start()
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        console.info("Stopping.")
    finally:
        stack.close()
        if daemon is not None:
            daemon.shutdown()
        bus.close()
    return EXIT_OK


def _print_turn(console: Console):
    def show(turn) -> None:  # noqa: ANN001
        if turn.intent in ("ambient", "echo"):
            return  # the room talking, or us. Never noise on the console.
        console.info(f'heard: "{turn.heard.strip()}"  [{turn.intent}/{turn.path}]')
        if turn.spoken:
            with console.nest():
                console.info(f'said:  "{turn.spoken}"  ({turn.total_ms:.0f} ms)')
    return show


def _cmd_config_check(config: Config, console: Console) -> int:
    console.line("🧾", f"Config valid · {config.brokers.primary.kind} "
                       f"({config.brokers.primary.mode})")
    with console.nest():
        console.line("🛡️ ", f"Approval mode: {config.approval.mode}")
        console.line(
            "📉",
            f"Risk: max position {config.risk.max_position_pct}% · "
            f"heat {config.risk.max_portfolio_heat_pct}% · "
            f"daily loss {config.risk.max_daily_loss_pct}%",
        )
        console.line("🎯", f"Allowlist: {', '.join(config.risk.symbol_allowlist)}")
        console.line("🧠", f"Vault: {config.memory.vault_path}")

        secrets = load_secrets(Path("~/.genesis/.env"))
        present = secrets.present()
        if present:
            console.line("🔑", f"Secrets present: {', '.join(present)}")
        else:
            console.line("🔑", "Secrets present: none (see .env.example)")

        # Two independent actions to go live -- never one flag.
        if config.is_live and "ALPACA_API_KEY" not in secrets:
            console.warn("broker mode is live but no broker key is present")
    return EXIT_OK


def _cmd_config_show(config: Config, console: Console) -> int:
    import json

    from genesis.observability import _json_default

    print(json.dumps(config.model_dump(mode="python"), indent=2, default=_json_default))
    return EXIT_OK


def _cmd_config_init(path: Path, force: bool, console: Console) -> int:
    target = path.expanduser()
    if target.exists() and not force:
        console.warn(f"{target} already exists — pass --force to overwrite")
        return EXIT_CONFIG_ERROR
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(default_config_text(), encoding="utf-8")
    console.ok(f"Wrote default config to {target}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    console = Console()

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    if args.command == "config" and args.config_command == "init":
        return _cmd_config_init(args.config, args.force, console)

    # Everything else needs a valid config. Fail closed and name the key.
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        console.error("Refusing to start — configuration is invalid.")
        with console.nest():
            for line in str(exc).splitlines():
                print(f"  {line}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    if args.command == "daemon":
        return _cmd_daemon(config, console, tick=args.tick, once=args.once)

    if args.command == "voice":
        return _cmd_voice(
            config,
            console,
            silent=args.silent,
            wake_model=args.wake_model,
            say=args.say,
            no_daemon=args.no_daemon,
        )

    if args.command == "config":
        if args.config_command == "check":
            return _cmd_config_check(config, console)
        if args.config_command == "show":
            return _cmd_config_show(config, console)

    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
