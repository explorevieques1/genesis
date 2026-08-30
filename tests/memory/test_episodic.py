# Spec: Genesis Markdown/40-Memory/Episodic Log.md
"""Append-only is a database guarantee here, not a convention."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from genesis.ids import new_trace_id
from genesis.memory import EpisodicLog
from genesis.observability import redactor


@pytest.fixture
def log(tmp_path: Path) -> EpisodicLog:
    instance = EpisodicLog(tmp_path / "genesis.db")
    yield instance
    instance.close()


# --------------------------------------------------------------------------
# Append-only, enforced at the database level
# --------------------------------------------------------------------------


def test_update_fails_at_the_database_level(log: EpisodicLog) -> None:
    log.append(actor="bus", kind="task.done", trace_id="tr_1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        log.connection.execute("UPDATE episodic SET summary = 'rewritten'")


def test_delete_fails_at_the_database_level(log: EpisodicLog) -> None:
    log.append(actor="bus", kind="task.done", trace_id="tr_1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        log.connection.execute("DELETE FROM episodic")


def test_the_log_exposes_no_mutation_method(log: EpisodicLog) -> None:
    """Belt and braces: not even a private helper to reach for at 2am."""
    for name in dir(log):
        assert not name.startswith(("update", "delete", "remove", "purge"))


def test_a_correction_is_a_new_row_that_supersedes(log: EpisodicLog) -> None:
    original = log.append(actor="screener", kind="scan.completed",
                          trace_id="tr_1", summary="9 candidates")
    correction = log.append(actor="screener", kind="scan.completed",
                            trace_id="tr_1", summary="8 candidates",
                            supersedes=original)
    entries = log.by_trace("tr_1")
    assert len(entries) == 2
    assert entries[1].supersedes == original
    assert log.get(original).summary == "9 candidates", "original is untouched"


# --------------------------------------------------------------------------
# Required fields
# --------------------------------------------------------------------------


def test_actor_kind_and_trace_are_required(log: EpisodicLog) -> None:
    with pytest.raises(TypeError):
        log.append(kind="task.done", trace_id="tr_1")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        log.append(actor="bus", trace_id="tr_1")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        log.append(actor="bus", kind="task.done")  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# Tracing
# --------------------------------------------------------------------------


def test_by_trace_returns_the_whole_causal_chain(log: EpisodicLog) -> None:
    trace = new_trace_id()
    for kind in ("utterance.heard", "task.submitted", "task.done", "reply.spoken"):
        log.append(actor="orchestrator", kind=kind, trace_id=trace)
    log.append(actor="orchestrator", kind="noise", trace_id=new_trace_id())

    assert [e.kind for e in log.by_trace(trace)] == [
        "utterance.heard", "task.submitted", "task.done", "reply.spoken"
    ]


def test_ordering_is_insertion_order_not_millisecond_order(log: EpisodicLog) -> None:
    """Entries written inside one millisecond must still order causally.

    Ordering by id or ts would fall back to the ULID's random suffix here, which
    can put an effect before its cause.
    """
    trace = new_trace_id()
    kinds = [f"step.{i}" for i in range(50)]
    for kind in kinds:
        log.append(actor="bus", kind=kind, trace_id=trace)
    assert [e.kind for e in log.by_trace(trace)] == kinds


def test_parent_id_builds_the_tree_within_a_trace(log: EpisodicLog) -> None:
    trace = new_trace_id()
    root = log.append(actor="orchestrator", kind="utterance.heard", trace_id=trace)
    child = log.append(actor="screener", kind="agent.run", trace_id=trace,
                       parent_id=root)
    log.append(actor="screener", kind="tool.called", trace_id=trace, parent_id=child)

    tree = log.trace_tree(trace)
    assert [e.kind for e in tree[None]] == ["utterance.heard"]
    assert [e.kind for e in tree[root]] == ["agent.run"]
    assert [e.kind for e in tree[child]] == ["tool.called"]


def test_query_by_actor_and_kind(log: EpisodicLog) -> None:
    log.append(actor="screener", kind="scan.completed", trace_id="tr_1")
    log.append(actor="screener", kind="scan.completed", trace_id="tr_2")
    log.append(actor="watchdog", kind="health.checked", trace_id="tr_3")

    assert len(log.by_actor("screener")) == 2
    assert len(log.by_kind("health.checked")) == 1


# --------------------------------------------------------------------------
# Payloads and secrets
# --------------------------------------------------------------------------


def test_payload_round_trips(log: EpisodicLog) -> None:
    log.append(actor="screener", kind="scan.completed", trace_id="tr_1",
               payload={"universe": 412, "candidates": 9},
               cost={"llm_tokens": 0, "wall_ms": 1840})
    entry = log.by_trace("tr_1")[0]
    assert entry.payload == {"universe": 412, "candidates": 9}
    assert entry.cost["wall_ms"] == 1840


def test_secrets_are_redacted_before_the_log_keeps_them_forever(tmp_path: Path) -> None:
    """The log is permanent — a key written into it cannot be removed."""
    log = EpisodicLog(tmp_path / "genesis.db",
                      scrub=redactor(("sk-super-secret-value",)))
    log.append(actor="broker-adapter", kind="tool.called", trace_id="tr_1",
               payload={"auth": "Bearer sk-super-secret-value"})
    assert "sk-super-secret-value" not in str(log.by_trace("tr_1")[0].payload)
    log.close()


def test_degraded_flag_is_preserved(log: EpisodicLog) -> None:
    log.append(actor="screener", kind="scan.completed", trace_id="tr_1", degraded=True)
    assert log.by_trace("tr_1")[0].degraded is True


# --------------------------------------------------------------------------
# Durability
# --------------------------------------------------------------------------


def test_entries_survive_reopening(tmp_path: Path) -> None:
    path = tmp_path / "genesis.db"
    log = EpisodicLog(path)
    log.append(actor="bus", kind="task.done", trace_id="tr_1")
    log.close()

    reopened = EpisodicLog(path)
    assert reopened.count() == 1
    reopened.close()


def test_pragmas_are_set_for_durability(log: EpisodicLog) -> None:
    assert log.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert log.connection.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    assert log.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
