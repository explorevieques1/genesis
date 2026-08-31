# Spec: Genesis Markdown/40-Memory/Working Memory.md
"""Working memory's acceptance criteria, including the two safety ones."""

from __future__ import annotations

import time

from genesis.memory.working import PendingConfirmation, WorkingMemory


def test_turns_roll_off_by_count_into_the_sink():
    rolled = []
    wm = WorkingMemory(max_turns=3, on_rolloff=rolled.extend)
    for i in range(5):
        wm.add_turn("user", f"turn {i}")
    assert [t.text for t in wm.turns()] == ["turn 2", "turn 3", "turn 4"]
    assert [t.text for t in rolled] == ["turn 0", "turn 1"]


def test_turns_roll_off_by_tokens_under_a_burst():
    """A burst of long results must not blow the cap even within the turn limit."""
    wm = WorkingMemory(max_turns=100, max_tokens=50)
    for _ in range(20):
        wm.add_turn("genesis", "x" * 200)
    assert wm.token_estimate() <= 50


def test_ambient_is_never_in_the_snapshot():
    """Conversation you did not address to the system does not reach disk."""
    wm = WorkingMemory()
    wm.ambient.add("private conversation about a divorce")
    snapshot = wm.snapshot()
    assert "divorce" not in repr(snapshot)
    assert "ambient" not in snapshot


def test_ambient_rolls_off_by_time():
    wm = WorkingMemory(ambient_window_sec=0.05)
    wm.ambient.add("older speech")
    time.sleep(0.08)
    assert wm.ambient.context() == ""


def test_confirmations_are_single_use():
    """Voice UX: 'Never asks twice for the same proposal.' A claimable-twice
    confirmation is a double order waiting for a stutter."""
    wm = WorkingMemory()
    wm.add_confirmation(PendingConfirmation("p1", "NVDA", "confirm?", time.monotonic() + 60))
    assert wm.take_confirmation("p1") is not None
    assert wm.take_confirmation("p1") is None


def test_expired_confirmations_are_not_returned():
    wm = WorkingMemory()
    wm.add_confirmation(PendingConfirmation("p1", "NVDA", "confirm?", time.monotonic() - 1))
    assert wm.take_confirmation("p1") is None
    assert wm.pending_confirmations() == []


def test_restart_expires_every_pending_confirmation():
    """The note calls this a safety property: a restart must never resurrect a
    stale confirmation, because the price has moved and you are not there."""
    wm = WorkingMemory()
    wm.add_confirmation(PendingConfirmation("p1", "NVDA", "confirm?", time.monotonic() + 3600))
    wm.restore(summary="earlier: discussed semis")
    assert wm.pending_confirmations() == []
    assert [t.text for t in wm.turns()] == ["earlier: discussed semis"]
