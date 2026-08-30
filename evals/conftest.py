# Spec: Genesis Markdown/00-Meta/Conventions.md
"""Fixtures for the Genesis eval suite.

Evals are excluded from the default `pytest` run (see `pyproject.toml`
`testpaths`). Run them deliberately:

    pytest evals
    GENESIS_EVAL_JUDGE_MODEL=<model> pytest evals -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
EVALS = ROOT / "evals"

for path in (SRC, EVALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from helpers import (  # noqa: E402
    JUDGE_MODEL,
    ToolCallCapture,
    is_judge_available,
)

# Resolved once: a reachability probe per test would dominate the runtime.
_JUDGE_AVAILABLE = is_judge_available()

requires_judge = pytest.mark.skipif(
    not _JUDGE_AVAILABLE,
    reason=(
        "no judge model reachable — set GENESIS_EVAL_JUDGE_MODEL "
        "(and GENESIS_EVAL_JUDGE_BASE_URL if not localhost:11434)"
    ),
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark everything under evals/ as `eval`, so `-m` selection works."""
    for item in items:
        item.add_marker(pytest.mark.eval)


def pytest_report_header() -> list[str]:
    judge = JUDGE_MODEL or "<unset>"
    state = "reachable" if _JUDGE_AVAILABLE else "unavailable — judge evals skip"
    return [f"genesis evals: judge={judge} ({state})"]


@pytest.fixture
def tools() -> ToolCallCapture:
    """Captures the tool calls an agent makes during an eval."""
    return ToolCallCapture()


@pytest.fixture
def config():
    """The shipped defaults, so an eval never depends on a developer's machine."""
    from genesis.config import load_config

    return load_config(None)
