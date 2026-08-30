# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""Eval suite: MCP Gateway — with 100+ tools registered, is the right handful chosen?

**Placeholder. Nothing is evaluated here yet — the suite arrives in Phase 3.**

The gateway exists to stop context rot: a router that hands an agent every tool
it could possibly need is the failure the design was built to prevent. What
matters is precision at small k, and that registering another server does not
degrade selection for unrelated tasks.

This skips rather than being absent so that ``pytest evals`` reports the gap out
loud. A suite that is silently missing looks identical to a suite that passes,
and a green bar is not evidence.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Phase 3")
def test_tool_selection() -> None:
    """Score the gateway's tool router at small k."""
    raise AssertionError("not implemented")
