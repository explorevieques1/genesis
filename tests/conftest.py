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
