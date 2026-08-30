# Spec: Genesis Markdown/40-Memory/Trade Ledger.md
"""Crash durability, proven with real SIGKILL — not assumed from pragmas.

Three separate claims, each with its own kill point:

1. **No half-row.** A killed write leaves the row absent, never partial, and
   never a fill without its balanced legs.
2. **No lost acknowledged write.** If ``record_fill`` returned, the row is there
   after restart.
3. **No duplicate on retry.** Recovery reconciles through the broker fill id to
   exactly one row -- not zero (a lost fill), not two (a blind replay).

Threat model is **process kill**, which is what SIGKILL reproduces. Power loss
and lying fsync are deliberately out of scope; ``synchronous=FULL`` is what we
pay for the first and no software setting fixes the second.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from genesis.memory.ledger import TradeLedger

WRITER = Path(__file__).parent / "ledger_writer.py"

pytestmark = pytest.mark.crash


def run_writer(db: Path, kill_point: str, count: int = 1) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(WRITER), str(db), kill_point, str(count)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def open_ledger(db: Path) -> TradeLedger:
    return TradeLedger(db)


# --------------------------------------------------------------------------
# Control
# --------------------------------------------------------------------------


def test_clean_run_writes_everything(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    proc = run_writer(db, "none", 5)
    assert proc.returncode == 0, proc.stderr

    ledger = open_ledger(db)
    assert ledger.count_fills() == 5
    assert ledger.verify()["consistent"]
    ledger.close()


def test_the_child_really_dies_by_signal(tmp_path: Path) -> None:
    """Guard against the test silently degrading into a clean-exit test."""
    proc = run_writer(tmp_path / "ledger.db", "after_commit")
    assert proc.returncode == -9, f"expected SIGKILL, got {proc.returncode}"


# --------------------------------------------------------------------------
# 1. No half-row
# --------------------------------------------------------------------------


def test_kill_before_append_leaves_nothing(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    run_writer(db, "before_append")

    ledger = open_ledger(db)
    assert ledger.count_fills() == 0
    assert ledger.verify()["consistent"]
    ledger.close()


def test_kill_mid_transaction_leaves_no_orphan_fill(tmp_path: Path) -> None:
    """The torn write: fill row inserted, legs not, process killed.

    The commit never happens, so WAL discards the frame. If this ever fails,
    the ledger has a fill with no balanced legs — the books do not balance and
    every risk number downstream is built on fiction.
    """
    db = tmp_path / "ledger.db"
    run_writer(db, "mid_append")

    ledger = open_ledger(db)
    report = ledger.verify()
    assert ledger.count_fills() == 0, "an uncommitted fill must not survive"
    assert report["orphan_fills"] == []
    assert report["unbalanced_events"] == []
    assert report["consistent"]
    ledger.close()


def test_books_balance_after_every_surviving_event(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    run_writer(db, "during_replay", 20)

    ledger = open_ledger(db)
    report = ledger.verify()
    assert report["unbalanced_events"] == []
    assert report["orphan_fills"] == []
    ledger.close()


# --------------------------------------------------------------------------
# 2. No lost acknowledged write
# --------------------------------------------------------------------------


def test_acknowledged_write_survives_the_kill(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    proc = run_writer(db, "after_commit")
    acknowledged_id = proc.stdout.strip()
    assert acknowledged_id, "child should have printed the id it committed"

    ledger = open_ledger(db)
    assert ledger.count_fills() == 1
    assert ledger.fills()[0].id == acknowledged_id
    assert ledger.verify()["consistent"]
    ledger.close()


def test_durability_pragmas_are_actually_on(tmp_path: Path) -> None:
    ledger = open_ledger(tmp_path / "ledger.db")
    assert ledger.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert ledger.connection.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    ledger.close()


# --------------------------------------------------------------------------
# 3. No duplicate on retry
# --------------------------------------------------------------------------


def test_replay_after_a_crash_converges_to_exactly_one_row_each(tmp_path: Path) -> None:
    """Not zero (a lost fill), not two (a blind replay). Exactly one."""
    db = tmp_path / "ledger.db"
    run_writer(db, "during_replay", 20)

    ledger = open_ledger(db)
    partial = ledger.count_fills()
    assert 0 < partial < 20, f"expected a partial batch, got {partial}"

    # The recovery pass replays the whole batch, including what already landed.
    from tests.crash.helpers import make_batch

    counts = ledger.replay(make_batch(20))
    assert counts["skipped"] == partial, "already-applied fills must be skipped"
    assert ledger.count_fills() == 20

    broker_ids = [f.broker_fill_id for f in ledger.fills()]
    assert len(broker_ids) == len(set(broker_ids)), "a broker fill id appeared twice"
    assert ledger.verify()["consistent"]
    ledger.close()


def test_replaying_a_complete_batch_twice_changes_nothing(tmp_path: Path) -> None:
    from tests.crash.helpers import make_batch

    ledger = open_ledger(tmp_path / "ledger.db")
    batch = make_batch(10)

    first = ledger.replay(batch)
    second = ledger.replay(batch)

    assert first == {"applied": 10, "skipped": 0}
    assert second == {"applied": 0, "skipped": 10}
    assert ledger.count_fills() == 10
    ledger.close()


def test_idempotency_is_per_account(tmp_path: Path) -> None:
    """The same broker fill id in two accounts is two different fills."""
    from tests.crash.helpers import make_fill

    ledger = open_ledger(tmp_path / "ledger.db")
    assert ledger.record_fill(make_fill(0, account_id="primary")) is not None
    assert ledger.record_fill(make_fill(0, account_id="funded")) is not None
    assert ledger.record_fill(make_fill(0, account_id="primary")) is None
    assert ledger.count_fills() == 2
    ledger.close()
