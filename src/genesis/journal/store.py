# Spec: Genesis Markdown/70-Schemas/Trade Journal Schema.md
"""The journal store: what the system remembers, and how it accumulates.

This is the substrate the Journal Family's whole claim rests on. Journal
Family.md:

> The loop closes when a lesson changes a future decision. A journal that is
> only ever written is a diary; a journal that is read back into the decision
> process is an edge.

A diary needs a file. An edge needs a *queryable* store with four properties,
and each one is enforced here rather than trusted:

**Machine fields are immutable; human fields are not.** A ``BEFORE UPDATE``
trigger rejects any change to a price, an R multiple, or a plan-adherence flag,
while leaving the reflective columns writable. This is the machine/human split
made structural: the numbers the analyst reasons over cannot be edited after the
fact, including by the person who took the trade and now remembers it
differently.

**`lessons` has exactly one writer.** Memory Fabric names Agent — Insight Miner
as the only writer of that namespace. Here that is a column check, so a lesson
written by anything else fails loudly instead of silently diluting the one
namespace with elevated recall priority.

**Findings accumulate.** :meth:`record_hypothesis` upserts on a stable key, so
the same pattern found on thirty consecutive nights is one row whose evidence
grows — not thirty rows, and not thirty discarded findings. This is the
mechanism by which the system gets smarter over months.

**Observations are not trade-shaped.** They arrive from anywhere: a level that
held, an idea that was skipped, a feed that was stale. Which matters right now,
because the charting family is producing scoreable outcomes today and execution
does not exist yet -- so the store starts compounding before the first fill.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

from genesis.errors import FatalError
from genesis.journal.schema import (
    Evidence,
    Hypothesis,
    JournalEntry,
    Lesson,
    Observation,
)
from genesis.memory.db import connect, transaction

__all__ = ["INSIGHT_MINER", "SCHEMA", "JournalStore"]

#: The only agent permitted to write a lesson. Memory Fabric's single-writer
#: rule for the `lessons` namespace, as a value rather than a convention.
INSIGHT_MINER = "insight-miner"

#: Columns a human may fill in after the close. Everything else is machine
#: output and is frozen by trigger.
HUMAN_COLUMNS = (
    "emotion_entry",
    "emotion_hold",
    "confidence_felt",
    "followed_plan",
    "what_i_thought",
    "what_id_do_differently",
    "notes",
    "tags",
    "prompted_at",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_entry (
    id            TEXT PRIMARY KEY,
    created       TEXT NOT NULL,
    trace_id      TEXT,
    symbol        TEXT NOT NULL,
    direction     TEXT NOT NULL,
    account       TEXT NOT NULL,
    strategy      TEXT,
    setup         TEXT,
    idea          TEXT,
    entry_ts      TEXT NOT NULL,
    exit_ts       TEXT NOT NULL,
    r_multiple    REAL,
    pnl_net       REAL,
    regime        TEXT,
    session_segment TEXT,
    day_of_week   TEXT,
    qty           INTEGER NOT NULL,
    stop_moved    INTEGER NOT NULL DEFAULT 0,
    plan_followed INTEGER,
    -- The reflective half. These are the only columns an UPDATE may touch.
    emotion_entry TEXT,
    emotion_hold  TEXT,
    confidence_felt REAL,
    followed_plan INTEGER,
    what_i_thought TEXT,
    what_id_do_differently TEXT,
    notes         TEXT,
    tags          TEXT,
    prompted_at   TEXT,
    -- The machine record, frozen. Human reflection lives in the columns above
    -- and is merged back on read, so there is exactly one immutable copy of
    -- what the machine observed and exactly one mutable copy of what the person
    -- thought. Storing both in one blob would mean either the blob is writable
    -- (and the numbers are editable) or the reflection is not.
    body          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS journal_exit    ON journal_entry(exit_ts);
CREATE INDEX IF NOT EXISTS journal_symbol  ON journal_entry(symbol, exit_ts);
CREATE INDEX IF NOT EXISTS journal_setup   ON journal_entry(setup, exit_ts);
CREATE INDEX IF NOT EXISTS journal_strategy ON journal_entry(strategy, exit_ts);

-- Machine fields are frozen. The human half stays writable, which is the point:
-- the reflective columns are subjective by design and must never be able to
-- leak into the arithmetic the analyst reasons over.
CREATE TRIGGER IF NOT EXISTS journal_machine_fields_are_immutable
BEFORE UPDATE OF
    id, created, trace_id, symbol, direction, account, strategy, setup, idea,
    entry_ts, exit_ts, r_multiple, pnl_net, regime, session_segment,
    day_of_week, qty, stop_moved, plan_followed, body
ON journal_entry
BEGIN
    SELECT RAISE(ABORT, 'journal machine fields are computed and immutable: only the human reflection columns may be updated');
END;

CREATE TRIGGER IF NOT EXISTS journal_no_delete
BEFORE DELETE ON journal_entry
BEGIN
    SELECT RAISE(ABORT, 'journal entries are permanent: DELETE forbidden');
END;

CREATE TABLE IF NOT EXISTS lesson (
    id            TEXT PRIMARY KEY,
    created       TEXT NOT NULL,
    written_by    TEXT NOT NULL,
    key           TEXT NOT NULL DEFAULT '',
    title         TEXT NOT NULL,
    observations  INTEGER NOT NULL,
    confidence    REAL NOT NULL,
    enforcement   TEXT NOT NULL,
    status        TEXT NOT NULL,
    supersedes    TEXT REFERENCES lesson(id),
    approved_by_human INTEGER NOT NULL DEFAULT 0,
    body          TEXT NOT NULL,
    -- Single-writer, enforced by the database. Memory Fabric names Insight
    -- Miner as the only writer of `lessons`; a CHECK is what makes that true
    -- rather than aspirational.
    CHECK (written_by = 'insight-miner')
);

CREATE INDEX IF NOT EXISTS lesson_status ON lesson(status, created);
CREATE INDEX IF NOT EXISTS lesson_key    ON lesson(key, status);

CREATE TABLE IF NOT EXISTS hypothesis (
    key           TEXT PRIMARY KEY,      -- stable: the same pattern updates
    id            TEXT NOT NULL,
    created       TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    title         TEXT NOT NULL,
    observations  INTEGER NOT NULL,
    confidence    REAL NOT NULL,
    promoted_to   TEXT REFERENCES lesson(id),
    body          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS hypothesis_seen ON hypothesis(last_seen);

CREATE TABLE IF NOT EXISTS observation (
    id            TEXT PRIMARY KEY,
    at            TEXT NOT NULL,
    kind          TEXT NOT NULL,
    subject       TEXT NOT NULL,
    outcome       TEXT,
    value         REAL,
    unit          TEXT,
    source        TEXT,
    trace_id      TEXT,
    detail        TEXT
);

CREATE INDEX IF NOT EXISTS observation_kind    ON observation(kind, at);
CREATE INDEX IF NOT EXISTS observation_subject ON observation(subject, at);

-- An observation is a record of something that happened. Correcting it means
-- recording what actually happened, not editing history.
CREATE TRIGGER IF NOT EXISTS observation_no_update
BEFORE UPDATE ON observation
BEGIN
    SELECT RAISE(ABORT, 'observations are append-only');
END;
"""


@dataclass
class JournalStore:
    """Durable home for entries, lessons, hypotheses and observations."""

    path: Path | str = "~/.genesis/memory/journal.db"
    _conn: sqlite3.Connection | None = None

    def __post_init__(self) -> None:
        self._conn = connect(self.path)
        # executescript commits on its own, so it must not sit inside an
        # explicit transaction.
        self._conn.executescript(SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("JournalStore is closed")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Journal entries
    # ------------------------------------------------------------------

    def put_entry(self, entry: JournalEntry) -> JournalEntry:
        """Store a closed trade. Idempotent on id, per the Agent Contract."""
        with transaction(self.conn) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO journal_entry (
                    id, created, trace_id, symbol, direction, account, strategy,
                    setup, idea, entry_ts, exit_ts, r_multiple, pnl_net, regime,
                    session_segment, day_of_week, qty, stop_moved, plan_followed,
                    emotion_entry, emotion_hold, confidence_felt, followed_plan,
                    what_i_thought, what_id_do_differently, notes, tags,
                    prompted_at, body
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    entry.id, entry.created.isoformat(), entry.trace_id,
                    entry.symbol, entry.direction, entry.account, entry.strategy,
                    entry.setup, entry.idea, entry.entry_ts.isoformat(),
                    entry.exit_ts.isoformat(), entry.r_multiple, entry.pnl_net,
                    entry.regime, entry.session_segment, entry.day_of_week,
                    entry.qty, int(entry.plan_adherence.stop_moved),
                    int(entry.plan_adherence.followed),
                    entry.emotion_entry, entry.emotion_hold, entry.confidence_felt,
                    None if entry.followed_plan is None else int(entry.followed_plan),
                    entry.what_i_thought, entry.what_id_do_differently, entry.notes,
                    json.dumps(list(entry.tags)),
                    entry.prompted_at.isoformat() if entry.prompted_at else None,
                    _machine_json(entry),
                ),
            )
        return entry

    def patch_human(self, entry_id: str, **fields: Any) -> JournalEntry:
        """Fill in the reflective half. The one permitted mutation.

        Only the human columns are written; ``body`` is never touched, because
        it is the frozen machine record and the trigger refuses it. That refusal
        is the design working, not an obstacle to route around: the reflective
        half is subjective by construction and must not be able to reach the
        arithmetic the analyst reasons over.
        """
        entry = self.entry(entry_id)
        if entry is None:
            raise FatalError(f"no journal entry {entry_id!r}")
        patched = entry.human_patch(**fields)
        assignments = ", ".join(f"{column} = ?" for column in HUMAN_COLUMNS)
        with transaction(self.conn) as conn:
            conn.execute(
                f"UPDATE journal_entry SET {assignments} WHERE id = ?",
                (
                    patched.emotion_entry, patched.emotion_hold,
                    patched.confidence_felt,
                    None if patched.followed_plan is None else int(patched.followed_plan),
                    patched.what_i_thought, patched.what_id_do_differently,
                    patched.notes, json.dumps(list(patched.tags)),
                    patched.prompted_at.isoformat() if patched.prompted_at else None,
                    entry_id,
                ),
            )
        return patched

    def entry(self, entry_id: str) -> JournalEntry | None:
        row = self.conn.execute(
            "SELECT * FROM journal_entry WHERE id = ?", (entry_id,)
        ).fetchone()
        return _row_to_entry(row) if row else None

    def entries(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        symbol: str | None = None,
        strategy: str | None = None,
        setup: str | None = None,
        limit: int = 5000,
    ) -> list[JournalEntry]:
        """Closed trades, oldest first — the order every sequence effect needs.

        Ascending rather than newest-first because the Insight Miner's whole
        subject is *sequence*: "you oversize after two losses" is unanswerable
        from a list in reverse, and every caller would have to remember to flip
        it.
        """
        clauses = ["1=1"]
        args: list[Any] = []
        if since is not None:
            clauses.append("exit_ts >= ?")
            args.append(since.isoformat())
        if until is not None:
            clauses.append("exit_ts <= ?")
            args.append(until.isoformat())
        for column, value in (
            ("symbol", symbol.upper() if symbol else None),
            ("strategy", strategy),
            ("setup", setup),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                args.append(value)
        args.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM journal_entry WHERE {' AND '.join(clauses)} "
            f"ORDER BY exit_ts ASC, id ASC LIMIT ?",
            args,
        ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def unprompted(self, *, before: datetime | None = None) -> list[JournalEntry]:
        """Entries never offered for reflection.

        The Trade Journal asks once, after the close, and never again. This is
        the query that makes "once" literal rather than a hope: an entry leaves
        this list the moment it is prompted, whether or not anything was said.
        """
        args: list[Any] = []
        clause = "prompted_at IS NULL"
        if before is not None:
            clause += " AND exit_ts <= ?"
            args.append(before.isoformat())
        rows = self.conn.execute(
            f"SELECT * FROM journal_entry WHERE {clause} ORDER BY exit_ts ASC",
            args,
        ).fetchall()
        return [_row_to_entry(r) for r in rows]

    # ------------------------------------------------------------------
    # Lessons
    # ------------------------------------------------------------------

    def put_lesson(self, lesson: Lesson, *, written_by: str = INSIGHT_MINER) -> Lesson:
        """Write a lesson. Only the Insight Miner may.

        Checked twice, and the Python half is not redundant. The table carries a
        ``CHECK (written_by = 'insight-miner')``, but this insert is
        ``INSERT OR IGNORE`` for idempotency -- and SQLite's ``OR IGNORE``
        *skips the row* on a constraint violation instead of raising. So the
        CHECK alone would have made a forbidden write silently succeed-looking
        and silently do nothing, which is worse than either outcome on its own.

        The CHECK stays as defence in depth for anything writing SQL directly.
        This raise is what makes the rule visible to callers.
        """
        if written_by != INSIGHT_MINER:
            raise FatalError(
                f"{written_by!r} may not write a lesson — `lessons` is a "
                f"single-writer namespace owned by {INSIGHT_MINER!r} "
                f"(Memory Fabric)"
            )
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO lesson (id, created, written_by, key, title, "
                "observations, confidence, enforcement, status, supersedes, "
                "approved_by_human, body) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lesson.id, lesson.created.isoformat(), written_by, lesson.key,
                    lesson.title,
                    lesson.evidence.observations, lesson.evidence.confidence,
                    lesson.enforcement, lesson.status, lesson.supersedes,
                    int(lesson.approved_by_human), lesson.model_dump_json(),
                ),
            )
            if lesson.supersedes:
                # Superseding, not accumulating: the note's acceptance criterion
                # is that a duplicate finding replaces the earlier lesson rather
                # than the two both surfacing in the synthesizer's context.
                conn.execute(
                    "UPDATE lesson SET status = 'superseded' WHERE id = ?",
                    (lesson.supersedes,),
                )
        return lesson

    def lessons(self, *, status: str = "active") -> list[Lesson]:
        rows = self.conn.execute(
            "SELECT body FROM lesson WHERE status = ? ORDER BY created DESC",
            (status,),
        ).fetchall()
        return [Lesson.model_validate_json(r["body"]) for r in rows]

    def lesson_by_key(self, key: str, *, status: str = "active") -> Lesson | None:
        """The current lesson for a detector key, if there is one.

        The lookup behind supersede-don't-accumulate. Two lessons about the same
        behaviour in the Idea Synthesizer's context are two votes for one fact.
        """
        if not key:
            return None
        row = self.conn.execute(
            "SELECT body FROM lesson WHERE key = ? AND status = ? "
            "ORDER BY created DESC LIMIT 1",
            (key, status),
        ).fetchone()
        return Lesson.model_validate_json(row["body"]) if row else None

    def lesson(self, lesson_id: str) -> Lesson | None:
        row = self.conn.execute(
            "SELECT body FROM lesson WHERE id = ?", (lesson_id,)
        ).fetchone()
        return Lesson.model_validate_json(row["body"]) if row else None

    def retire_lesson(self, lesson_id: str) -> None:
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE lesson SET status = 'retired' WHERE id = ?", (lesson_id,)
            )

    # ------------------------------------------------------------------
    # Hypotheses — the accumulator
    # ------------------------------------------------------------------

    def record_hypothesis(self, hypothesis: Hypothesis) -> Hypothesis:
        """Upsert on ``key``. The same pattern seen again grows; it does not repeat.

        Without this the nightly pass would rediscover an under-evidenced
        pattern, decline to write it, and forget -- forever. With it the finding
        accrues until it qualifies, which is the difference between a system
        that learns over months and one that starts from zero every night.
        """
        existing = self.hypothesis(hypothesis.key)
        merged = hypothesis
        if existing is not None:
            merged = existing.model_copy(
                update={
                    "last_seen": hypothesis.last_seen,
                    "title": hypothesis.title,
                    "finding": hypothesis.finding,
                    "evidence": hypothesis.evidence,
                    "applies_when": hypothesis.applies_when,
                }
            )
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT INTO hypothesis (key, id, created, last_seen, title, "
                "observations, confidence, promoted_to, body) "
                "VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen, "
                "title=excluded.title, observations=excluded.observations, "
                "confidence=excluded.confidence, body=excluded.body",
                (
                    merged.key, merged.id, merged.created.isoformat(),
                    merged.last_seen.isoformat(), merged.title,
                    merged.evidence.observations, merged.evidence.confidence,
                    merged.promoted_to, merged.model_dump_json(),
                ),
            )
        return merged

    def hypothesis(self, key: str) -> Hypothesis | None:
        row = self.conn.execute(
            "SELECT body FROM hypothesis WHERE key = ?", (key,)
        ).fetchone()
        return Hypothesis.model_validate_json(row["body"]) if row else None

    def hypotheses(self, *, ready_only: bool = False) -> list[Hypothesis]:
        rows = self.conn.execute(
            "SELECT body FROM hypothesis WHERE promoted_to IS NULL "
            "ORDER BY observations DESC, last_seen DESC"
        ).fetchall()
        found = [Hypothesis.model_validate_json(r["body"]) for r in rows]
        return [h for h in found if h.ready] if ready_only else found

    def promote(self, key: str, lesson: Lesson) -> Lesson:
        """Graduate a hypothesis into a lesson, keeping the trail."""
        self.put_lesson(lesson)
        with transaction(self.conn) as conn:
            conn.execute(
                "UPDATE hypothesis SET promoted_to = ?, body = json_set(body, "
                "'$.promoted_to', ?) WHERE key = ?",
                (lesson.id, lesson.id, key),
            )
        return lesson

    # ------------------------------------------------------------------
    # Observations — the wide net
    # ------------------------------------------------------------------

    def record(self, observation: Observation) -> Observation:
        with transaction(self.conn) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO observation (id, at, kind, subject, "
                "outcome, value, unit, source, trace_id, detail) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    observation.id, observation.at.isoformat(), observation.kind,
                    observation.subject, observation.outcome, observation.value,
                    observation.unit, observation.source, observation.trace_id,
                    json.dumps(observation.detail, sort_keys=True, default=str),
                ),
            )
        return observation

    def record_many(self, observations: Iterable[Observation]) -> int:
        count = 0
        for observation in observations:
            self.record(observation)
            count += 1
        return count

    def observations(
        self,
        *,
        kind: str | None = None,
        subject: str | None = None,
        since: datetime | None = None,
        limit: int = 5000,
    ) -> list[Observation]:
        clauses = ["1=1"]
        args: list[Any] = []
        if kind:
            # Prefix match, so `kind="level"` finds `level.outcome` and
            # `level.touched` without the caller enumerating them.
            clauses.append("(kind = ? OR kind LIKE ?)")
            args.extend([kind, f"{kind}.%"])
        if subject:
            clauses.append("subject = ?")
            args.append(subject)
        if since is not None:
            clauses.append("at >= ?")
            args.append(since.isoformat())
        args.append(limit)
        rows = self.conn.execute(
            f"SELECT * FROM observation WHERE {' AND '.join(clauses)} "
            f"ORDER BY at ASC LIMIT ?",
            args,
        ).fetchall()
        return [
            Observation(
                id=r["id"], at=datetime.fromisoformat(r["at"]), kind=r["kind"],
                subject=r["subject"], outcome=r["outcome"] or "", value=r["value"],
                unit=r["unit"] or "", source=r["source"] or "",
                trace_id=r["trace_id"],
                detail=json.loads(r["detail"]) if r["detail"] else {},
            )
            for r in rows
        ]

    def outcome_rate(
        self, kind: str, *, good: Sequence[str], subject_prefix: str = ""
    ) -> dict[str, Any]:
        """How often a kind of observation came out well, with its ``n``.

        The query behind *"your anchored-VWAP levels hold 71% of the time and
        your trendlines hold 38%"* — Charting Family's stated distinctive edge,
        and the one finding this system can produce today because the charting
        family is already recording outcomes.

        Returns ``rate: None`` rather than 0.0 on an empty sample. A rate of
        zero and no data are different facts and must not read the same.
        """
        clauses = ["(kind = ? OR kind LIKE ?)"]
        args: list[Any] = [kind, f"{kind}.%"]
        if subject_prefix:
            clauses.append("subject LIKE ?")
            args.append(f"{subject_prefix}%")
        rows = self.conn.execute(
            f"SELECT outcome, source, COUNT(*) n FROM observation "
            f"WHERE {' AND '.join(clauses)} GROUP BY outcome, source",
            args,
        ).fetchall()
        total = sum(r["n"] for r in rows)
        hits = sum(r["n"] for r in rows if r["outcome"] in good)
        by_source: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket = by_source.setdefault(row["source"] or "unknown", {"n": 0, "good": 0})
            bucket["n"] += row["n"]
            if row["outcome"] in good:
                bucket["good"] += row["n"]
        return {
            "kind": kind,
            "n": total,
            "rate": (hits / total) if total else None,
            "by_source": {
                name: {
                    "n": bucket["n"],
                    "rate": bucket["good"] / bucket["n"] if bucket["n"] else None,
                }
                for name, bucket in sorted(by_source.items())
            },
        }

    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return int(
            self.conn.execute("SELECT COUNT(*) c FROM journal_entry").fetchone()["c"]
        )

    def counts(self) -> dict[str, int]:
        """One row of every table. What the Digest reports and the Watchdog probes."""
        return {
            table: int(
                self.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            )
            for table in ("journal_entry", "lesson", "hypothesis", "observation")
        }


# --------------------------------------------------------------------------
# Row <-> entry
# --------------------------------------------------------------------------

#: The reflective fields, cleared out of the frozen machine record.
_HUMAN_FIELDS = {
    "emotion_entry": None,
    "emotion_hold": None,
    "confidence_felt": None,
    "followed_plan": None,
    "what_i_thought": "",
    "what_id_do_differently": "",
    "notes": "",
    "prompted_at": None,
}


def _machine_json(entry: JournalEntry) -> str:
    """The entry with the human half stripped. What ``body`` holds, forever."""
    return entry.model_copy(update=dict(_HUMAN_FIELDS)).model_dump_json()


def _row_to_entry(row: sqlite3.Row) -> JournalEntry:
    """Frozen machine record plus the current human columns.

    The merge happens on read rather than on write so there is never a moment
    where a reflection has been recorded and the machine record has been
    rewritten to contain it -- which is the state an audit could not distinguish
    from a machine field having been edited.
    """
    entry = JournalEntry.model_validate_json(row["body"])
    followed = row["followed_plan"]
    return entry.model_copy(
        update={
            "emotion_entry": row["emotion_entry"],
            "emotion_hold": row["emotion_hold"],
            "confidence_felt": row["confidence_felt"],
            "followed_plan": None if followed is None else bool(followed),
            "what_i_thought": row["what_i_thought"] or "",
            "what_id_do_differently": row["what_id_do_differently"] or "",
            "notes": row["notes"] or "",
            "tags": tuple(json.loads(row["tags"]) if row["tags"] else ()),
            "prompted_at": (
                datetime.fromisoformat(row["prompted_at"])
                if row["prompted_at"]
                else None
            ),
        }
    )
