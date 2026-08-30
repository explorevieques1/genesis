# Spec: Genesis Markdown/10-Architecture/Config And Secrets.md
"""Layered configuration and secret loading.

Four layers, later overriding earlier:

1. **Defaults** -- ``default_config.yaml``, shipped in code, safe values.
2. **Config file** -- ``~/.genesis/config.yaml``, human-edited behaviour.
3. **Environment** -- secrets only, never behaviour.
4. **Runtime** -- Dashboard toggles; Phase 6, not implemented here.

Two rules from the spec shape this module:

- **Secrets in env, behaviour in config.** :class:`Secrets` is a separate object
  from :class:`Config`; there is no field on ``Config`` that can hold an API key.
- **Money is ``Decimal``, never ``float``.** Enforced at the YAML parser, not at
  the model -- see :func:`_load_yaml`. A float never exists to be rounded.

Invalid config does not start the system. :func:`load_config` raises
:class:`ConfigError`, whose message names exactly which key is wrong and what was
expected.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

__all__ = [
    "Config",
    "ConfigError",
    "Secrets",
    "DEFAULT_CONFIG_PATH",
    "default_config_text",
    "load_config",
    "load_secrets",
]

DEFAULT_CONFIG_PATH = Path("~/.genesis/config.yaml")
_PACKAGED_DEFAULTS = Path(__file__).with_name("default_config.yaml")


class ConfigError(Exception):
    """Configuration is invalid. The system must not start.

    The message names the offending key path and what was expected, so the
    operator can fix it without reading this file.
    """


# --------------------------------------------------------------------------
# YAML loading -- money becomes Decimal before it can ever be a float
# --------------------------------------------------------------------------


class _DecimalSafeLoader(yaml.SafeLoader):
    """A SafeLoader that yields ``Decimal`` for every YAML float.

    Constructing from the raw scalar *text* is the whole point: ``Decimal(0.1)``
    is 0.1000000000000000055511151231257827, whereas ``Decimal("0.1")`` is
    exactly 0.1. Parsing through ``float`` first would lose the value before any
    model could protect it.
    """


def _decimal_constructor(loader: yaml.Loader, node: yaml.Node) -> Decimal:
    return Decimal(loader.construct_scalar(node))


_DecimalSafeLoader.add_constructor(
    "tag:yaml.org,2002:float", _decimal_constructor
)


def _load_yaml(text: str, source: str) -> dict[str, Any]:
    try:
        data = yaml.load(text, Loader=_DecimalSafeLoader)  # noqa: S506 - custom safe loader
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source}: not valid YAML -- {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{source}: expected a mapping at the top level, got {type(data).__name__}"
        )
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively overlay ``override`` onto ``base``, returning a new dict.

    Mappings merge key-by-key so a config file may set one nested key without
    restating its siblings. Lists replace wholesale -- a half-overridden
    ``symbol_allowlist`` would be a trap.
    """
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            out[key] = _deep_merge(current, value)
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

_Pct = Decimal


class _Strict(BaseModel):
    """Base: reject unknown keys, and never silently coerce a wrong type."""

    model_config = ConfigDict(extra="forbid", strict=False, frozen=True)


class Identity(_Strict):
    wake_word: str = Field(min_length=1)
    voice_id: str | None = None
    persona: str
    verbosity: Literal["terse", "brief", "full"]


class Approval(_Strict):
    mode: Literal["advisory", "confirm", "auto-within-limits", "halt"]
    confirmation_ttl_sec: int = Field(gt=0, le=3600)
    require_ticker_in_confirmation: bool


class SessionWindow(_Strict):
    start: str
    end: str
    tz: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError(f"expected 24-hour HH:MM, got {v!r}")
        return v


class PropFirm(_Strict):
    firm: str
    account_size: Decimal = Field(gt=0)


class Risk(_Strict):
    """The signed envelope. Every percentage is a Decimal in (0, 100].

    A nonsense limit here is the single most dangerous thing in the config file:
    a system that boots with ``max_daily_loss_pct: 150`` is worse than one that
    refuses to boot.
    """

    max_position_pct: _Pct = Field(gt=0, le=100)
    max_portfolio_heat_pct: _Pct = Field(gt=0, le=100)
    max_daily_loss_pct: _Pct = Field(gt=0, le=100)
    max_correlated_exposure_pct: _Pct = Field(gt=0, le=100)
    symbol_allowlist: list[str]
    session_window: SessionWindow
    prop_firm: PropFirm | None = None

    @field_validator("symbol_allowlist")
    @classmethod
    def _non_empty_symbols(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError(
                "expected at least one symbol -- an empty allowlist permits nothing "
                "and is almost certainly a mistake"
            )
        for sym in v:
            if not re.fullmatch(r"[A-Z0-9.:!\-]{1,16}", sym):
                raise ValueError(f"not a plausible ticker: {sym!r}")
        return v


class Broker(_Strict):
    kind: str
    mode: Literal["paper", "live"]


class Brokers(_Strict):
    primary: Broker


class Data(_Strict):
    primary_feed: str
    realtime: bool
    universe: Literal["watchlist", "sp500", "custom"]


class LLMTier(_Strict):
    backend: str
    model: str


class LLM(_Strict):
    nano: LLMTier
    small: LLMTier
    large: LLMTier
    vision: LLMTier
    embedding: LLMTier
    daily_token_budget: int = Field(gt=0)


def _expand(value: Path) -> Path:
    """Expand ``~`` at load time so no downstream caller has to remember to."""
    return Path(value).expanduser()


class Memory(_Strict):
    db_path: Path
    vault_path: Path
    consolidation_hour: int = Field(ge=0, le=23)

    _exp = field_validator("db_path", "vault_path")(classmethod(lambda cls, v: _expand(v)))


class Voice(_Strict):
    stt: Literal["elevenlabs", "whisper-local"]
    tts: Literal["elevenlabs", "piper-local"]
    fallback_to_local: bool


class Logging(_Strict):
    console: bool
    level: Literal["debug", "info", "warn", "error"]
    jsonl_path: Path

    _exp = field_validator("jsonl_path")(classmethod(lambda cls, v: _expand(v)))


class Config(_Strict):
    """The validated, immutable system configuration."""

    identity: Identity
    approval: Approval
    risk: Risk
    brokers: Brokers
    data: Data
    llm: LLM
    memory: Memory
    # Agent blocks vary per agent and grow through Phases 1-10; validated by the
    # agents themselves against Agent Contract, not pinned here.
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)
    voice: Voice
    logging: Logging

    @property
    def is_live(self) -> bool:
        """True only when the primary broker is in live mode.

        Going live requires *two* independent actions -- this flag and the live
        key present in the environment. Never one flag. See Config And Secrets.
        """
        return self.brokers.primary.mode == "live"


# --------------------------------------------------------------------------
# Secrets -- env only, never logged, never persisted
# --------------------------------------------------------------------------

SECRET_ENV_VARS: tuple[str, ...] = (
    "ELEVENLABS_API_KEY",
    "ANTHROPIC_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "MARKET_DATA_API_KEY",
    "NEWS_API_KEY",
)


class Secrets:
    """Secret material read from the environment.

    Deliberately not a pydantic model and deliberately not part of
    :class:`Config`: it must never be serialised alongside behaviour. ``repr``
    is redacted so a secret cannot reach a log through a stray f-string.
    """

    __slots__ = ("_values",)

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def require(self, name: str) -> str:
        value = self._values.get(name)
        if not value:
            raise ConfigError(
                f"missing secret {name} -- expected it in the environment or "
                f"~/.genesis/.env (see .env.example)"
            )
        return value

    def present(self) -> list[str]:
        """Names of the secrets that are set. Never the values."""
        return sorted(self._values)

    def values(self) -> tuple[str, ...]:
        """The raw secret values, for the log redactor only."""
        return tuple(self._values.values())

    def __contains__(self, name: object) -> bool:
        return name in self._values

    def __repr__(self) -> str:
        return f"Secrets(present={self.present()!r})"


def load_secrets(env_file: Path | None = None) -> Secrets:
    """Read known secrets from ``env_file`` (if present) and the environment.

    The real environment wins over the file. Only names in
    :data:`SECRET_ENV_VARS` are read -- an env var is never allowed to change
    behaviour, only to supply credentials.
    """
    if env_file is not None:
        path = env_file.expanduser()
        if path.is_file():
            _warn_if_world_readable(path)
            from dotenv import dotenv_values

            file_values = dotenv_values(path)
            for key, value in file_values.items():
                if key in SECRET_ENV_VARS and value and key not in os.environ:
                    os.environ[key] = value

    return Secrets(
        {name: os.environ[name] for name in SECRET_ENV_VARS if os.environ.get(name)}
    )


def _warn_if_world_readable(path: Path) -> None:
    """The spec requires 0600 on the env file. Say so rather than silently accept."""
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ConfigError(
            f"{path}: permissions are {mode:04o}, expected 0600 -- a secrets file "
            f"readable by anyone else is a leak. Fix with: chmod 600 {path}"
        )


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def default_config_text() -> str:
    """The shipped default template, verbatim -- what ``config init`` writes."""
    return _PACKAGED_DEFAULTS.read_text(encoding="utf-8")


def load_config(path: Path | None = DEFAULT_CONFIG_PATH) -> Config:
    """Load, merge, and validate the config stack.

    ``path`` is the user's config file; a missing file is fine and means
    "defaults only". Passing ``None`` skips layer 2 entirely, which is what the
    tests use to assert the shipped defaults stand on their own.

    Raises :class:`ConfigError` naming the exact offending key. The system must
    not start on an invalid config.
    """
    merged = _load_yaml(default_config_text(), str(_PACKAGED_DEFAULTS))

    if path is not None:
        user_path = path.expanduser()
        if user_path.is_file():
            user = _load_yaml(
                user_path.read_text(encoding="utf-8"), str(user_path)
            )
            merged = _deep_merge(merged, user)

    try:
        return Config.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc, path)) from exc


def _format_validation_error(exc: ValidationError, path: Path | None) -> str:
    """Turn pydantic's error list into 'exactly which key is wrong'."""
    source = str(path.expanduser()) if path is not None else "shipped defaults"
    lines = [
        f"invalid configuration ({exc.error_count()} problem"
        f"{'s' if exc.error_count() != 1 else ''}) -- check {source}:"
    ]
    for err in exc.errors():
        key = ".".join(str(p) for p in err["loc"]) or "<root>"
        detail = err["msg"]
        lines.append(f"  {key}: {detail}")
        if "input" in err and err["type"] != "missing":
            lines.append(f"    got: {err['input']!r}")
    return "\n".join(lines)
