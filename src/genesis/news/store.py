# Spec: Genesis Markdown/60-UI/News.md §Store
"""``news.db`` — the headlines Genesis collected, the text it read, what it made of them.

Three tables and a log:

- ``articles`` — one row per story. Keyed by title + publisher, not URL: the
  same story arrives under a publisher URL from ``Ticker.news`` and a Yahoo URL
  from ``Search``, and keying on the URL shows it twice. A story seen under two
  symbols is one row with both symbols.
- ``body`` / ``analysis`` on that row — the article text (read on demand) and
  the AI summary. Both are **tier 4**: third-party claims and a model's reading
  of them. Nothing here is a number the risk engine may read.
- ``briefs`` — multi-article summaries (the weekend brief), each listing the
  article ids it read, so a brief can be checked against its sources.
- ``econ_events`` — the forward economic calendar: one row per scheduled print,
  with its impact rating. A *schedule*, not a reading of one, so unlike the
  tables above it is tier 3 and carries no model output. Rows are replaced in
  place when the vendor revises a time or fills in a forecast.
- ``collections`` — one line per collector run. It is what Status shows, and a
  collector that ran and got nothing is visible as that, not as silence.

The trader's own cache, deletable, the conversation-store pattern. No order,
size or broker anywhere in the schema.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from functools import wraps
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

__all__ = ["NewsStore", "article_id"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    alt_url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    publisher TEXT NOT NULL,
    published TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    symbols TEXT NOT NULL DEFAULT '[]',
    thumbnail TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    collected TEXT NOT NULL,
    body TEXT,
    body_at TEXT,
    analysis TEXT,
    analysis_at TEXT
);
CREATE INDEX IF NOT EXISTS articles_published ON articles(published);
CREATE TABLE IF NOT EXISTS briefs (
    id TEXT PRIMARY KEY,
    created TEXT NOT NULL,
    title TEXT NOT NULL,
    hours REAL NOT NULL,
    requested_by TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS econ_events (
    id TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    country TEXT NOT NULL,
    title TEXT NOT NULL,
    impact TEXT NOT NULL,
    forecast TEXT NOT NULL DEFAULT '',
    previous TEXT NOT NULL DEFAULT '',
    all_day INTEGER NOT NULL DEFAULT 0,
    fetched TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS econ_events_at ON econ_events(at);
CREATE TABLE IF NOT EXISTS collections (
    at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    sources INTEGER NOT NULL,
    fetched INTEGER NOT NULL,
    new INTEGER NOT NULL,
    detail TEXT NOT NULL
);
"""

_LIST_COLUMNS = (
    "id, url, alt_url, title, publisher, published, summary, symbols, thumbnail, "
    "source, collected, body_at, analysis_at"
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def article_id(title: str, publisher: str) -> str:
    key = f"{' '.join(title.lower().split())}|{publisher.lower().strip()}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _locked(method):  # noqa: ANN001, ANN202
    """One connection, many threads: serialise every use of it.

    `check_same_thread=False` only lifts sqlite3's guard; it does not make one
    connection safe to use concurrently. `write_brief` reads article bodies on a
    thread pool, and without this two `set_body` calls collide with
    ``InterfaceError: bad parameter or other API misuse``.
    """
    @wraps(method)
    def wrapped(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class NewsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Daemon writes, server reads: WAL so neither blocks the other.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    @_locked
    def close(self) -> None:
        self._conn.close()

    # -- articles ----------------------------------------------------------

    @_locked
    def add(self, items: Iterable[dict[str, Any]]) -> int:
        """Upsert stories. Returns how many were new. Symbols merge; text is kept."""
        new = 0
        with self._conn:
            for item in items:
                aid = article_id(item["title"], item["publisher"])
                row = self._conn.execute("SELECT symbols FROM articles WHERE id = ?", (aid,)).fetchone()
                symbols = sorted({*(item.get("symbols") or ()), *(json.loads(row["symbols"]) if row else ())})
                if row:
                    self._conn.execute("UPDATE articles SET symbols = ? WHERE id = ?", (json.dumps(symbols), aid))
                    continue
                new += 1
                self._conn.execute(
                    "INSERT INTO articles (id, url, alt_url, title, publisher, published, summary, "
                    "symbols, thumbnail, source, collected) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (aid, item["url"], item.get("alt_url") or "", item["title"], item["publisher"],
                     item["published"], item.get("summary") or "", json.dumps(symbols),
                     item.get("thumbnail") or "", item.get("source") or "unknown", _now()),
                )
        return new

    @_locked
    def list(
        self,
        *,
        hours: float | None = None,
        symbols: Iterable[str] = (),
        query: str = "",
        ids: Iterable[str] = (),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Newest first. No body -- a list of 200 stories does not carry 200 articles."""
        where, args = [], []
        if hours:
            where.append("published >= ?")
            args.append((datetime.now(UTC) - timedelta(hours=float(hours))).isoformat(timespec="seconds"))
        wanted = [s.strip().upper() for s in symbols if s and s.strip()]
        if wanted:
            where.append("(" + " OR ".join("symbols LIKE ?" for _ in wanted) + ")")
            args += [f'%"{s}"%' for s in wanted]
        for word in query.split():
            where.append("(title LIKE ? OR summary LIKE ?)")
            args += [f"%{word}%", f"%{word}%"]
        ids = list(ids)
        if ids:
            where.append(f"id IN ({','.join('?' for _ in ids)})")
            args += ids
        sql = f"SELECT {_LIST_COLUMNS} FROM articles"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY published DESC LIMIT ?"
        rows = self._conn.execute(sql, (*args, int(limit))).fetchall()
        return [self._row(r) for r in rows]

    @_locked
    def get(self, aid: str) -> dict[str, Any] | None:
        row = self._conn.execute(f"SELECT {_LIST_COLUMNS}, body, analysis FROM articles WHERE id = ?", (aid,)).fetchone()
        return self._row(row) if row else None

    @_locked
    def set_body(self, aid: str, body: str) -> None:
        with self._conn:
            self._conn.execute("UPDATE articles SET body = ?, body_at = ? WHERE id = ?", (body, _now(), aid))

    @_locked
    def set_analysis(self, aid: str, analysis: dict[str, Any]) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE articles SET analysis = ?, analysis_at = ? WHERE id = ?",
                (json.dumps(analysis), _now(), aid),
            )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["symbols"] = json.loads(out["symbols"])
        if "analysis" in out:
            out["analysis"] = json.loads(out["analysis"]) if out["analysis"] else None
        return out

    # -- briefs ------------------------------------------------------------

    # -- econ calendar -----------------------------------------------------

    @_locked
    def add_events(self, items: Iterable[dict[str, Any]]) -> int:
        """Upsert calendar rows. Returns how many were new.

        A revision (the time moves, a forecast appears) overwrites: the calendar
        is a statement about the future, and two rows for one print is how a
        countdown ends up naming a time that was corrected days ago.
        """
        new = 0
        with self._conn:
            for item in items:
                row = self._conn.execute("SELECT id FROM econ_events WHERE id = ?", (item["id"],)).fetchone()
                new += 0 if row else 1
                self._conn.execute(
                    "INSERT INTO econ_events (id, at, country, title, impact, forecast, previous, all_day, fetched) "
                    "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "at=excluded.at, impact=excluded.impact, forecast=excluded.forecast, "
                    "previous=excluded.previous, all_day=excluded.all_day, fetched=excluded.fetched",
                    (item["id"], item["at"], item["country"], item["title"], item["impact"],
                     item.get("forecast") or "", item.get("previous") or "",
                     int(bool(item.get("all_day"))), _now()),
                )
        return new

    @_locked
    def events(
        self,
        *,
        since: str | None = None,
        impacts: Iterable[str] = (),
        countries: Iterable[str] = (),
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Soonest first — this table is read forwards, unlike every other one here."""
        where, args = [], []
        if since:
            where.append("at >= ?")
            args.append(since)
        for column, values in (("impact", impacts), ("country", countries)):
            wanted = [str(v).strip() for v in values if str(v).strip()]
            if wanted:
                where.append(f"{column} IN ({','.join('?' for _ in wanted)})")
                args += wanted
        sql = "SELECT * FROM econ_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY at ASC LIMIT ?"
        rows = self._conn.execute(sql, (*args, int(limit))).fetchall()
        return [{**dict(r), "all_day": bool(r["all_day"])} for r in rows]

    @_locked
    def events_fetched_at(self) -> str | None:
        """When the calendar was last pulled. Drives the staleness guard in ``econ.refresh``."""
        return self._conn.execute("SELECT MAX(fetched) FROM econ_events").fetchone()[0]

    @_locked
    def add_brief(self, *, title: str, hours: float, requested_by: str, body: dict[str, Any]) -> str:
        bid = f"brf_{secrets.token_hex(6)}"
        with self._conn:
            self._conn.execute(
                "INSERT INTO briefs (id, created, title, hours, requested_by, body) VALUES (?,?,?,?,?,?)",
                (bid, _now(), title, float(hours), requested_by, json.dumps(body)),
            )
        return bid

    @_locked
    def briefs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, created, title, hours, requested_by FROM briefs ORDER BY created DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def brief(self, bid: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM briefs WHERE id = ?", (bid,)).fetchone()
        if not row:
            return None
        return {**dict(row), "body": json.loads(row["body"])}

    # -- the collector's log -----------------------------------------------

    @_locked
    def log_collection(self, *, ok: bool, sources: int, fetched: int, new: int, detail: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO collections (at, ok, sources, fetched, new, detail) VALUES (?,?,?,?,?,?)",
                (_now(), int(ok), sources, fetched, new, detail[:2000]),
            )
            # ponytail: keeps the last 500 runs; nothing reads further back.
            self._conn.execute(
                "DELETE FROM collections WHERE rowid NOT IN "
                "(SELECT rowid FROM collections ORDER BY at DESC LIMIT 500)"
            )

    @_locked
    def status(self) -> dict[str, Any]:
        last = self._conn.execute("SELECT * FROM collections ORDER BY at DESC LIMIT 1").fetchone()
        last_ok = self._conn.execute("SELECT at FROM collections WHERE ok = 1 ORDER BY at DESC LIMIT 1").fetchone()
        day = (datetime.now(UTC) - timedelta(hours=24)).isoformat(timespec="seconds")
        return {
            "articles": self._conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
            "last_24h": self._conn.execute("SELECT COUNT(*) FROM articles WHERE published >= ?", (day,)).fetchone()[0],
            "newest": (self._conn.execute("SELECT MAX(published) FROM articles").fetchone()[0]),
            "last_run": {**dict(last), "ok": bool(last["ok"])} if last else None,
            "last_ok_at": last_ok["at"] if last_ok else None,
        }


def demo() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = NewsStore(Path(tmp) / "news.db")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        old = (datetime.now(UTC) - timedelta(days=3)).isoformat(timespec="seconds")
        story = {"url": "https://a.test/1", "title": "Fed holds", "publisher": "Wire",
                 "published": now, "symbols": ["SPY"], "source": "yfinance"}
        assert store.add([story]) == 1
        # Same story, other URL, other symbol: one row, both symbols.
        assert store.add([{**story, "url": "https://b.test/1", "symbols": ["TLT"]}]) == 0
        assert store.add([{**story, "title": "Old news", "published": old, "symbols": ["NVDA"]}]) == 1
        rows = store.list(hours=24)
        assert [r["title"] for r in rows] == ["Fed holds"] and rows[0]["symbols"] == ["SPY", "TLT"]
        assert [r["title"] for r in store.list(symbols=["nvda"])] == ["Old news"]
        assert [r["title"] for r in store.list(query="fed")] == ["Fed holds"]
        aid = rows[0]["id"]
        store.set_analysis(aid, {"summary": "held"})
        assert store.get(aid)["analysis"] == {"summary": "held"}
        bid = store.add_brief(title="Weekend", hours=64, requested_by="operator", body={"overview": "x"})
        assert store.brief(bid)["body"] == {"overview": "x"}
        assert store.status()["last_run"] is None
        store.log_collection(ok=True, sources=2, fetched=10, new=2, detail="")
        assert store.status()["last_run"]["new"] == 2 and store.status()["articles"] == 2
        soon = (datetime.now(UTC) + timedelta(hours=2)).isoformat(timespec="seconds")
        event = {"id": "e1", "at": soon, "country": "USD", "title": "CPI m/m",
                 "impact": "High", "forecast": "0.2%", "previous": "0.3%"}
        assert store.add_events([event]) == 1
        # A revised forecast is the same print, not a second one.
        assert store.add_events([{**event, "forecast": "0.4%"}]) == 0
        upcoming = store.events(since=now, impacts=["High"], countries=["USD"])
        assert len(upcoming) == 1 and upcoming[0]["forecast"] == "0.4%"
        assert store.events(since=now, impacts=["Low"]) == []
        assert store.events_fetched_at() is not None
        store.close()
    print("news store: ok")


if __name__ == "__main__":
    demo()
