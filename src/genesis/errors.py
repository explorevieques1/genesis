# Spec: Genesis Markdown/10-Architecture/Error Handling And Degradation.md
"""Typed failures.

Three classes, and the response to each is fixed by the note:

``transient``
    Will probably work on retry -- network blip, session loss, rate limit.
    Retry with backoff, cap attempts, then escalate to ``degraded``.
``degraded``
    Can proceed with less -- stale quotes, one feed down. Proceed, **label the
    output**, keep going.
``fatal``
    Cannot proceed safely. Stop that path, escalate, speak immediately.

The classes are types rather than a string field because the retry machinery in
the Task Bus branches on them, and a typo in a string would silently turn a
fatal into an unrecognised-and-therefore-retried failure.

Never confabulate: an agent that could not get data raises one of these. It does
not guess a price.
"""

from __future__ import annotations

from typing import Literal

__all__ = [
    "DegradedError",
    "FailureClass",
    "FatalError",
    "GenesisError",
    "TransientError",
]

FailureClass = Literal["transient", "degraded", "fatal"]


class GenesisError(Exception):
    """Base for every typed failure. Never raised directly."""

    failure_class: FailureClass
    retryable: bool

    def __init__(self, reason: str, *, spoken_summary: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.spoken_summary = spoken_summary


class TransientError(GenesisError):
    """Retry with backoff. After max attempts this escalates to degraded."""

    failure_class: FailureClass = "transient"
    retryable = True


class DegradedError(GenesisError):
    """Proceed with less, and label whatever is produced from it."""

    failure_class: FailureClass = "degraded"
    retryable = False


class FatalError(GenesisError):
    """Stop. Escalate. Do not retry.

    Retrying a fatal is how a bad config or a corrupt ledger becomes a loop
    instead of an alert.
    """

    failure_class: FailureClass = "fatal"
    retryable = False
