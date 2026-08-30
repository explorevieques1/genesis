# Spec: Genesis Markdown/40-Memory/Recall Pathways.md
"""Eval suite: Recall Pathways — does the right prior context come back?

**Placeholder. Nothing is evaluated here yet — the suite arrives in Phase 4.**

Recall is graded, not binary. The questions are whether what came back was
worth the tokens it cost, and whether stale context was correctly superseded by
newer information.

This skips rather than being absent so that ``pytest evals`` reports the gap out
loud. A suite that is silently missing looks identical to a suite that passes,
and a green bar is not evidence.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Phase 4")
def test_memory_recall() -> None:
    """Grade what recall returns, not merely that it returned something."""
    raise AssertionError("not implemented")
