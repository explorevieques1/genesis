# Spec: Genesis Markdown/30-MCP/MCP Server Catalog.md
"""What servers exist, and which of their tools we are willing to catalogue.

Layered exactly like :mod:`genesis.config`: defaults shipped in code, overridden
by ``~/.genesis/mcp_servers.yaml``, with **secrets never here** -- a server names
the environment variables it needs and the runtime reads them at connect time.

The one rule in this module that is a safety property rather than ergonomics:

    **A server that can write must name every tool it exposes.**

``read_only: false`` flips :attr:`ServerConfig.explicit_only`, and the registry
then catalogues only tools listed under ``tools:``. This is the mechanism behind
MCP Server Catalog.md's warning about Alpaca: ``alpaca-mcp-server`` ships order
placement in the same server as market data, so registering it by *server* would
put ``place_order`` in the catalogue three phases before the Pre-Trade Risk
Engine exists -- the exact path Safety Invariants §1 forbids. Registering by
*tool name* takes the read half and leaves the rest unreachable.

Forgetting to describe a server is therefore safe and visible: nothing from it
registers, rather than everything from it registering.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from genesis.config import ConfigError
from genesis.mcp.spec import CachePolicy, Trust

__all__ = [
    "DEFAULT_SERVERS_PATH",
    "RateLimitConfig",
    "ServerConfig",
    "ToolConfig",
    "default_servers_text",
    "load_servers",
]

DEFAULT_SERVERS_PATH = Path("~/.genesis/mcp_servers.yaml")

#: ``${NAME}`` — a header value that is really a pointer to a secret.
_ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")
_PACKAGED_DEFAULTS = Path(__file__).with_name("default_servers.yaml")


class CacheConfig(BaseModel):
    """The YAML face of :class:`~genesis.mcp.spec.CachePolicy`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ttl_sec: float | None = Field(default=None, gt=0)
    bar_boundary: bool = False

    def to_policy(self) -> CachePolicy:
        return CachePolicy(ttl_sec=self.ttl_sec, bar_boundary=self.bar_boundary)


class RateLimitConfig(BaseModel):
    """How fast we are willing to call this server.

    Belongs to the *server* rather than to a tool because the quota belongs to
    the API key, and one key is one server. A per-tool limit would let ten
    tools each spend the whole day's allowance.

    Absent means unlimited, which is correct for anything local: throttling the
    clock server protects nobody and adds latency to a time lookup.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    per_minute: float = Field(gt=0)
    #: Defaults to a quarter of the minute's allowance. See limits.py.
    burst: float | None = Field(default=None, gt=0)


class ToolConfig(BaseModel):
    """What we assert about one tool, over and above what the server says.

    A server describes its tools; it does not get to describe its own
    trustworthiness or how long its answers stay true. Those are ours to
    declare, so they live here rather than being read off the wire.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: What the tool is *for*. Defaults to the tool's own name, which makes two
    #: servers offering ``get_quote`` collide loudly rather than both register.
    capability: str | None = None
    #: ``None`` means "believe the server's readOnlyHint, and assume mutating
    #: if it did not say". Set it explicitly for anything that matters.
    mutating: bool | None = None
    trust: Trust | None = None
    cache: CacheConfig = CacheConfig()
    tier: int | None = Field(default=None, ge=1)
    #: Overrides the server's ``call_timeout_sec`` for this tool alone.
    timeout_sec: float | None = Field(default=None, gt=0)
    #: Words a person would use that the tool's own name and description do
    #: not contain. See ToolSpec.keywords for why this exists.
    keywords: tuple[str, ...] = ()

    @field_validator("keywords", mode="before")
    @classmethod
    def _keyword_tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v


class ServerConfig(BaseModel):
    """One MCP server: how to reach it, and what we will take from it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+([-_][a-z0-9]+)*$")  # kebab, Conventions
    transport: Literal["stdio", "http"] = "stdio"

    # stdio
    command: str | None = None
    args: tuple[str, ...] = ()
    #: Names only. Values are read from the environment at connect time, so a
    #: key never sits in a config file -- Config And Secrets, layer 3.
    env_keys: tuple[str, ...] = ()
    #: Environment values set *from this file*, for servers that take
    #: behaviour through the environment rather than through a flag.
    #:
    #: The module rule is "secrets in env, behaviour here", and this is the
    #: half of it that had nowhere to live. ``ALPACA_TOOLSETS`` decides which
    #: tools alpaca-mcp-server exposes at all -- that is behaviour, and
    #: important behaviour, since it is what keeps ``place_stock_order`` off
    #: the wire entirely. Reading it from the environment would put a safety
    #: decision in a shell profile, where it is invisible, unversioned, and
    #: changed by accident. It belongs in the file somebody reviews.
    #:
    #: Never a credential. ``env_keys`` is for those, and a value here is
    #: committed to git.
    env: dict[str, str] = Field(default_factory=dict)

    # http
    url: str | None = None
    #: Headers for an http server. Values may reference an environment
    #: variable as ``${NAME}`` and are resolved at connect time, so the config
    #: file holds the *name* of a secret and never the secret — Config And
    #: Secrets layer 3, extended to headers because hosted MCP servers
    #: authenticate that way (Exa's ``x-api-key``, for one).
    headers: dict[str, str] = Field(default_factory=dict)

    #: Whether this server can change anything in the world. ``False`` here is
    #: a claim we are making, and it unlocks bulk registration -- so it is a
    #: claim to make deliberately.
    read_only: bool = False
    trust: Trust = Trust.UNTRUSTED
    tier: int = Field(default=9, ge=1)
    tools: dict[str, ToolConfig] = Field(default_factory=dict)

    #: Namespace for capabilities this server's tools get by default, e.g.
    #: ``filings`` turns ``get_company_facts`` into ``filings.get_company_facts``.
    #:
    #: Without it, a bulk-registered tool's capability is its own bare name —
    #: and a capability with no namespace is a capability **no allow-list can
    #: grant**, because every entry is either exact or ``prefix.*``. That is why
    #: `time` and `filesystem` above name every tool by hand for no other
    #: reason than to give it a capability. This says the same thing once.
    #:
    #: It also keeps two servers apart. Both `sec-edgar` and `openbb` offer
    #: something called `get_company_facts`; under a prefix they are
    #: `filings.get_company_facts` and `fundamentals.get_company_facts`, which
    #: is the truth. Undecorated they would collide at the same tier and the
    #: registry would refuse to boot — correct, but a strange way to learn that
    #: two unrelated servers happened to agree on a word.
    #:
    #: A per-tool ``capability`` always wins over this.
    capability_prefix: str | None = Field(
        default=None, pattern=r"^[a-z0-9]+([-][a-z0-9]+)*$"
    )

    #: Words that describe every tool on this server, added to each tool's own
    #: keywords. The server-level form exists because the servers that most
    #: need keywords are exactly the ones registered in bulk: a prefixed server
    #: has no `tools:` block to hang a per-tool list on, and "everything from
    #: FRED is about CPI, rates and unemployment" is true of all of them.
    keywords: tuple[str, ...] = ()

    @field_validator("keywords", mode="before")
    @classmethod
    def _server_keyword_tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    #: Register only the tools named in ``tools:``. Defaults to "yes if this
    #: server can write" — but the two questions are genuinely separate, and
    #: conflating them showed up the first time a real catalogue was built.
    #: brave-search cannot write anything and still wants curating: it ships
    #: eight tools, of which a trading desk wants three, and the other five are
    #: pure context rot. Set this true to curate a read-only server.
    explicit_tools: bool | None = None

    #: Free tiers are small and a ban looks exactly like an outage. See
    #: limits.py for why this is enforced locally rather than learned from a
    #: 429 that has already cost the call.
    rate_limit: RateLimitConfig | None = None

    enabled: bool = True
    #: Close an idle session after this long. ``None`` keeps it open forever,
    #: which is right for anything on a latency path and wasteful otherwise.
    idle_timeout_sec: float | None = Field(default=None, gt=0)
    call_timeout_sec: float = Field(default=30.0, gt=0)

    @field_validator("args", "env_keys", mode="before")
    @classmethod
    def _tuple(cls, v: Any) -> Any:
        return tuple(v) if isinstance(v, list) else v

    def model_post_init(self, _: Any) -> None:
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"server {self.id!r}: transport 'stdio' requires a command")
        if self.transport == "http" and not self.url:
            raise ValueError(f"server {self.id!r}: transport 'http' requires a url")
        overlap = set(self.env) & set(self.env_keys)
        if overlap:
            raise ValueError(
                f"server {self.id!r}: {sorted(overlap)} is in both `env:` and "
                f"`env_keys:` — the first is committed to git and the second is "
                f"a credential, and one name cannot be both"
            )
        if self.explicit_only and not self.tools:
            raise ValueError(
                f"server {self.id!r} is not read_only, so it must name the tools "
                f"to register under `tools:` — see MCP Server Catalog.md on Alpaca"
            )

    @property
    def expanded_args(self) -> list[str]:
        """Arguments with ``~`` resolved.

        The child process does no tilde expansion -- that is a shell's job, and
        there is no shell here. A server handed a literal ``~/GenesisVault``
        creates a directory called ``~`` next to wherever it was started, which
        is a failure that looks like success right up until you go looking for
        your notes.
        """
        return [_expand(a) for a in self.args]

    @property
    def explicit_only(self) -> bool:
        """Register only the named tools.

        True for anything that can write, and true for anything an operator
        chose to curate. The write case is a safety rule; the curation case is
        about context rot. Both end here.
        """
        if self.explicit_tools is not None:
            return self.explicit_tools
        return not self.read_only

    def resolved_headers(self) -> dict[str, str]:
        """Headers with ``${VAR}`` references filled in from the environment.

        A missing variable raises rather than sending an empty header: an
        unauthenticated request gets a 401 that reads like a server problem,
        which is a worse error than the true one.
        """
        out: dict[str, str] = {}
        for key, value in self.headers.items():
            match = _ENV_REF.fullmatch(value.strip())
            if match is None:
                out[key] = value
                continue
            name = match.group(1)
            resolved = os.environ.get(name)
            if not resolved:
                raise ConfigError(
                    f"server {self.id!r} header {key!r} needs {name} in the environment"
                )
            out[key] = resolved
        return out

    def child_env(self) -> dict[str, str]:
        """What the server process gets: the secrets it was promised, plus
        the behaviour this file sets.

        A missing key is not filled with an empty string: the server would then
        start, fail to authenticate, and report something less useful than the
        truth.

        Secrets are applied *after* the config values, so a config file can
        never shadow a credential -- a mistyped ``env:`` entry named after a
        key would otherwise hand a server a plausible-looking wrong secret.
        """
        missing = [k for k in self.env_keys if not os.environ.get(k)]
        if missing:
            raise ConfigError(
                f"server {self.id!r} needs {', '.join(missing)} in the environment"
            )
        return {**self.env, **{k: os.environ[k] for k in self.env_keys}}


def _expand(arg: str) -> str:
    """Expand ``~`` at the start of an argument, or after an ``=``.

    The second case is not a flourish: obsidian-mcp takes its vault as
    ``--vault name=/path``, so the tilde is in the middle of the argument and a
    naive startswith check sails straight past it.
    """
    if arg.startswith("~"):
        return str(Path(arg).expanduser())
    if "=" in arg:
        key, _, value = arg.partition("=")
        if value.startswith("~"):
            return f"{key}={Path(value).expanduser()}"
    return arg


def default_servers_text() -> str:
    return _PACKAGED_DEFAULTS.read_text(encoding="utf-8")


def load_servers(path: Path | None = None) -> tuple[ServerConfig, ...]:
    """Load the server catalogue: packaged defaults, then the operator's file.

    A server present in both is replaced wholesale rather than merged. Deep
    merging an allow-list is how an operator ends up with tools they thought
    they had removed.
    """
    merged: dict[str, dict[str, Any]] = {}
    for text, source in _sources(path):
        for raw in _parse(text, source):
            if not isinstance(raw, dict) or "id" not in raw:
                raise ConfigError(f"{source}: every entry under `servers:` needs an id")
            merged[str(raw["id"])] = raw

    out: list[ServerConfig] = []
    for raw in merged.values():
        try:
            out.append(ServerConfig(**raw))
        except ValidationError as exc:
            raise ConfigError(f"server {raw.get('id')!r}: {exc}") from exc
    return tuple(out)


def _sources(path: Path | None) -> list[tuple[str, str]]:
    sources = [(default_servers_text(), "default_servers.yaml")]
    user = (path or DEFAULT_SERVERS_PATH).expanduser()
    if user.is_file():
        sources.append((user.read_text(encoding="utf-8"), str(user)))
    return sources


def _parse(text: str, source: str) -> list[Any]:
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source}: {exc}") from exc
    if not isinstance(doc, dict):
        raise ConfigError(f"{source}: expected a mapping with a `servers:` key")
    servers = doc.get("servers") or []
    if not isinstance(servers, list):
        raise ConfigError(f"{source}: `servers:` must be a list")
    return servers
