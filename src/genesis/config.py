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
    "LiveConfig",
    "default_config_text",
    "load_config",
    "load_secrets",
]

#: ``GENESIS_CONFIG`` selects a whole config profile -- the mechanism behind
#: the development tier table (see ``config-dev.example.yaml``). It is read
#: here rather than plumbed through ``--config`` because most callers reach
#: config through a bare ``load_config()``: the daemon, the read API, the
#: command table and the voice routes all would have ignored the flag, and a
#: profile switch that applies to some of the process is worse than none.
DEFAULT_CONFIG_PATH = Path(os.environ.get("GENESIS_CONFIG") or "~/.genesis/config.yaml")
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
    #: Widen the allow-list beyond the futures roots above to the S&P 500 and
    #: the core ETFs, from the snapshot `genesis universe refresh` writes.
    #: Off by default: turning it on is a decision about what this desk trades,
    #: and a safety control that grew by 500 symbols because of a default would
    #: be the wrong kind of quiet.
    equity_universe: bool = False
    session_window: SessionWindow
    prop_firm: PropFirm | None = None
    #: Futures limits (Open Questions §1: IBKR, CME futures). A percentage of
    #: equity means nothing against an NQ contract's notional, so futures are
    #: capped in contracts and dollars instead.
    max_contracts_per_symbol: int = Field(default=2, ge=1, le=100)
    max_daily_loss_usd: Decimal = Field(default=Decimal("2000"), gt=0)
    #: Fat-finger band: a limit or absolute stop this far from the arrival
    #: quote is refused.
    max_price_deviation_pct: _Pct = Field(default=Decimal("2.0"), gt=0, le=50)

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


class Execution(_Strict):
    """Wiring for the order path. The limits live in :class:`Risk`, the mode in
    :class:`Approval`; this is only where and how the path connects.

    Paper only. The broker connection refuses to start unless
    ``brokers.primary.mode`` is ``paper`` *and* IBKR reports a paper account id.
    """

    enabled: bool = False
    #: IBKR client ids. The order connection must keep the same id across
    #: restarts: IBKR lets only the placing client modify or cancel an order.
    client_id: int = 30
    killswitch_client_id: int = 31
    killswitch_port: int = Field(default=8766, gt=0, lt=65536)
    #: ledger.db, quality.db, halt.json, audit.jsonl
    state_dir: Path = Path("~/.genesis/execution")
    #: How long a position may sit without a working stop before it is flattened.
    protective_grace_sec: int = Field(default=5, gt=0, le=60)

    _exp = field_validator("state_dir")(classmethod(lambda cls, v: _expand(v)))


class Data(_Strict):
    primary_feed: str
    realtime: bool
    universe: Literal["watchlist", "sp500", "custom"]


class MarketDataAdapter(_Strict):
    """One vendor's wiring. See 10-Architecture/Market Data Plane.md.

    ``tier`` is here rather than hardcoded in the adapter because promoting a
    source is a *decision*, and a decision belongs somewhere reviewable. IBKR
    arrives at tier 3 and is promoted to 1 only after the reconciliation
    against Databento is measured and recorded -- "it connected" is not
    evidence of execution truth.
    """

    enabled: bool = True
    tier: int = Field(default=3, ge=1, le=4)
    host: str | None = None
    port: int | None = None
    #: IBKR only: delayed | realtime. Delayed needs no subscription and
    #: exercises every line of the path, so it is the honest default.
    market_data_type: Literal["delayed", "realtime"] | None = None
    #: Databento: history only. It cannot serve live and must not be asked to.
    historical_only: bool = False
    #: IBKR: the API client id. Two processes sharing one ejects both, so the
    #: daemon and an ad-hoc CLI run must not collide.
    client_id: int | None = None
    #: IBKR: run the reconnect Watchdog. Off only for tests -- its soft-timeout
    #: probe is the defence against a wedged subscription, which is the failure
    #: that is silent.
    use_watchdog: bool = True
    #: CSV replay root.
    root: Path | None = None

    _exp = field_validator("root")(
        classmethod(lambda cls, v: _expand(v) if v is not None else v)
    )


class MarketData(_Strict):
    """The market data plane's configuration.

    ``chains`` is Market Data Sources' per-consumer fallback list, resolved in
    one place instead of inside each agent. Adding IBKR once the adapter exists
    is an edit here -- a config change, not a code change, which was the point
    of building the plane before the broker.
    """

    store_path: Path = Path("~/.genesis/market/market.duckdb")
    budget_path: Path = Path("~/.genesis/market/budget.db")

    # The house convention, applied here too. The stores call `.expanduser()`
    # themselves, so this is not load-bearing today -- but a literal
    # "~/.genesis/..." directory appearing in the repo the first time some
    # future caller forgets is the failure it prevents, and consistency with
    # Memory/Logging is worth more than the two lines.
    _exp = field_validator("store_path", "budget_path")(
        classmethod(lambda cls, v: _expand(v))
    )
    adapters: dict[str, MarketDataAdapter] = Field(default_factory=dict)
    chains: dict[str, list[str]] = Field(default_factory=dict)
    #: Series `genesis serve` keeps streaming from IBKR into the store, as
    #: ``{symbol_id, timeframe}``. An explicit contract month, never "the
    #: front month" (Open Questions §13) -- rolling is an edit here.
    live: list[dict[str, str]] = Field(default_factory=list)

    def chain_for(self, consumer: str) -> list[str]:
        """The ordered adapter names for a consumer, falling back to default.

        An explicitly EMPTY chain means "store only" and must not fall through
        to the default. `backtests: []` is Market Data Sources' "stored bars
        only" row, and resolving it to the default chain would let a backtest
        reach a vendor -- which is both the wrong data and, given IBKR's
        two-year expired-contract limit, silently incomplete data.

        So this tests membership rather than truthiness. `or` would be the
        natural spelling and would be wrong in exactly the case that matters.
        """
        if consumer in self.chains:
            return self.chains[consumer]
        return self.chains.get("default", [])


#: Every backend a tier may name. Validated at load so a typo is a config
#: error with the list attached, not a tier that silently resolves to None
#: three minutes into a run.
LLM_BACKENDS = frozenset(
    {"none", "anthropic", "ollama", "onnx-local", "gemini", "groq", "openrouter"}
)


class LLMTier(_Strict):
    backend: str
    model: str

    @field_validator("backend")
    @classmethod
    def _known_backend(cls, value: str) -> str:
        if value not in LLM_BACKENDS:
            known = ", ".join(sorted(LLM_BACKENDS))
            raise ValueError(f"unknown backend {value!r}; expected one of: {known}")
        return value


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
    marketdata: MarketData = Field(default_factory=MarketData)
    execution: Execution = Field(default_factory=Execution)
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
    # Not a credential — the id of the workspace an identity-linked Anthropic
    # key acts in. Required whenever ANTHROPIC_API_KEY is identity-linked: the
    # SDK sends it as the `anthropic-workspace-id` header and every request is
    # a 400 without it. Listed here because this tuple is the only channel the
    # config layer reads environment from. See Config And Secrets §Secrets.
    "ANTHROPIC_WORKSPACE_ID",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "MARKET_DATA_API_KEY",
    "NEWS_API_KEY",
    # MCP Server Catalog §web. The gateway's server configs name the variables
    # they need; a name absent from this tuple is never read from the .env
    # file, so wiring a server means adding it here too.
    "EXA_API_KEY",
    # Development model providers (LLM Model Tiers §Development tiers). Free
    # tiers used to exercise the orchestrator without burning Anthropic
    # credits; never on a live-broker path -- `_tier_backend` refuses to build
    # them when the broker is live.
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    # MCP Server Catalog §fundamentals and §work. SEC_EDGAR_USER_AGENT is not
    # a credential — EDGAR asks for a contact string and 403s an anonymous
    # client — but this tuple is the only channel the config layer reads
    # environment from, and a server that needs a variable must be able to
    # name it.
    "SEC_EDGAR_USER_AGENT",
    "FRED_API_KEY",
    "GITHUB_PERSONAL_ACCESS_TOKEN",
    # The market-data bench: configured, disabled, listed here so that turning
    # one on is a flag rather than a hunt for which variable it wanted.
    # ALPACA_TOOLSETS is deliberately NOT here — it is behaviour, not a
    # credential, and lives in `env:` in default_servers.yaml where it is
    # versioned and reviewable.
    # Open Questions §6 (2026-09-04): historical ONLY, on free credits. IBKR
    # cannot serve backtests -- expired futures contracts more than two years
    # past expiry are gone from its API, and its historical endpoint paces at
    # 60 requests per 10 minutes -- so history and live come from different
    # vendors by necessity. That split is why Market Data Plane is
    # adapter-shaped.
    "DATABENTO_API_KEY",
    "ALPHAVANTAGE_API_KEY",
    "FINANCIAL_DATASETS_API_KEY",
    "FINNHUB_API_KEY",
    # The IBKR login name, so the account panel can say which login the
    # gateway is using. IB_PASSWORD is deliberately absent: only the gateway
    # container reads it, and Genesis has no reason to ever hold it.
    "IB_USERID",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
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


class LiveConfig:
    """A config that notices its file changed. The endocrine system.

    Config And Secrets loads once at start-up, which is right for almost
    everything: the fleets bind their backends at construction, so a tier
    change *cannot* take effect without a restart and both doors say so rather
    than showing a control that does nothing ([[LLM Model Tiers]]).

    The risk envelope is the exception, and it is the one that matters. A
    limit you must restart the daemon to tighten is a limit you will not
    tighten at 15:40 in a drawdown -- which is exactly when tightening is the
    point. Hormones are slow global state, not a boot argument.

    Three properties, each chosen because the alternative is worse:

    **It re-reads on mtime, and only when asked.** No thread, no inotify: the
    check happens when a caller wants a value, which for the risk envelope is
    once per order proposal. A background watcher would swap the envelope
    underneath a half-evaluated proposal.

    **A broken file keeps the last good config.** Fail closed means *the limits
    already in force stay in force*: a YAML typo must not widen a limit, and it
    must not stop the system either. The error is reported once per change, not
    on every read, so a broken file does not fill the log.

    **It never hands back a different object mid-decision.** :meth:`get`
    returns one immutable :class:`Config`; the risk engine reads every value it
    needs from that one object, so a reload between two checks cannot produce a
    decision made against two different envelopes.
    """

    def __init__(self, path: Path | None = DEFAULT_CONFIG_PATH, *, on_error: Any = None) -> None:
        self.path = path
        self._on_error = on_error
        self._config = load_config(path)  # a bad config at boot still refuses to start
        self._stamp = self._mtime()
        self.reloads = 0
        self.last_error: str | None = None

    def _mtime(self) -> float | None:
        if self.path is None:
            return None
        try:
            return self.path.expanduser().stat().st_mtime
        except OSError:
            return None

    def get(self) -> Config:
        """The current config, re-reading the file if it changed."""
        stamp = self._mtime()
        if stamp == self._stamp:
            return self._config
        self._stamp = stamp
        try:
            self._config = load_config(self.path)
            self.reloads += 1
            self.last_error = None
        except ConfigError as exc:
            # Keep the last good one. The limits in force stay in force.
            self.last_error = str(exc)
            if self._on_error is not None:
                self._on_error(exc)
        return self._config

    def state(self) -> dict[str, Any]:
        """What a person needs to see: did it reload, and is the file valid?"""
        return {
            "path": None if self.path is None else str(self.path.expanduser()),
            "reloads": self.reloads,
            "valid": self.last_error is None,
            "error": self.last_error,
        }


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
