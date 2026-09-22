# Spec: Genesis Markdown/60-UI/Terminal.md
"""Calling a tool by hand: what it may reach, and what it must refuse.

Three properties, and only three, because everything else this route does
happens inside ``Gateway.call`` and is tested there. The point of the route is
that it adds no check and skips none -- so what is worth asserting is the two
refusals it *does* own, and the fact that the operator's grant is a reading
grant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from genesis.mcp.spec import ToolSpec, Trust
from genesis.server.app import EventBus, build_app

starlette_testclient = pytest.importorskip("starlette.testclient")
TestClient = starlette_testclient.TestClient


READ = ToolSpec(
    id="sec-edgar.get_company_facts", server="sec-edgar", name="get_company_facts",
    capability="filings.facts", description="Company facts from XBRL.",
    input_schema={
        "type": "object",
        "properties": {"ticker": {"type": "string", "description": "e.g. AAPL"}},
        "required": ["ticker"],
    },
    mutating=False, trust=Trust.UNTRUSTED, tier=1,
)
WRITE = ToolSpec(
    id="telegram.send_message", server="telegram", name="send_message",
    capability="notify.send", mutating=True, trust=Trust.UNTRUSTED, tier=4,
)


class _Registry:
    def __init__(self, *specs: ToolSpec) -> None:
        self._by_id = {s.id: s for s in specs}
        self._by_cap = {s.capability: s for s in specs}

    def find(self, tool_id: str) -> ToolSpec | None:
        return self._by_id.get(tool_id)

    def for_capability(self, capability: str) -> ToolSpec | None:
        return self._by_cap.get(capability)


@dataclass
class _Result:
    content: Any = "ok"
    structured: dict[str, Any] | None = None
    latency_ms: float = 4.0
    fence: Any = None


class _Gateway:
    """Enough gateway to answer the route. Records what it was asked to run."""

    def __init__(self) -> None:
        self.registry = _Registry(READ, WRITE)
        self.calls: list[tuple[str, str, dict]] = []

    def tools_for(self, agent: str) -> tuple[str, ...]:
        return (READ.id,) if agent == "operator" else ()

    def call(self, agent: str, capability: str, arguments: dict | None = None, **_: Any):
        self.calls.append((agent, capability, arguments or {}))
        return _Result(content=[{"cik": "0000320193", "ticker": "AAPL"}])


@pytest.fixture
def gateway(monkeypatch) -> _Gateway:
    """Stand in for a live gateway without spawning seventeen subprocesses."""
    fake = _Gateway()

    @dataclass
    class _Build:
        gateway: _Gateway
        failed: dict[str, str]

        def summary(self) -> str:
            return "2 tools from 2 servers"

    monkeypatch.setattr(
        "genesis.mcp.build.build_gateway", lambda *a, **k: _Build(fake, {})
    )
    return fake


@pytest.fixture
def client(gateway):
    with TestClient(build_app(EventBus())) as c:
        yield c


def test_a_tools_arguments_come_from_the_server_not_from_config(client):
    """The whole reason this route exists. Config knows the tool is called
    `get_company_facts`; only the server knows it wants a ticker."""
    body = client.get(f"/v1/mcp/tool/{READ.id}").json()
    assert body["available"] is True
    assert body["tool"]["input_schema"]["required"] == ["ticker"]
    assert body["tool"]["callable"] is True


def test_a_mutating_tool_is_refused_and_says_why(client, gateway):
    """A command line whose muscle memory is "type, Enter" must not be able to
    send a Telegram message. The refusal is stated *and* the gateway is never
    reached -- an error after the send would be no protection at all."""
    schema = client.get(f"/v1/mcp/tool/{WRITE.id}").json()
    assert schema["tool"]["callable"] is False
    assert "writes" in schema["tool"]["refusal"]

    body = client.post("/v1/mcp/call", json={"tool": WRITE.id, "args": {}}).json()
    assert body["ok"] is False
    assert "writes" in body["reason"]
    assert gateway.calls == []


def test_a_read_call_goes_through_the_gateway_as_the_operator(client, gateway):
    """Attribution is the point: the audit line must be able to tell a person
    from a model, even though their grants are deliberately the same shape."""
    body = client.post(
        "/v1/mcp/call", json={"tool": READ.id, "args": {"ticker": "AAPL"}}
    ).json()
    assert body["ok"] is True
    assert body["content"] == [{"cik": "0000320193", "ticker": "AAPL"}]
    assert gateway.calls == [("operator", READ.id, {"ticker": "AAPL"})]


def test_an_unknown_tool_is_an_answer_not_a_crash(client):
    body = client.get("/v1/mcp/tool/nope.nothing").json()
    assert body["available"] is False
    assert "not in the live catalogue" in body["reason"]


def test_the_operator_is_granted_no_write_pattern():
    """The second, independent reason a hand-driven call cannot write. Deleting
    the refusal in `tool_routes.py` must not open the path."""
    from genesis.mcp.build import ALLOW_LISTS

    for pattern in ALLOW_LISTS["operator"]:
        assert not pattern.startswith(("vault.create", "vault.edit", "chart.")), pattern
    # Every grant is either an explicit read verb or a read-only family.
    assert "vault.*" not in ALLOW_LISTS["operator"]
    assert "research.*" not in ALLOW_LISTS["operator"]
