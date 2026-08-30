# Spec: Genesis Markdown/10-Architecture/Observability.md
"""The ``genesis`` command-line entry point.

Console style is the house style from Conventions.md: a leading emoji per line,
indentation for hierarchy. See :mod:`genesis.observability`.

Phase 0 exposes only what the Build Order's exit criteria need -- a version, and
enough of a config surface to prove the loader works and refuses to start on a
bad file. Fleet control (``genesis run``, ``genesis halt``) is Phase 1+.
"""

from __future__ import annotations

import argparse
import sys
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

    return parser


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

    if args.command == "config":
        if args.config_command == "check":
            return _cmd_config_check(config, console)
        if args.config_command == "show":
            return _cmd_config_show(config, console)

    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
