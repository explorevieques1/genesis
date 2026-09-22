# Spec: Genesis Markdown/30-MCP/MCP Server Catalog.md
"""Loading the server catalogue, and the claims it forces an operator to make."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from genesis.config import ConfigError
from genesis.mcp.servers import ServerConfig, load_servers


def test_the_shipped_catalogue_loads() -> None:
    servers = {c.id for c in load_servers()}
    assert {"time", "filesystem", "obsidian", "alpaca", "market-data"} <= servers


def test_the_broker_and_market_data_ship_disabled() -> None:
    """Market Data Sources decides feeds by tier, and that is a separate call.

    Alpaca is described in full so that turning it on is one flag rather than
    fresh research — and so the name-level allow-list that keeps place_order
    out of the catalogue is already written down when somebody does.
    """
    off = {c.id for c in load_servers() if not c.enabled}
    assert {"alpaca", "market-data"} <= off


def test_no_enabled_server_can_reach_the_broker() -> None:
    """The enabled surface is vault, web, time, git and analysis. Nothing else."""
    for config in load_servers():
        if not config.enabled:
            continue
        for name, tool in config.tools.items():
            capability = tool.capability or name
            assert not capability.startswith(("order.", "broker.", "position.")), (
                f"{config.id}.{name} is enabled and execution-class"
            )


def test_a_writing_server_must_name_its_tools() -> None:
    with pytest.raises(ValidationError, match="must name the tools"):
        ServerConfig(id="dangerous", command="x", read_only=False)


def test_a_read_only_server_need_not() -> None:
    assert ServerConfig(id="clock", command="x", read_only=True).tools == {}


def test_stdio_needs_a_command_and_http_needs_a_url() -> None:
    with pytest.raises(ValidationError, match="requires a command"):
        ServerConfig(id="a", transport="stdio", read_only=True)
    with pytest.raises(ValidationError, match="requires a url"):
        ServerConfig(id="b", transport="http", read_only=True)


def test_a_missing_secret_is_named_rather_than_blanked(monkeypatch) -> None:
    """An empty key would start the server and fail later, less usefully."""
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    config = next(c for c in load_servers() if c.id == "alpaca")
    with pytest.raises(ConfigError, match="ALPACA_API_KEY"):
        config.child_env()


def test_the_operator_file_replaces_an_entry_wholesale(tmp_path, monkeypatch) -> None:
    """Deep-merging an allow-list is how you keep tools you thought you removed."""
    override = tmp_path / "mcp_servers.yaml"
    override.write_text(
        "servers:\n"
        "  - id: alpaca\n"
        "    command: uvx\n"
        "    read_only: false\n"
        "    tools:\n"
        "      get_stock_bars: { capability: market-data.ohlcv, mutating: false }\n"
    )
    alpaca = next(c for c in load_servers(override) if c.id == "alpaca")
    assert set(alpaca.tools) == {"get_stock_bars"}
    assert alpaca.env_keys == ()  # not inherited from the shipped entry


def test_a_bad_file_names_the_server(tmp_path) -> None:
    bad = tmp_path / "mcp_servers.yaml"
    bad.write_text("servers:\n  - id: broken\n    transport: carrier-pigeon\n")
    with pytest.raises(ConfigError, match="broken"):
        load_servers(bad)


def test_a_header_points_at_a_secret_rather_than_holding_one(monkeypatch) -> None:
    """Hosted MCP servers authenticate by header. The key still lives in env."""
    monkeypatch.setenv("EXA_API_KEY", "sk-not-a-real-key")
    config = ServerConfig(
        id="exa",
        transport="http",
        url="https://mcp.exa.ai/mcp",
        read_only=True,
        headers={"x-api-key": "${EXA_API_KEY}"},
    )
    assert config.resolved_headers() == {"x-api-key": "sk-not-a-real-key"}
    # The config file itself holds only the name.
    assert "sk-not-a-real-key" not in str(config.headers)


def test_a_missing_header_secret_raises_rather_than_sending_an_empty_one(monkeypatch) -> None:
    """A 401 reads like a server problem. The true error is better."""
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    config = ServerConfig(
        id="exa", transport="http", url="https://x", read_only=True,
        headers={"x-api-key": "${EXA_API_KEY}"},
    )
    with pytest.raises(ConfigError, match="EXA_API_KEY"):
        config.resolved_headers()


def test_a_literal_header_is_passed_through(monkeypatch) -> None:
    config = ServerConfig(
        id="x", transport="http", url="https://x", read_only=True,
        headers={"user-agent": "genesis/1"},
    )
    assert config.resolved_headers() == {"user-agent": "genesis/1"}


def test_the_web_search_key_is_declared_as_a_secret() -> None:
    """A name absent from SECRET_ENV_VARS is never read from the .env file."""
    from genesis.config import SECRET_ENV_VARS

    assert "EXA_API_KEY" in SECRET_ENV_VARS
