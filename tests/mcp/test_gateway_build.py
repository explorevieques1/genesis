# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Start-up: what gets assembled, and what happens when a server is down."""

from __future__ import annotations

import pytest

from genesis.mcp.build import ALLOW_LISTS, build_gateway
from genesis.mcp.registry import EXECUTION_NAMESPACES
from genesis.mcp.servers import ServerConfig, load_servers

# A command that cannot exist, so the failure is fast and local.
MISSING = ServerConfig(id="ghost", command="genesis-no-such-binary", read_only=True)
DISABLED = ServerConfig(id="later", command="x", read_only=True, enabled=False)


@pytest.fixture
def build():
    b = build_gateway((MISSING, DISABLED))
    yield b
    b.gateway.runtime.stop()


def test_a_dead_server_is_recorded_and_start_up_continues(build) -> None:
    """One feed down means proceed with less, never refuse to boot.

    A gateway that would not start because a news server was unreachable takes
    the whole system down for the least important thing in it.
    """
    assert "ghost" in build.failed
    assert build.connected == ()
    assert build.skipped == ("later",)


def test_the_failure_reason_is_actionable(build) -> None:
    """Not 'unhandled errors in a TaskGroup (1 sub-exception)'."""
    reason = build.failed["ghost"]
    assert "genesis-no-such-binary" in reason or "No such file" in reason


def test_the_phase_3_posture_is_writes_yes_orders_no(build) -> None:
    """Genesis may write your vault. It may not go near an order."""
    registry = build.gateway.registry
    assert registry.allow_writes is True
    assert registry.allow_execution_writes is False


def test_no_allow_list_reaches_an_execution_capability() -> None:
    """Read every grant in the file and check none of them touches money.

    A static check over the table, so adding a pattern that opens the broker to
    the orchestrator fails here rather than in Phase 7.
    """
    for agent, patterns in ALLOW_LISTS.items():
        for pattern in patterns:
            assert not pattern.startswith(EXECUTION_NAMESPACES), (
                f"{agent} is granted {pattern!r}, which is execution-class"
            )


def test_no_allow_list_grants_a_bare_namespace_of_everything() -> None:
    for agent, patterns in ALLOW_LISTS.items():
        assert "*" not in patterns, f"{agent} has an unauditable grant"


def test_the_news_agent_is_the_narrowest_grant() -> None:
    """The agent that ingests the most untrusted text writes nothing.

    Asserted as a property rather than a frozen set. The grant grows as
    sources are wired — MCP Server Catalog gives this agent news, filings and
    calendar — and a test pinning the exact tuple would fail on every honest
    addition while catching none of the dishonest ones. What must never change
    is that everything in it is a read, and that none of it is the vault: this
    agent produces results on the bus, and something else decides what is
    worth keeping.
    """
    granted = set(ALLOW_LISTS["news-catalyst"])
    assert not any(p.startswith("vault.") for p in granted)
    assert granted <= {
        "web.*", "news.*", "filings.*", "macro.*", "calendar.*", "papers.*",
        "corporate.*",
    }, (
        f"news-catalyst gained a grant outside its reading brief: {granted}"
    )


def test_the_watchdog_cannot_reach_the_web() -> None:
    """A health probe must never be the thing that ingests an injection."""
    assert not any(
        p.startswith(("web.", "news.")) for p in ALLOW_LISTS["watchdog"]
    )


def test_the_shipped_catalogue_registers_no_execution_capability() -> None:
    """Over the real config, offline: no enabled server names a money tool."""
    for config in load_servers():
        for name, tool in config.tools.items():
            capability = tool.capability or name
            if capability.startswith(EXECUTION_NAMESPACES):
                assert not config.enabled, (
                    f"{config.id}.{name} is execution-class and the server is enabled"
                )


def test_tradingview_is_curated_down_from_its_full_surface() -> None:
    """It ships 73 tools including execute_order and kelly_position_size.

    Registering it by server would be Safety Invariants §1 *and* §3 in one
    line, plus most of the catalogue. Named tools only.
    """
    tv = next(c for c in load_servers() if c.id == "tradingview")
    assert tv.explicit_only
    assert len(tv.tools) <= 8
    forbidden = ("order", "trade", "position_size", "portfolio", "execute")
    for name in tv.tools:
        assert not any(word in name for word in forbidden), f"{name} must not register"


# ----------------------------------------------------------------------
# The shipped catalogue, checked offline
# ----------------------------------------------------------------------


def test_every_curated_server_names_at_least_one_tool() -> None:
    """`explicit_tools` with an empty block registers nothing, silently.

    The server starts, answers, and contributes zero capabilities — which
    looks exactly like a server nobody uses rather than a server that is
    broken. Cheaper to catch here than in a report.
    """
    for config in load_servers():
        if config.explicit_only:
            assert config.tools, (
                f"{config.id} registers only named tools and names none"
            )


def test_every_bulk_registered_server_has_a_capability_prefix() -> None:
    """A bare tool name is a capability no allow-list can ever grant.

    Entries are exact or `prefix.*`, so a bulk-registered tool whose capability
    defaulted to its own name would be unreachable by any grant — visible only
    as an agent that mysteriously cannot do one of its jobs.
    """
    for config in load_servers():
        if config.explicit_only:
            continue
        assert config.capability_prefix, (
            f"{config.id} registers in bulk with no capability_prefix, so "
            f"nothing it offers can be granted"
        )


def test_no_free_source_ever_claims_a_tier_1_price() -> None:
    """The rule that replaced "no market data at all", and the better one.

    Tier is trust, and Safety Invariants §11 turns on it: Pre-Trade Risk
    Engine reads tier 1 and nothing else, because tier 1 means the venue's own
    book. A free public source is fine for answering "what's the high of day"
    out loud and wrong for sizing a position — and the way that distinction
    survives is that no public server is ever allowed to *call itself* tier 1.

    Alpaca is the only tier-1 price source in the catalogue. If a second one
    appears, either it is the broker, or this test has caught the thing it
    exists to catch.
    """
    for config in load_servers():
        for name, tool in config.tools.items():
            capability = tool.capability or f"{config.capability_prefix}.{name}"
            if not capability.startswith(("market-data.", "broker.")):
                continue
            tier = tool.tier if tool.tier is not None else config.tier
            assert tier > 2 or config.id == "alpaca", (
                f"{config.id}.{name} claims {capability} at tier {tier}. "
                f"Tier 1-2 is execution truth; a public feed may not claim it "
                f"— see Market Data Sources.md and Safety Invariants §11"
            )


def test_no_two_enabled_tools_contest_a_capability_at_one_tier() -> None:
    """A tie makes the registry raise, which means the daemon does not boot.

    Dedup refuses to pick between two sources at the same tier — correctly, a
    silent coin-flip between two data feeds is the failure it exists to
    prevent. But that refusal happens at start-up, so a contest introduced by
    editing this file is not a subtle bug, it is a system that will not start.
    Cheaper to find here.
    """
    claimed: dict[tuple[str, int], str] = {}
    for config in load_servers():
        if not config.enabled:
            continue
        for name, tool in config.tools.items():
            capability = tool.capability or f"{config.capability_prefix}.{name}"
            tier = tool.tier if tool.tier is not None else config.tier
            key = (capability, tier)
            assert key not in claimed, (
                f"{capability!r} at tier {tier} is claimed by both "
                f"{claimed[key]!r} and {config.id!r} — the registry raises on "
                f"a tie, so this would stop the gateway booting. Give one a "
                f"different tier, or a capability naming what it actually does."
            )
            claimed[key] = config.id


def test_a_server_that_registers_nothing_is_reported() -> None:
    """The symptom of the failure that otherwise looks like success."""
    from genesis.mcp.build import GatewayBuild
    from genesis.mcp.gateway import Gateway
    from genesis.mcp.registry import ToolRegistry
    from genesis.mcp.runtime import GatewayRuntime

    gateway = Gateway(ToolRegistry(), GatewayRuntime())
    build = GatewayBuild(gateway=gateway, connected=("ghost",))
    assert build.empty == ("ghost",)
    assert "registered nothing" in build.summary()


# ----------------------------------------------------------------------
# The market-data bench
# ----------------------------------------------------------------------

#: Capability namespaces no allow-list in ALLOW_LISTS may grant. A vendor
#: parked here can be enabled by accident without any agent gaining anything.
VENDOR_PREFIX = "vendor-"


def _bench() -> list:
    """Every disabled server whose capabilities are vendor-scoped."""
    return [
        c
        for c in load_servers()
        if (c.capability_prefix or "").startswith(VENDOR_PREFIX)
        or any(
            (t.capability or "").startswith(VENDOR_PREFIX)
            for t in c.tools.values()
        )
    ]


def test_the_vendor_bench_is_not_empty() -> None:
    """If this ever empties, the rule below is passing vacuously.

    The bench shrank on 2026-09-03 from eight servers to three, and that is
    the shape of the change rather than a weakening: free sources were wired
    in properly, and what remains parked is what is paid (financial-datasets,
    alpha-vantage) or does not install (market-data). A vendor kept for a
    written route rather than a pending decision.
    """
    assert len(_bench()) >= 2


def test_nothing_on_the_vendor_bench_is_enabled() -> None:
    """A vendor-scoped capability is a decision not yet made.

    Enabling one would answer Market Data Plane's ownership question by
    accident, which is the way that question must never be answered.
    """
    for config in _bench():
        assert not config.enabled, (
            f"{config.id} is enabled while still registering under "
            f"`{VENDOR_PREFIX}*` — either the market-data decision was made "
            f"and its capabilities should be renamed, or it should be off"
        )


def test_no_allow_list_can_reach_the_vendor_bench() -> None:
    """The second half of the rule, and the half that actually protects.

    `enabled: false` is one flag away from wrong. This is the property that
    holds even after somebody flips it: no grant in the table matches, so a
    vendor turned on by mistake registers tools that nothing can call.
    """
    from genesis.mcp.allowlist import matches

    for config in _bench():
        capabilities = [
            t.capability or f"{config.capability_prefix}.{name}"
            for name, t in config.tools.items()
        ] or [f"{config.capability_prefix}.anything"]
        for agent, patterns in ALLOW_LISTS.items():
            for pattern in patterns:
                for capability in capabilities:
                    assert not matches(pattern, capability), (
                        f"{agent}'s grant {pattern!r} reaches {capability!r} "
                        f"on the deferred vendor bench"
                    )


def test_maverick_never_offers_a_tool_that_sizes_a_position() -> None:
    """Safety Invariants §3, on the server most able to violate it.

    maverick-mcp ships regime-adjusted sizing, ATR stop computation and a
    pre-trade risk check. None of those names contains a verb the discovery
    tripwire catches — "sizing" and "risk" are not "order" or "delete" — so
    the explicit tool block is the only thing standing between them and the
    catalogue. This asserts it is still standing.
    """
    config = next(c for c in load_servers() if c.id == "maverick")
    assert config.explicit_only, "maverick must name every tool it registers"

    forbidden = ("sizing", "risk", "journal", "backtest", "add_position",
                 "remove_position", "clear_portfolio")
    for name in config.tools:
        assert not any(word in name.lower() for word in forbidden), (
            f"maverick.{name} is sizing, risk arithmetic, a second trade "
            f"ledger, or a second backtester — see Safety Invariants §3"
        )


def test_alpaca_never_loads_the_trading_toolset() -> None:
    """Lock #1: the order tools are never exposed on the wire at all.

    Stronger than refusing to catalogue them, because nothing downstream has
    to be careful about a tool that does not exist in the session.
    """
    config = next(c for c in load_servers() if c.id == "alpaca")
    toolsets = config.env.get("ALPACA_TOOLSETS", "")
    assert toolsets, "alpaca must pin its toolsets, not inherit the default"
    assert "trading" not in toolsets.split(",")
    assert "ALPACA_TOOLSETS" not in config.env_keys, (
        "a safety decision must not be readable from a shell profile"
    )


def test_a_config_value_can_never_shadow_a_credential() -> None:
    """`env:` is committed to git; `env_keys:` is a secret. Not both."""
    import pytest as _pytest

    from genesis.mcp.servers import ServerConfig

    with _pytest.raises(ValueError, match="cannot be both"):
        ServerConfig(
            id="x",
            command="y",
            read_only=True,
            capability_prefix="x",
            env={"SECRET": "not-really"},
            env_keys=("SECRET",),
        )
