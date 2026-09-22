# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md §Live session
"""The data-connection writes: the env file keeps its other lines and stays
0600, contracts are canonicalised, bare roots are refused, and a write without
a JSON content-type is refused before it touches anything."""

from __future__ import annotations

import stat

import pytest

from genesis.errors import DegradedError
from genesis.server import broker_routes


def test_env_write_keeps_other_lines_and_locks_the_file(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("# keys\nANTHROPIC_API_KEY=abc\nIB_USERID=old\n")
    monkeypatch.setattr(broker_routes, "ENV_FILE", env)

    broker_routes.write_env({"IB_USERID": "paperuser", "IB_PASSWORD": "p#ss $word"})

    assert env.read_text().splitlines() == [
        "# keys", "ANTHROPIC_API_KEY=abc", "IB_USERID='paperuser'", "IB_PASSWORD='p#ss $word'",
    ]
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert broker_routes.read_env()["IB_PASSWORD"] == "p#ss $word"
    with pytest.raises(ValueError):
        broker_routes.write_env({"IB_PASSWORD": "it's"})


def test_contracts_are_canonical_and_bare_roots_refused() -> None:
    rows = broker_routes.canonical_series([{"symbol": "nqz6", "timeframe": "1m"}] * 2)
    assert rows == [{"symbol_id": "FUT:CME:NQ:2026-12", "timeframe": "1m"}]
    with pytest.raises(DegradedError, match="futures family"):
        broker_routes.canonical_series([{"symbol": "NQ", "timeframe": "1m"}])


def test_a_write_without_json_content_type_is_refused(tmp_path, monkeypatch) -> None:
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    env = tmp_path / ".env"
    monkeypatch.setattr(broker_routes, "ENV_FILE", env)
    client = TestClient(Starlette(routes=broker_routes.broker_routes()))

    r = client.post("/v1/broker/login", content='{"userid":"x","password":"y"}', headers={"content-type": "text/plain"})
    assert r.status_code == 415
    assert not env.exists()
