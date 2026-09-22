# Spec: Genesis Markdown/40-Memory/Research Directory.md
"""Findings: every sub-task a prompt fanned out into, remembered by (company, intent).

*"Analyse Adobe's earnings -- has the price drifted from fair value?"* is one
sentence and several pieces of work. The planner already splits it into typed
tasks (``research.company``, ``company.earnings``, ...). Until now the pieces
were spoken once and dropped. A finding keeps each one: subject key
``"ADBE:research.company"``, the prompt's ``trace_id``, the agent's own
summary, a bounded copy of its data and a reference to any note it wrote.

The research directory already had everything a finding needs -- supersede per
subject, half-life, graph projection, vault mirror -- so a finding is a note
kind, not a new store. One current finding per intent per company; the older
reads stay as history, which is where "what changed since last time" comes from.

Everything in this module is **reflex**. Which company a task was about is a
deterministic lookup, whether a stored read is fresh enough is arithmetic, and
neither is ever asked of a model (Biological Design, reflex arc).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from genesis.company.resolve import resolve_subject, subjects_in
from genesis.research.schema import ResearchNote
from genesis.research.store import ResearchStore

__all__ = [
    "REUSE_MAX_HOURS",
    "asks_for_fresh",
    "fresh_enough",
    "previous",
    "recall",
    "record",
    "reusable",
    "symbol_of",
]

#: How old a stored read may be and still answer a repeat question, whatever
#: its half-life. A fundamental note stays worth *reading* for two months, but
#: "has the price drifted from fair value" has a different answer tomorrow.
REUSE_MAX_HOURS = 24.0

#: Used when the task wrote no note that carries a half-life of its own.
DEFAULT_HALF_LIFE_HOURS = 24.0

#: A finding keeps the agent's data only up to this size. Past it the finding
#: keeps the reference and drops the rows -- a 40-row screen is the screener's
#: store's business, not a copy in every finding.
MAX_DATA_CHARS = 4000

#: The operator's way past reuse, typed or spoken: "refresh Adobe fair value".
_FRESH = re.compile(r"(?:^|\s)--fresh\b|\b(?:refresh|re-?run|again|fresh(?: look| read| run)?)\b", re.I)

_SUBJECT_KEYS = ("symbol", "ticker", "subject", "company", "topic", "query")


def asks_for_fresh(utterance: str) -> bool:
    return bool(_FRESH.search(utterance or ""))


def symbol_of(args: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> str | None:
    """The one company a task's args are about, or None. Never guesses.

    Resolves only to a ticker in the snapshot: "Gann" stays a research subject
    and gets no finding (a ``ponytail:`` cut, below), and an ambiguous name
    gets none rather than the wrong company's. A planner-written phrase
    ("Adobe fundamental analysis, fair value") counts when it names exactly one
    company.
    """
    raw = next((args[k] for k in _SUBJECT_KEYS if isinstance(args.get(k), str) and args[k].strip()), None)
    if raw is None and isinstance(args.get("symbols"), list) and len(args["symbols"]) == 1:
        raw = str(args["symbols"][0])
    if raw is None:
        return None
    if rows is None:
        from genesis.screener.snapshot import load_snapshot

        rows = load_snapshot().rows
    try:
        ticker, _ = resolve_subject(raw, rows)
    except Exception:  # noqa: BLE001 - ambiguous or unusable: try the phrase instead
        ticker = None
    if ticker is not None and any(r.get("symbol") == ticker for r in rows):
        return ticker
    # ponytail: S&P 500 tickers only; topic subjects ("Gann") get findings when
    # non-company prompts need recall.
    named = subjects_in(raw, rows)
    return named[0] if len(named) == 1 else None


def record(store: ResearchStore, task: Any, *, rows: list[dict[str, Any]] | None = None) -> ResearchNote | None:
    """Store one finished bus task as a finding. Idempotent on the task id.

    ``task`` is a bus :class:`~genesis.bus.task.Task` in ``DONE`` state. Tasks
    about no resolvable company are skipped.
    """
    result = task.result or {}
    symbol = symbol_of(task.args or {}, rows)
    if symbol is None:
        return None

    evidence = [w["note"] for w in result.get("wrote", []) if isinstance(w, dict) and w.get("note")]
    half_life = DEFAULT_HALF_LIFE_HOURS
    if evidence and (written := store.note(str(evidence[0]))) is not None:
        half_life = written.half_life_hours

    data = result.get("data") or {}
    encoded = json.dumps(data, default=str)
    kept = data if len(encoded) <= MAX_DATA_CHARS else {"omitted": f"{len(encoded)} chars — see evidence"}
    degraded = bool(result.get("degraded"))
    summary = str(result.get("spoken_summary") or "").strip()

    note = ResearchNote(
        id=f"res_fnd_{task.id}",
        kind="finding",
        subject=f"{symbol}:{task.type}",
        title=f"{symbol} — {task.type}",
        created_by=task.agent,
        summary=summary[:600],
        data={"symbol": symbol, "intent": task.type, "args": task.args,
              "result": kept, "evidence": evidence},
        tags=("finding", task.type),
        half_life_hours=half_life,
        confidence=0.5,
        degraded=degraded,
        caveats=("the agent reported this result as degraded",) if degraded else (),
        trace_id=task.trace_id or None,
    )
    return store.put(note)


def reusable(
    store: ResearchStore, intent: str, symbol: str, *, now: datetime | None = None
) -> ResearchNote | None:
    """The stored finding that may answer this task instead of running it.

    Fresh means inside both its own half-life and :data:`REUSE_MAX_HOURS`.
    A degraded finding, or one with nothing to say, is never reused -- rerunning
    is exactly what a degraded read is asking for.
    """
    note = store.current("finding", f"{symbol}:{intent}")
    return note if note is not None and fresh_enough(note, now=now) else None


def fresh_enough(note: ResearchNote, *, now: datetime | None = None) -> bool:
    """May this stored read answer a repeat question? Any note kind."""
    if note.degraded or not note.summary:
        return False
    now = now or datetime.now(UTC)
    age = (now - note.created).total_seconds() / 3600.0
    return age <= min(note.half_life_hours, REUSE_MAX_HOURS)


def previous(store: ResearchStore, note: ResearchNote) -> ResearchNote | None:
    """The read this finding superseded -- what "last time" means."""
    older = [n for n in store.history(note.kind, note.subject) if n.id != note.id]
    return older[0] if older else None


def recall(
    store: ResearchStore, text: str, *, rows: list[dict[str, Any]] | None = None,
    now: datetime | None = None, limit: int = 12,
) -> str:
    """What Genesis already knows about the companies a sentence names.

    Handed to the planner as context, one line per finding, grouped by company.
    Stale lines are included and marked: knowing that a read exists and is old
    is itself worth planning around.
    """
    now = now or datetime.now(UTC)
    lines: list[str] = []
    for symbol in subjects_in(text, rows):
        for note in store.findings(symbol):
            fresh = reusable(store, str(note.data.get("intent")), symbol, now=now) is not None
            lines.append(
                f"- {note.subject} as of {note.created:%Y-%m-%d %H:%M} UTC "
                f"({'fresh' if fresh else 'stale'}): {note.summary[:200]}"
            )
    return "\n".join(lines[:limit])


def demo() -> None:
    import tempfile
    from datetime import timedelta
    from types import SimpleNamespace

    rows = [{"symbol": "ADBE", "name": "Adobe Inc."}]
    with tempfile.TemporaryDirectory() as tmp:
        store = ResearchStore(path=f"{tmp}/r.db", vault=None, graph=None)
        task = SimpleNamespace(id="tsk_1", type="company.valuation", agent="fundamental",
                               args={"subject": "Adobe"}, trace_id="tr_1",
                               result={"spoken_summary": "Adobe trades 12% under fair value.",
                                       "data": {"gap": -0.12}})
        note = record(store, task, rows=rows)
        assert note is not None and note.subject == "ADBE:company.valuation"
        record(store, task, rows=rows)  # idempotent: same id, no self-supersede
        assert len(store.history("finding", note.subject)) == 1
        assert reusable(store, "company.valuation", "ADBE") is not None
        later = datetime.now(UTC) + timedelta(hours=REUSE_MAX_HOURS + 1)
        assert reusable(store, "company.valuation", "ADBE", now=later) is None
        assert "ADBE:company.valuation" in recall(store, "what about Adobe?", rows=rows)
        assert store.by_trace("tr_1")[0].id == note.id
        assert asks_for_fresh("refresh Adobe") and not asks_for_fresh("analyse Adobe")
        assert symbol_of({"topic": "Adobe fundamental analysis, fair value"}, rows) == "ADBE"
        assert symbol_of({"topic": "W.D. Gann"}, rows) is None


if __name__ == "__main__":
    demo()
    print("ok")
