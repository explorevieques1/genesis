# Spec: Genesis Markdown/30-MCP/genesis-execution-mcp.md §Approval token · 70-Schemas/Order And Fill Schema.md
"""Approval tokens: signed, short-lived, single-use, bound to one exact order.

The key is random per process and never written anywhere. An approval lives
sixty seconds, so it has no reason to survive a restart -- and a key that is
never on disk cannot leak from it.

Redemption checks, in order: the approval exists, the signature matches, it has
not been used, it has not expired, the order about to be sent is the order it
was issued for, and -- when confirmation is required -- the confirmation names
the contract and the size. A bare "yes" does not place a trade (Approval Modes).
The approval is spent the moment redemption succeeds, even if placement then
fails: a retry re-proposes, it never reuses.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from genesis.execution.risk import Decision, Proposal
from genesis.ids import new_id

__all__ = ["Approval", "ApprovalBook", "ApprovalError"]


class ApprovalError(Exception):
    """Redemption refused. The message says which rule."""


@dataclass(frozen=True)
class Approval:
    approval_id: str
    proposal_id: str
    decision: str
    approved_qty: int
    binds_to: dict[str, Any]
    local_symbol: str
    worst_case_loss: str | None
    approval_mode: str
    requires_confirmation: bool
    expires_at: datetime
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id, "proposal_id": self.proposal_id,
            "decision": self.decision, "approved_qty": self.approved_qty,
            "binds_to": self.binds_to, "local_symbol": self.local_symbol,
            "worst_case_loss": self.worst_case_loss, "approval_mode": self.approval_mode,
            "requires_confirmation": self.requires_confirmation,
            "expires_at": self.expires_at.isoformat(), "signature": self.signature,
        }


class ApprovalBook:
    def __init__(self, ttl_sec: int = 60, *, clock: Callable[[], datetime] | None = None) -> None:
        self.ttl = timedelta(seconds=ttl_sec)
        self._key = secrets.token_bytes(32)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._issued: dict[str, Approval] = {}
        self._used: set[str] = set()
        self._lock = threading.Lock()

    def _sign(self, approval_id: str, binds: dict[str, Any], expires_at: datetime) -> str:
        msg = json.dumps({"id": approval_id, "binds": binds, "exp": expires_at.isoformat()},
                         sort_keys=True).encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def issue(self, proposal: Proposal, decision: Decision, mode: str) -> Approval:
        if not decision.approved or decision.proposal_id != proposal.id:
            raise ApprovalError("no approval for a rejected or mismatched decision")
        approval_id = new_id("appr")
        binds = proposal.binds(decision.approved_qty)
        expires = self._clock() + self.ttl
        approval = Approval(
            approval_id=approval_id, proposal_id=proposal.id, decision=decision.decision,
            approved_qty=decision.approved_qty, binds_to=binds, local_symbol=proposal.local_symbol,
            worst_case_loss=None if decision.worst_case_loss is None else str(decision.worst_case_loss),
            approval_mode=mode, requires_confirmation=decision.requires_confirmation,
            expires_at=expires, signature=self._sign(approval_id, binds, expires),
        )
        with self._lock:
            self._prune()
            self._issued[approval_id] = approval
        return approval

    def get(self, approval_id: str) -> Approval | None:
        with self._lock:
            return self._issued.get(approval_id)

    def redeem(self, approval_id: str, signature: str, binds_now: dict[str, Any],
               confirmation: dict[str, Any] | None = None) -> Approval:
        with self._lock:
            approval = self._issued.get(approval_id)
            if approval is None:
                raise ApprovalError("unknown approval — propose again")
            expected = self._sign(approval.approval_id, approval.binds_to, approval.expires_at)
            if not hmac.compare_digest(expected, str(signature)):
                raise ApprovalError("approval signature does not match")
            if approval_id in self._used:
                raise ApprovalError("approval already used — propose again")
            if self._clock() >= approval.expires_at:
                raise ApprovalError("approval expired — the price has moved, propose again")
            if binds_now != approval.binds_to:
                raise ApprovalError("the order changed after it was approved — propose again")
            if approval.requires_confirmation:
                c = confirmation or {}
                if str(c.get("symbol", "")).upper() != approval.local_symbol.upper() \
                        or str(c.get("qty", "")) != str(approval.approved_qty):
                    raise ApprovalError(
                        f"confirmation must name {approval.local_symbol} and {approval.approved_qty} contracts"
                    )
            self._used.add(approval_id)
            return approval

    def _prune(self) -> None:
        now = self._clock()
        stale = [k for k, a in self._issued.items() if a.expires_at + self.ttl < now]
        for k in stale:
            self._issued.pop(k, None)
            self._used.discard(k)
