# Spec: Genesis Markdown/10-Architecture/Observability.md
"""Does this server admit it when the fleet behind it is gone?

Written after a two-day outage that nothing reported. A capability summary was
28 characters over its limit, the registry refused it, `_warm_fleet`'s
`except Exception` logged one line into a five-megabyte log, and the server
kept answering `/v1/health` with a constant `{"ok": true, "idle": true}`. For
two days `./genesis status` said `healthy` while no cron fired, no workflow ran
and no agent was registered.

Biological Design calls that drift between believed and actual state and names
it the failure that loses money quietly. Two tests, for the two halves of it:
the health route must be able to say the fleet is down, and the thing that took
the fleet down must be caught here rather than at boot.
"""

from __future__ import annotations

import pytest
from starlette import testclient

from genesis.orchestrator.registry import MAX_SUMMARY_CHARS
from genesis.server.app import EventBus, build_app
from genesis.server.fleet import FLEET_STATE


@pytest.fixture()
def client():
    with testclient.TestClient(build_app(EventBus())) as c:
        yield c


def test_health_reports_the_fleet_not_just_the_port(client) -> None:
    """`ok` answers "is something listening". It is not the interesting half."""
    before = (FLEET_STATE.state, FLEET_STATE.detail, FLEET_STATE.agents)
    try:
        FLEET_STATE.set("failed", detail="summary for 'session-plan' is 188 chars")
        body = client.get("/v1/health").json()
        assert body["ok"] is True, "the HTTP server is up; ./genesis up waits on this"
        assert body["fleet"]["ok"] is False
        assert body["fleet"]["state"] == "failed"
        assert "188 chars" in body["fleet"]["detail"], "the reason must survive to the operator"

        FLEET_STATE.set("up", agents=16)
        assert client.get("/v1/health").json()["fleet"] == {
            "state": "up", "detail": "", "agents": 16, "ok": True,
        }

        # A deliberate --no-daemon is a choice, not a fault, and must not read
        # as one or the signal stops meaning anything.
        FLEET_STATE.set("disabled", detail="started with --no-daemon")
        assert client.get("/v1/health").json()["fleet"]["ok"] is True
    finally:
        FLEET_STATE.set(before[0], detail=before[1], agents=before[2])


def test_no_capability_summary_can_take_the_fleet_down() -> None:
    """The exact bug, caught here instead of at boot.

    One agent's catalogue line being too long refused the whole registry, and
    the registry is built before anything is registered — so a prose edit in
    one family silently disabled all thirty agents. It is a sentence: it should
    fail in a test, not at three in the morning in a log nobody is reading.
    """
    from genesis.agents.charting import fleet as charting
    from genesis.agents.journal import fleet as journal
    from genesis.agents.research import fleet as research

    too_long = [
        (c.agent, len(c.summary))
        for module in (charting, journal, research)
        for c in module.CAPABILITIES
        if len(c.summary) > MAX_SUMMARY_CHARS
    ]
    assert too_long == [], (
        f"over the {MAX_SUMMARY_CHARS}-char limit: {too_long}. "
        f"The registry refuses these, and refusing one refuses the fleet."
    )
