# Spec: Genesis Markdown/40-Memory/Memory Consolidation.md
"""The nightly pass. Every assertion here is a sentence from the note."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from genesis.memory.consolidate import Consolidator
from genesis.memory.episodic import EpisodicLog
from genesis.memory.graph import KnowledgeGraph
from genesis.memory.vectors import VectorStore
from tests.memory.test_vectors import WordBag

NOW = dt.datetime(2026, 9, 17, 21, 0, tzinfo=dt.UTC)


def _graph(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(path=tmp_path / "graph.db")


def test_levels_within_a_tick_become_one_level(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    for key, price, touches in (("NVDA:121.00", "121.00", 3), ("NVDA:121.02", "121.02", 2)):
        graph.upsert("level", key, label=key, namespace="chart-markup",
                     data={"symbol": "NVDA", "price": price, "touches": touches})
    graph.upsert("level", "NVDA:140.00", label="NVDA:140.00", namespace="chart-markup",
                 data={"symbol": "NVDA", "price": "140.00", "touches": 1})

    report = Consolidator(graph=graph, clock=lambda: NOW).run()
    merged = [p for p in report.passes if p.name == "merge-entities"][0]
    assert merged.changed == 1

    kept = graph.entity("level:NVDA:121.00")
    assert kept is not None and kept.data["touches"] == 5, "counts sum; merging is not deletion"
    assert "NVDA:121.02" in kept.data["aliases"]
    loser = graph.entity("level:NVDA:121.02")
    assert loser is not None and loser.superseded_by == kept.id, "the loser stays queryable"
    assert graph.entity("level:NVDA:140.00").data["touches"] == 1, "a distinct level is untouched"


def test_a_belief_nobody_confirmed_weakens_then_retires(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph.upsert("belief", "semis-lead", label="semis lead the tape", namespace="insight-miner",
                 data={"status": "active", "last_confirmed": "2026-01-01T00:00:00+00:00"})

    Consolidator(graph=graph, clock=lambda: NOW).run()
    assert graph.entity("belief:semis-lead").data["status"] == "weakening"
    Consolidator(graph=graph, clock=lambda: NOW).run()
    assert graph.entity("belief:semis-lead").data["status"] == "retired"


def test_a_fresh_belief_is_left_alone(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph.upsert("belief", "fresh", label="fresh", namespace="insight-miner",
                 data={"status": "active", "last_confirmed": NOW.isoformat()})
    Consolidator(graph=graph, clock=lambda: NOW).run()
    assert graph.entity("belief:fresh").data["status"] == "active"


def test_an_idea_past_its_timeframe_expires(tmp_path: Path) -> None:
    graph = _graph(tmp_path)
    graph.upsert("idea", "nvda-orb", label="NVDA ORB", namespace="idea-synthesizer",
                 data={"status": "active", "expires_at": "2026-09-01T00:00:00+00:00"})
    Consolidator(graph=graph, clock=lambda: NOW).run()
    assert graph.entity("idea:nvda-orb").data["status"] == "expired"


def test_compaction_summarises_and_deletes_nothing(tmp_path: Path) -> None:
    """Memory Fabric: the episodic log is summarised, never deleted.

    The classification is the digest's, so this wires the real one rather than
    asserting against a second copy of the rule.
    """
    from genesis.agents.journal.digest import DigestAgent
    from genesis.journal.store import JournalStore

    log = EpisodicLog(tmp_path / "ep.db")
    for _ in range(5):
        log.append(actor="daemon", kind="health.check", trace_id="t1")
    log.append(actor="order-manager", kind="fill.recorded", trace_id="t2")
    before = log.count()

    digest = DigestAgent(JournalStore(tmp_path / "journal.db"), episodic=log)
    report = Consolidator(episodic=log, digest=digest, clock=lambda: NOW).run()

    compacted = [p for p in report.passes if p.name == "compact-episodic"][0]
    assert compacted.ok and compacted.changed == 5, compacted.detail

    summary = log.by_kind("episodic.compacted", limit=1)[0]
    assert summary.payload["preserved"] == 1, "a fill is never collapsible"
    assert summary.payload["collapsible"] == 5
    assert log.count() == before + 2, "one summary row and one report row; nothing removed"


def test_the_log_refuses_deletion_at_the_database_level(tmp_path: Path) -> None:
    """Why compaction cannot mean deletion, proved rather than assumed."""
    log = EpisodicLog(tmp_path / "ep.db")
    log.append(actor="daemon", kind="health.check", trace_id="t1")
    with pytest.raises(Exception, match="append-only"):
        log.connection.execute("DELETE FROM episodic")


def test_a_failing_pass_is_skipped_not_fatal(tmp_path: Path) -> None:
    class Exploding:
        def entities(self, **kw: object) -> list[object]:
            raise RuntimeError("graph is on fire")

    report = Consolidator(graph=Exploding(), clock=lambda: NOW).run()
    merged = [p for p in report.passes if p.name == "merge-entities"][0]
    assert not merged.ok and "on fire" in merged.detail
    assert not report.ok
    assert [p.name for p in report.passes if p.ok], "the other passes still ran"


def test_integrity_alerts_and_does_not_repair(tmp_path: Path) -> None:
    from genesis.memory.ledger import Fill, TradeLedger

    ledger = TradeLedger(tmp_path / "ledger.db")
    ledger.record_fill(Fill(
        account_id="DU1", client_order_id="c1", broker_fill_id="b1", approval_id="a1",
        symbol="NVDA", side="buy", qty=10, price=Decimal("100"), fee=Decimal("1"),
        trace_id="t1", ts="2026-09-17T14:00:00+00:00",
    ))
    # Stored positions were never snapshotted, so the rebuild disagrees with them.
    report = Consolidator(ledger=ledger, clock=lambda: NOW).run()
    integrity = [p for p in report.passes if p.name == "integrity"][0]
    assert not integrity.ok
    assert "position drift" in integrity.detail
    assert report.alerts, "an integrity failure is an alert"
    assert ledger.stored_positions() == {}, "it alerts; it never quietly repairs"


def test_edited_vault_notes_are_re_embedded(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "20-Journal").mkdir(parents=True)
    note = vault / "20-Journal" / "lesson.md"
    note.write_text("I keep taking NVDA breakout trades too late.\n", encoding="utf-8")
    vectors = VectorStore(tmp_path / "vec.db", WordBag())

    report = Consolidator(vectors=vectors, vault_path=vault, clock=lambda: NOW).run()
    absorbed = [p for p in report.passes if p.name == "absorb-vault-edits"][0]
    assert absorbed.ok and absorbed.changed == 1
    hits = vectors.search("NVDA breakout", namespaces=["vault"])
    assert hits and hits[0].ref == "20-Journal/lesson.md"


def test_a_pass_with_nothing_wired_says_skipped(tmp_path: Path) -> None:
    report = Consolidator(clock=lambda: NOW).run()
    assert report.ok
    assert all("skipped" in p.detail for p in report.passes), report.to_dict()
