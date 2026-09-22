# Spec: Genesis Markdown/60-UI/Automation.md
"""The HTTP door: save appends, Genesis drafts stay off, only the operator enables."""

from __future__ import annotations

from pathlib import Path

import pytest

import genesis.automation as automation
from genesis.automation.store import WorkflowStore
from genesis.server.app import EventBus, build_app

TestClient = pytest.importorskip("starlette.testclient").TestClient

WORKFLOW = {
    "id": "refresh-map", "name": "Nightly vault map",
    "trigger": {"type": "cron", "at": "23:30"},
    "start": "map",
    "steps": [{"id": "map", "kind": "refresh", "target": "vault-map"}],
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(automation, "open_store", lambda config=None: WorkflowStore(tmp_path / "wf.db"))
    monkeypatch.setattr(automation, "_ATTACHED", {})
    with TestClient(build_app(EventBus())) as c:
        yield c


def test_save_then_read_back(client) -> None:
    saved = client.post("/v1/automation/workflows/save", json={"workflow": WORKFLOW}).json()
    assert saved["ok"] and saved["workflow"]["version"] == 1
    assert saved["scheduled"] is False, "no daemon in this process — and it says so"
    listed = client.get("/v1/automation/workflows").json()["workflows"]
    assert [w["workflow_id"] for w in listed] == ["refresh-map"]


def test_an_invalid_workflow_is_refused_with_reasons(client) -> None:
    bad = {**WORKFLOW, "steps": [{"id": "map", "kind": "gather",
                                  "capability": "genesis-execution.propose_order"}]}
    reply = client.post("/v1/automation/workflows/save", json={"workflow": bad})
    assert reply.status_code == 400
    assert "grant" in str(reply.json()["errors"])


def test_a_genesis_draft_is_saved_disabled_and_cannot_enable_itself(client) -> None:
    body = {"workflow": WORKFLOW, "author": "orchestrator"}
    saved = client.post("/v1/automation/workflows/save", json=body).json()
    assert saved["workflow"]["enabled"] is False

    refused = client.post("/v1/automation/workflows/refresh-map/enable",
                          json={"enabled": True, "author": "orchestrator"})
    assert refused.status_code == 400 and "operator" in refused.json()["reason"]

    enabled = client.post("/v1/automation/workflows/refresh-map/enable",
                          json={"enabled": True}).json()
    assert enabled["workflow"]["enabled"] is True
    versions = client.get("/v1/automation/workflows/refresh-map/versions").json()["versions"]
    assert [(v["version"], v["author"]) for v in versions] == [(2, "operator"), (1, "orchestrator")]


def test_the_catalog_serves_the_palette_and_processes(client) -> None:
    process = {**WORKFLOW, "id": "morning-scan", "name": "Morning scan", "trigger": {"type": "on-demand"}}
    client.post("/v1/automation/workflows/save", json={"workflow": process})
    body = client.get("/v1/automation/catalog").json()
    ids = {n["id"] for n in body["nodes"]}
    assert {"tool.news.company", "signal.indicator", "output.alert", "process.morning-scan"} <= ids
    assert {c["id"] for c in body["categories"]} >= {"signals", "logic", "custom"}
    assert client.get("/v1/automation/alerts").json()["alerts"] == []


def test_templates_are_served_ready_to_open(client) -> None:
    body = client.get("/v1/automation/templates").json()
    names = {t["name"] for t in body["templates"]}
    assert {"Morning news synopsis", "Breakout scanner", "Market open gate"} <= names
    first = body["templates"][0]
    # A template body is saveable as-is: the same validator the canvas's save uses.
    saved = client.post("/v1/automation/workflows/save", json={"workflow": first["body"]}).json()
    assert saved["ok"] and saved["workflow"]["enabled"] is False
