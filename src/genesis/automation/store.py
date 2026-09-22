# Spec: Genesis Markdown/60-UI/Automation.md §Q1
"""Workflows as an append-only version log, and what each run did.

Nothing is updated in place. A save, an enable, a disable and a delete each
append a version with its author and time, so "who changed this, when, and what
changed" is two rows of the same workflow. Current is the highest version; a
delete is a version whose body is null.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genesis.automation.workflow import Workflow
from genesis.errors import DegradedError

__all__ = ["VersionConflict", "WorkflowStore", "WorkflowVersion"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_versions (
    workflow_id TEXT NOT NULL,
    version     INTEGER NOT NULL,
    body        TEXT,
    enabled     INTEGER NOT NULL,
    author      TEXT NOT NULL,
    at          TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (workflow_id, version)
);
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id      TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    version     INTEGER NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status      TEXT NOT NULL,
    steps       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS workflow_runs_by_workflow
    ON workflow_runs(workflow_id, started_at);
CREATE TABLE IF NOT EXISTS workflow_alerts (
    alert_id    TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    step_id     TEXT NOT NULL,
    at          TEXT NOT NULL,
    title       TEXT NOT NULL,
    message     TEXT NOT NULL,
    urgency     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS workflow_alerts_by_at ON workflow_alerts(at);
"""


class VersionConflict(DegradedError):
    """Someone saved since you loaded. Reload rather than overwrite."""


@dataclass(frozen=True)
class WorkflowVersion:
    workflow_id: str
    version: int
    body: dict[str, Any] | None
    enabled: bool
    author: str
    at: str
    note: str

    @property
    def deleted(self) -> bool:
        return self.body is None

    def workflow(self) -> Workflow:
        assert self.body is not None
        return Workflow.model_validate(self.body)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id, "version": self.version, "body": self.body,
            "enabled": self.enabled, "author": self.author, "at": self.at,
            "note": self.note, "deleted": self.deleted,
        }


class WorkflowStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- versions ----------------------------------------------------------

    def _append(
        self, workflow_id: str, body: dict[str, Any] | None, enabled: bool,
        author: str, note: str, base_version: int | None,
    ) -> WorkflowVersion:
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT MAX(version) FROM workflow_versions WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            latest = row[0] or 0
            if base_version is not None and base_version != latest:
                raise VersionConflict(
                    f"workflow {workflow_id!r} is at v{latest}, you edited v{base_version}"
                )
            version = WorkflowVersion(
                workflow_id=workflow_id, version=latest + 1, body=body,
                enabled=enabled, author=author,
                at=datetime.now(UTC).isoformat(timespec="seconds"), note=note,
            )
            self._conn.execute(
                "INSERT INTO workflow_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (workflow_id, version.version,
                 None if body is None else json.dumps(body, sort_keys=True),
                 int(enabled), author, version.at, note),
            )
        return version

    def save(
        self, workflow: Workflow, *, author: str, enabled: bool | None = None,
        note: str = "", base_version: int | None = None,
    ) -> WorkflowVersion:
        """Append a version. ``enabled=None`` keeps the current state (off if new)."""
        current = self.current(workflow.id)
        keep = bool(current and current.enabled)
        return self._append(
            workflow.id, workflow.model_dump(mode="json"),
            keep if enabled is None else enabled, author, note, base_version,
        )

    def set_enabled(self, workflow_id: str, enabled: bool, *, author: str) -> WorkflowVersion:
        current = self._require(workflow_id)
        return self._append(
            workflow_id, current.body, enabled, author,
            "enabled" if enabled else "disabled", current.version,
        )

    def delete(self, workflow_id: str, *, author: str) -> WorkflowVersion:
        current = self._require(workflow_id)
        return self._append(workflow_id, None, False, author, "deleted", current.version)

    def _require(self, workflow_id: str) -> WorkflowVersion:
        current = self.current(workflow_id)
        if current is None:
            raise DegradedError(f"no workflow {workflow_id!r}")
        return current

    def current(self, workflow_id: str) -> WorkflowVersion | None:
        """The latest version, or None if it never existed or was deleted."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id = ? "
                "ORDER BY version DESC LIMIT 1", (workflow_id,),
            ).fetchone()
        version = _version(row) if row else None
        return None if version is None or version.deleted else version

    def list(self) -> list[WorkflowVersion]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT v.* FROM workflow_versions v JOIN ("
                "  SELECT workflow_id, MAX(version) AS version FROM workflow_versions"
                "  GROUP BY workflow_id) latest USING (workflow_id, version)"
                " WHERE v.body IS NOT NULL ORDER BY v.workflow_id"
            ).fetchall()
        return [_version(r) for r in rows]

    def versions(self, workflow_id: str) -> list[WorkflowVersion]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id = ? ORDER BY version DESC",
                (workflow_id,),
            ).fetchall()
        return [_version(r) for r in rows]

    # -- runs --------------------------------------------------------------

    def record_run(
        self, *, run_id: str, workflow_id: str, version: int, started_at: str,
        status: str, steps: list[dict[str, Any]],
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO workflow_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, workflow_id, version, started_at,
                 datetime.now(UTC).isoformat(timespec="seconds"), status,
                 json.dumps(steps, default=str)),
            )

    def runs(self, workflow_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM workflow_runs WHERE workflow_id = ? "
                "ORDER BY started_at DESC LIMIT ?", (workflow_id, limit),
            ).fetchall()
        return [{**dict(r), "steps": json.loads(r["steps"])} for r in rows]


    def recent_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Every workflow's runs, newest first. What the feed reads.

        ``runs`` answers "what did this workflow do"; the feed asks the other
        question -- "what has anything produced lately" -- so it cannot be a
        per-workflow query with a loop around it.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM workflow_runs ORDER BY started_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return [{**dict(r), "steps": json.loads(r["steps"])} for r in rows]

    # -- alerts ------------------------------------------------------------

    def add_alert(
        self, *, alert_id: str, workflow_id: str, run_id: str, step_id: str,
        at: str, title: str, message: str, urgency: str,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO workflow_alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, workflow_id, run_id, step_id, at, title, message, urgency),
            )

    def alerts(self, *, limit: int = 50, workflow_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM workflow_alerts"
        args: tuple[Any, ...] = ()
        if workflow_id:
            sql, args = sql + " WHERE workflow_id = ?", (workflow_id,)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY at DESC LIMIT ?", (*args, limit)).fetchall()
        return [dict(r) for r in rows]

    def last_alert_at(self, workflow_id: str, step_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(at) FROM workflow_alerts WHERE workflow_id = ? AND step_id = ?",
                (workflow_id, step_id),
            ).fetchone()
        return row[0] if row else None


def _version(row: sqlite3.Row) -> WorkflowVersion:
    return WorkflowVersion(
        workflow_id=row["workflow_id"], version=row["version"],
        body=None if row["body"] is None else json.loads(row["body"]),
        enabled=bool(row["enabled"]), author=row["author"], at=row["at"],
        note=row["note"],
    )
