# Spec: Genesis Markdown/60-UI/Feed.md
"""What the automations have produced lately, newest first.

**The feed stores nothing.** A run already records every step's output, and a
step that wrote something says so in its own output -- ``output.note`` returns
the note path, ``news.brief`` returns the brief id, ``journal.observe`` returns
the observation id. So "what has Genesis produced" is a *view* over the run log,
not a second table that could disagree with it. Nothing here writes.

**A run without an artifact is not news.** A gate that stopped the chain because
it was not pre-market did its job; it is in ``CD``'s run history and does not
belong in front of a person. Only runs that left something durable -- a note, a
brief, an observation, an alert -- become feed items.

**New is recency, not state.** An item from the last ``NEW_HOURS`` is new. There
is no seen-marker to drift out of step with what was actually read.
ponytail: if that nags, a seen-at row in ``meta`` is the upgrade.

Tier none. Reading a log and matching keys is not a judgement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = ["NEW_HOURS", "feed", "items_from_run"]

NEW_HOURS = 24

#: Output key -> (artifact kind, the module that opens it). The contract between
#: an action that writes and the feed that offers the way in: an action grows a
#: destination by returning its id, not by teaching the feed about itself.
_ARTIFACTS: dict[str, tuple[str, str]] = {
    "path": ("note", "notebook"),
    "brief": ("brief", "news"),
    "observation": ("observation", "journal-entries"),
}


def items_from_run(run: dict[str, Any], workflow_name: str) -> dict[str, Any] | None:
    """One feed item, or ``None`` when the run produced nothing to look at."""
    artifacts: list[dict[str, Any]] = []
    alert: dict[str, Any] | None = None
    last_text = ""
    for record in run.get("steps") or []:
        output = record.get("output") or {}
        structured = output.get("structured")
        if not isinstance(structured, dict):
            continue
        if structured.get("suppressed"):
            continue
        for key, (kind, module) in _ARTIFACTS.items():
            target = structured.get(key)
            if isinstance(target, str) and target:
                artifacts.append({"kind": kind, "module": module, "target": target,
                                  "label": structured.get("title") or target})
        if structured.get("alert"):
            alert = structured
        if output.get("text"):
            last_text = str(output["text"])

    if not artifacts and not alert:
        return None
    return {
        "id": run["run_id"],
        "at": run["started_at"],
        "workflow": {"id": run["workflow_id"], "name": workflow_name, "version": run["version"]},
        "status": run["status"],
        "title": (alert or {}).get("title") or workflow_name,
        "summary": ((alert or {}).get("message") or last_text)[:1000],
        "artifacts": artifacts,
    }


def feed(store: Any, *, limit: int = 50, now: datetime | None = None) -> dict[str, Any]:
    """``{items, new, as_of}`` -- the producing runs, newest first."""
    names = {v.workflow_id: v.workflow().name for v in store.list()}
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=NEW_HOURS)
    items = []
    # Runs outnumber producing runs, so read deeper than the page asked for.
    for run in store.recent_runs(limit=limit * 4):
        item = items_from_run(run, names.get(run["workflow_id"], run["workflow_id"]))
        if item is None:
            continue
        item["new"] = _parse(item["at"]) > cutoff
        items.append(item)
        if len(items) >= limit:
            break
    return {
        "items": items,
        "new": sum(i["new"] for i in items),
        "new_hours": NEW_HOURS,
        "as_of": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
    }


def _parse(at: str) -> datetime:
    parsed = datetime.fromisoformat(at)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
