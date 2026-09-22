# Spec: Genesis Markdown/30-MCP/genesis-execution-mcp.md §Approval token
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from genesis.execution.approval import ApprovalBook, ApprovalError
from genesis.execution.risk import evaluate

from tests.execution.test_risk import NOW, ctx, proposal


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def issued(book: ApprovalBook, **ctx_kw):
    p = proposal()
    d = evaluate(p, ctx(**ctx_kw), now=NOW)
    return p, book.issue(p, d, "confirm")


def test_redeem_once_with_named_confirmation():
    book = ApprovalBook(60, clock=Clock())
    p, a = issued(book)
    with pytest.raises(ApprovalError, match="must name NQZ6"):
        book.redeem(a.approval_id, a.signature, p.binds(1), {"symbol": "yes"})
    book.redeem(a.approval_id, a.signature, p.binds(1), {"symbol": "nqz6", "qty": 1})
    with pytest.raises(ApprovalError, match="already used"):
        book.redeem(a.approval_id, a.signature, p.binds(1), {"symbol": "NQZ6", "qty": 1})


def test_expired_forged_or_mutated_is_refused():
    clock = Clock()
    book = ApprovalBook(60, clock=clock)
    p, a = issued(book, mode="auto-within-limits")
    with pytest.raises(ApprovalError, match="signature"):
        book.redeem(a.approval_id, "0" * 64, p.binds(1))
    with pytest.raises(ApprovalError, match="changed"):
        book.redeem(a.approval_id, a.signature, p.binds(2))
    clock.now = NOW + timedelta(seconds=61)
    with pytest.raises(ApprovalError, match="expired"):
        book.redeem(a.approval_id, a.signature, p.binds(1))


def test_no_approval_for_a_rejection():
    book = ApprovalBook(60)
    p = proposal()
    d = evaluate(p, ctx(halted=True), now=datetime.now(UTC))
    with pytest.raises(ApprovalError):
        book.issue(p, d, "confirm")
