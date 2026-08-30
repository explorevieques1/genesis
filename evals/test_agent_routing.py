# Spec: Genesis Markdown/10-Architecture/Task Bus.md
"""Eval suite: Task Bus — does work reach the agent that should do it?

**Placeholder. Nothing is evaluated here yet — the suite arrives in Phase 4.**

Misrouting is quiet. A task handled by the wrong agent usually produces a
plausible answer rather than an error, which is why this needs an eval and not
a unit test.

This skips rather than being absent so that ``pytest evals`` reports the gap out
loud. A suite that is silently missing looks identical to a suite that passes,
and a green bar is not evidence.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Phase 4")
def test_agent_routing() -> None:
    """Check that a dispatched task lands on the right specialist."""
    raise AssertionError("not implemented")
