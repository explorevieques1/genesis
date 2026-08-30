# Spec: Genesis Markdown/40-Memory/Trade Ledger.md
"""Fill builders shared by the crash test and its child process."""

from __future__ import annotations

from decimal import Decimal

from genesis.memory.ledger import Fill

__all__ = ["make_batch", "make_fill"]


def make_fill(i: int, *, account_id: str = "primary") -> Fill:
    return Fill(
        account_id=account_id,
        client_order_id=f"gen_{i:04d}",
        broker_fill_id=f"bf_{i:04d}",
        approval_id=f"appr_{i:04d}",
        symbol="NVDA",
        side="buy",
        qty=10,
        price=Decimal("121.06"),
        fee=Decimal("0.60"),
        trace_id="tr_crash",
        ts=f"2026-08-29T14:31:{i:02d}.000Z",
    )


def make_batch(n: int, *, account_id: str = "primary") -> list[Fill]:
    return [make_fill(i, account_id=account_id) for i in range(n)]
