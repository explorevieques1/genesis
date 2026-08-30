# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Eval suite: Voice Stack — directed vs. ambient vs. follow-up vs. stop

**Placeholder. Nothing is evaluated here yet — the suite arrives in Phase 2.**

The costly errors are asymmetric. Acting on ambient conversation is worse than
missing a directed one, and failing to hear "stop" is worst of all, so this
suite must weight the classes rather than report a flat accuracy.

This skips rather than being absent so that ``pytest evals`` reports the gap out
loud. A suite that is silently missing looks identical to a suite that passes,
and a green bar is not evidence.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Phase 2")
def test_intent_classification() -> None:
    """Classify every utterance the mic hears before anything acts on it."""
    raise AssertionError("not implemented")
