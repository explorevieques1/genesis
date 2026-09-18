# Spec: Genesis Markdown/10-Architecture/Agent Contract.md
"""Shared fixtures. Building blocks live in ``tests/helpers.py``."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from genesis.errors import FatalError, TransientError
from helpers import EchoAgent

ET = ZoneInfo("America/New_York")


@pytest.fixture
def echo() -> EchoAgent:
    return EchoAgent()


@pytest.fixture
def transient() -> TransientError:
    return TransientError("feed blip")


@pytest.fixture
def fatal() -> FatalError:
    return FatalError("bad config")


@pytest.fixture
def market_open() -> dt.datetime:
    """A Monday, 10:00 ET — regular session."""
    return dt.datetime(2026, 8, 31, 10, 0, tzinfo=ET)


@pytest.fixture
def market_closed() -> dt.datetime:
    """A Monday, 22:00 ET — closed."""
    return dt.datetime(2026, 8, 31, 22, 0, tzinfo=ET)


@pytest.fixture(autouse=True)
def _no_live_order_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may open a broker connection or spawn a kill switch.

    `build_app`'s lifespan reads the real ~/.genesis/config.yaml; with
    `execution.enabled` on, a server test would otherwise connect to the paper
    account. Tests of the order path build their own manager on a fake broker.

    The market-data live session is the same hazard from the other side: with
    the IBKR adapter enabled it dials the gateway on start and emits
    ``broker.connection`` when that fails, so every server test that counts
    events counted the developer's gateway state rather than its own.
    """
    from genesis.execution import order_manager
    from genesis.marketdata import ibkr_live
    import genesis.server.app as app

    monkeypatch.setattr(order_manager, "start", lambda config, emit, **kw: None)
    monkeypatch.setattr(ibkr_live, "start", lambda *a, **kw: None)
    monkeypatch.setattr(app, "_spawn_killswitch", lambda port, state_dir: None, raising=False)
