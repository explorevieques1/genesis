# Spec: Genesis Markdown/30-MCP/MCP Server Catalog.md
"""What we take from a server, and what we refuse.

The Alpaca test is the one that matters: MCP Server Catalog.md warns that
``alpaca-mcp-server`` ships order placement in the same server as market data,
and that registering it by server would put ``place_order`` in the catalogue
three phases before the Pre-Trade Risk Engine exists.
"""

from __future__ import annotations

from genesis.mcp.discovery import DiscoveredTool, normalize
from genesis.mcp.registry import ToolRegistry
from genesis.mcp.servers import ServerConfig, load_servers
from genesis.mcp.spec import Trust

ALPACA_SURFACE = [
    DiscoveredTool("get_stock_bars", read_only_hint=True),
    DiscoveredTool("get_stock_quote", read_only_hint=True),
    DiscoveredTool("get_account", read_only_hint=True),
    # Everything below this line must never reach the catalogue.
    DiscoveredTool("place_order"),
    DiscoveredTool("close_position"),
    DiscoveredTool("cancel_all_orders"),
    DiscoveredTool("liquidate_position"),
]


def alpaca_config() -> ServerConfig:
    return next(c for c in load_servers() if c.id == "alpaca")


def test_only_the_read_half_of_alpaca_registers() -> None:
    registry = ToolRegistry()
    registry.register_all(normalize(alpaca_config(), ALPACA_SURFACE))

    assert registry.surface()  # something registered, so this is a real check
    for spec in registry:
        assert not spec.mutating, f"{spec.id} is mutating and must not be catalogued"
    for forbidden in ("place_order", "close_position", "cancel_all_orders"):
        assert f"alpaca.{forbidden}" not in registry


def test_no_mutating_tool_survives_the_whole_shipped_catalogue() -> None:
    """The surface test: enumerate everything, fail if anything can write.

    Phrased over the shipped config rather than one server, so adding a server
    to ``default_servers.yaml`` without thinking about its write half fails
    here rather than in Phase 7.
    """
    registry = ToolRegistry()
    for config in load_servers():
        # Pretend every server offers a dangerous tool alongside its real ones.
        offered = [DiscoveredTool(n) for n in config.tools] + [
            DiscoveredTool("place_order"),
            DiscoveredTool("delete_everything"),
        ]
        registry.register_all(normalize(config, offered))

    assert all(spec.read_only for spec in registry)
    assert not any(".place_order" in line for line in registry.surface())


def test_an_unnamed_tool_from_a_writing_server_is_silently_refused() -> None:
    """Silence is a refusal, not a default-open."""
    config = alpaca_config()
    specs = normalize(config, [DiscoveredTool("some_new_tool_alpaca_added")])
    assert specs == []


def test_a_read_only_server_registers_everything_it_offers() -> None:
    """The reward for claiming read_only is not having to name forty tools."""
    config = next(c for c in load_servers() if c.id == "market-data")
    specs = normalize(config, [DiscoveredTool("volume_profile"), DiscoveredTool("orb")])
    assert {s.name for s in specs} == {"volume_profile", "orb"}
    assert all(s.read_only for s in specs)
    assert all(s.trust is Trust.UNTRUSTED for s in specs)


def test_an_undescribed_tool_defaults_to_the_unsafe_to_forget_direction() -> None:
    config = ServerConfig(id="vague", command="x", read_only=True)
    spec = normalize(config, [DiscoveredTool("mystery")])[0]
    assert spec.capability == "mystery"  # collides loudly with any other 'mystery'
    assert spec.cache.cacheable is False
    assert spec.tier == 9  # loses every capability contest


def test_a_servers_own_read_only_hint_does_not_outrank_ours() -> None:
    """A server does not get to declare itself harmless."""
    config = ServerConfig(
        id="sneaky",
        command="x",
        read_only=False,
        tools={"wire_money": {"capability": "bank.wire", "mutating": True}},
    )
    spec = normalize(config, [DiscoveredTool("wire_money", read_only_hint=True)])[0]
    assert spec.mutating is True


def test_an_absent_hint_reads_as_mutating() -> None:
    config = ServerConfig(id="quiet", command="x", read_only=False, tools={"go": {}})
    spec = normalize(config, [DiscoveredTool("go", read_only_hint=None)])[0]
    assert spec.mutating is True


def test_a_read_only_claim_does_not_cover_a_dangerous_verb() -> None:
    """The tripwire. A server's claim is about the server as it was written.

    Servers gain tools. If one that we bulk-registered as read-only ships a
    ``place_order``, the claim is now wrong, and believing it is how a write
    tool reaches the catalogue without anyone deciding to put it there.
    """
    config = ServerConfig(id="helpful", command="x", read_only=True)
    specs = normalize(
        config,
        [
            DiscoveredTool("get_quote"),
            DiscoveredTool("place_order"),
            DiscoveredTool("liquidate_position"),
            DiscoveredTool("cancel_all"),
        ],
    )
    assert {s.name for s in specs} == {"get_quote"}


def test_the_tripwire_does_not_fire_on_an_innocent_name() -> None:
    """A tripwire that cries wolf is one somebody switches off."""
    config = ServerConfig(id="helpful", command="x", read_only=True)
    specs = normalize(
        config,
        [DiscoveredTool("get_borderline"), DiscoveredTool("reorder_columns")],
    )
    assert {s.name for s in specs} == {"get_borderline", "reorder_columns"}


def test_the_tripwire_yields_to_a_deliberate_declaration() -> None:
    """Phase 7 must be able to catalogue propose_order on purpose."""
    config = ServerConfig(
        id="genesis-execution",
        command="x",
        read_only=False,
        tools={"propose_order": {"capability": "order.propose", "mutating": True}},
    )
    specs = normalize(config, [DiscoveredTool("propose_order")])
    assert specs and specs[0].mutating is True


def test_a_slow_tool_gets_its_own_timeout() -> None:
    """One server can host a quote lookup and a five-minute research agent.

    A single per-server number would be either a hair trigger on the first or
    no protection at all on the second.
    """
    config = ServerConfig(
        id="exa", transport="http", url="https://x", read_only=True,
        call_timeout_sec=30,
        tools={
            "web_search_exa": {"capability": "web.search"},
            "agent_run": {"capability": "research.agent", "timeout_sec": 300},
        },
    )
    specs = {s.name: s for s in normalize(config, [
        DiscoveredTool("web_search_exa"), DiscoveredTool("agent_run"),
    ])}
    assert specs["web_search_exa"].timeout_sec == 30
    assert specs["agent_run"].timeout_sec == 300


# ----------------------------------------------------------------------
# capability_prefix — how a bulk-registered server becomes grantable
# ----------------------------------------------------------------------


def test_a_prefix_gives_bulk_registered_tools_a_grantable_namespace() -> None:
    """A bare tool name is a legal capability and a useless one.

    Allow-list entries are exact or ``prefix.*``, so `get_company_facts` could
    only ever be granted by naming it, one tool at a time, forever. This is
    what lets a server we never hand-curate still land somewhere an allow-list
    can reach.
    """
    config = ServerConfig(
        id="sec-edgar",
        command="uvx",
        read_only=True,
        capability_prefix="filings",
    )
    specs = normalize(config, [DiscoveredTool("get_company_facts")])
    assert [s.capability for s in specs] == ["filings.get_company_facts"]

    from genesis.mcp.allowlist import AllowList

    assert AllowList.of("x", ("filings.*",)).permits(specs[0].capability)


def test_a_named_capability_still_wins_over_the_prefix() -> None:
    config = ServerConfig(
        id="sec-edgar",
        command="uvx",
        read_only=True,
        capability_prefix="filings",
        tools={"get_company_facts": {"capability": "filings.facts"}},
    )
    specs = normalize(config, [DiscoveredTool("get_company_facts")])
    assert specs[0].capability == "filings.facts"


def test_two_servers_agreeing_on_a_tool_name_do_not_collide_under_prefixes() -> None:
    """Both sec-edgar and openbb offer something called `get_company_facts`.

    Undecorated they claim one capability and the registry refuses to boot —
    correct, but a strange way to learn that two unrelated servers happened to
    agree on a word.
    """
    edgar = normalize(
        ServerConfig(id="sec-edgar", command="x", read_only=True, capability_prefix="filings"),
        [DiscoveredTool("get_company_facts")],
    )
    openbb = normalize(
        ServerConfig(id="openbb", command="x", read_only=True, capability_prefix="fundamentals"),
        [DiscoveredTool("get_company_facts")],
    )
    registry = ToolRegistry()
    assert registry.register_all(edgar + openbb) == 2


def test_the_mutating_verb_tripwire_still_fires_under_a_prefix() -> None:
    """A namespace is not a permission. The reflex is unaffected by it."""
    config = ServerConfig(
        id="sec-edgar", command="x", read_only=True, capability_prefix="filings"
    )
    specs = normalize(config, [DiscoveredTool("delete_everything")])
    assert specs == []
