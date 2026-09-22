# Spec: Genesis Markdown/60-UI/Economic Calendar.md
"""The red-folder calendar: when the high-impact prints land. Deterministic, tier none.

**Afferent only.** One GET per week-file, parse, upsert, done. Nothing here
reads a model or reaches a broker, and nothing acts on an event -- the trader
does. It is a clock with names on it.

**The impact rating is the whole point.** ForexFactory's weekly JSON carries
``impact`` per event (``High`` is the red folder), which is what the free
alternatives -- FRED release dates, the Fed's own schedule, the BLS calendar --
do not: with those you get dates and hand-maintain the "which of these matters"
list yourself. So the rating comes from the vendor, and a wrong one is a wrong
row rather than a wrong judgement of ours.

**Tier 3, and the panel says so.** This is a third party's schedule with no
provenance line. It informs a person; it is never an input to sizing or a stop,
and no risk check may read this table (`Safety Invariants`).

**One rolling week is the horizon** -- ``thisweek`` is the only file published
(``nextweek`` and the rest 404), so on a Friday you can see through Sunday and
no further. Old rows are kept rather than pruned, so the table grows backwards
into a record of what printed and what was forecast.
ponytail: one week; if the horizon has to reach further, the upgrade is the
Fed/BLS published schedules for the handful of prints that are known months
out, not a second vendor.

Times are revised upstream, which is why rows are replaced in place rather than
appended: see ``NewsStore.add_events``.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from genesis.news.store import NewsStore

__all__ = ["COUNTRIES", "FEEDS", "IMPACTS", "STALE_HOURS", "next_event", "parse", "refresh", "upcoming"]

log = logging.getLogger(__name__)

#: The one file the vendor publishes. Mon-Sun, rolling, revised in place.
FEEDS: tuple[str, ...] = ("https://nfs.faireconomy.media/ff_calendar_thisweek.json",)
#: Vendor's own spelling. ``High`` is the red folder.
IMPACTS: tuple[str, ...] = ("High", "Medium", "Low", "Holiday")
#: The default filter. A US equities desk is not woken at 02:00 for an AUD print;
#: the route takes ``countries`` for anyone who wants the rest.
COUNTRIES: tuple[str, ...] = ("USD",)
#: How old the stored calendar may get before a collector run re-pulls it. A
#: schedule two weeks long does not need a 15-minute refresh.
STALE_HOURS = 6.0

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def event_id(at: str, country: str, title: str) -> str:
    """Identity is *what prints, where, when* -- not the row's position in the file."""
    key = f"{at}|{country.upper()}|{' '.join(title.lower().split())}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def parse(entry: Any) -> dict[str, Any] | None:
    """One feed row, or ``None`` if it is not a dated event we can place on a clock.

    The feed's ``date`` carries a real UTC offset (``-04:00`` in EDT), so the
    conversion is a conversion and not an assumption about which timezone the
    vendor meant. Midnight is the feed's stand-in for all-day and tentative
    entries, flagged rather than shown as a 00:00 print.
    """
    if not isinstance(entry, dict):
        return None
    title = str(entry.get("title") or "").strip()
    country = str(entry.get("country") or "").strip().upper()
    impact = str(entry.get("impact") or "").strip().title()
    if not title or not country or impact not in IMPACTS:
        return None
    try:
        when = datetime.fromisoformat(str(entry.get("date") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    local = when.timetuple()
    at = when.astimezone(UTC).isoformat(timespec="seconds")
    return {
        "id": event_id(at, country, title),
        "at": at,
        "country": country,
        "title": title,
        "impact": impact,
        "forecast": str(entry.get("forecast") or "").strip(),
        "previous": str(entry.get("previous") or "").strip(),
        "all_day": local.tm_hour == 0 and local.tm_min == 0,
    }


def fetch(url: str, *, timeout: float = 15.0) -> list[Any]:
    import httpx

    response = httpx.get(url, headers=_UA, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def refresh(store: NewsStore, *, force: bool = False) -> dict[str, Any]:
    """Pull both week-files and upsert. Skips silently if the stored calendar is fresh.

    Never raises: a vendor that is down costs the countdown its data, and the
    right failure for that is an empty panel that says when it last succeeded,
    not a collector run that dies on the way past.
    """
    fetched_at = store.events_fetched_at()
    if not force and fetched_at:
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(fetched_at)
            if age < timedelta(hours=STALE_HOURS):
                return {"ok": True, "skipped": True, "events": 0, "new": 0, "errors": []}
        except ValueError:
            pass

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in FEEDS:
        try:
            items.extend(p for p in (parse(e) for e in fetch(url)) if p)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url.rsplit('/', 1)[-1]}: {type(exc).__name__}: {exc}"[:200])
    new = store.add_events(items) if items else 0
    return {"ok": bool(items), "skipped": False, "events": len(items), "new": new, "errors": errors}


def upcoming(
    store: NewsStore,
    *,
    impacts: Iterable[str] = ("High",),
    countries: Iterable[str] = COUNTRIES,
    limit: int = 100,
    grace_min: float = 15.0,
) -> list[dict[str, Any]]:
    """What has not happened yet, soonest first.

    A print stays on the list for ``grace_min`` after its time: the number you
    are waiting for is most interesting in the minute *after* it lands, and a
    row that vanishes at the bell takes the context with it.
    """
    since = (datetime.now(UTC) - timedelta(minutes=grace_min)).isoformat(timespec="seconds")
    return store.events(since=since, impacts=impacts, countries=countries, limit=limit)


def next_event(store: NewsStore, **kwargs: Any) -> dict[str, Any] | None:
    """The one the countdown names. Timed events only -- an all-day row has no clock."""
    for row in upcoming(store, limit=50, **kwargs):
        if not row["all_day"]:
            return row
    return None


def demo() -> None:
    import tempfile
    from pathlib import Path

    row = {"title": "CPI m/m", "country": "usd", "date": "2026-09-14T08:30:00-04:00",
           "impact": "High", "forecast": "0.2%", "previous": "0.3%"}
    item = parse(row)
    assert item and item["at"] == "2026-09-14T12:30:00+00:00" and item["country"] == "USD"
    assert item["all_day"] is False and item["impact"] == "High"
    # Midnight in the feed's own timezone is all-day, not a 00:00 print -- and
    # it must not be read as midnight UTC, which would be a different day.
    holiday = parse({**row, "title": "Bank Holiday", "date": "2026-09-14T00:00:00-04:00", "impact": "holiday"})
    assert holiday and holiday["all_day"] is True and holiday["impact"] == "Holiday"
    assert parse({**row, "impact": "Nonsense"}) is None
    assert parse({**row, "date": "not a date"}) is None
    assert parse({**row, "date": "2026-09-14T08:30:00"}) is None  # no offset: unplaceable
    assert parse("nope") is None

    with tempfile.TemporaryDirectory() as tmp:
        store = NewsStore(Path(tmp) / "news.db")
        # Pinned to a wall-clock hour so "midnight is all-day" cannot fire by luck.
        now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
        store.add_events([
            {**parse({**row, "date": (now + timedelta(hours=3)).isoformat()}), "title": "CPI m/m"},
            {"id": "past", "at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
             "country": "USD", "title": "Old print", "impact": "High"},
            {"id": "allday", "at": (now + timedelta(hours=1)).isoformat(timespec="seconds"),
             "country": "USD", "title": "Holiday", "impact": "High", "all_day": True},
            {"id": "eur", "at": (now + timedelta(hours=2)).isoformat(timespec="seconds"),
             "country": "EUR", "title": "ECB", "impact": "High"},
        ])
        titles = [e["title"] for e in upcoming(store)]
        assert titles == ["Holiday", "CPI m/m"], titles
        assert next_event(store)["title"] == "CPI m/m"
        assert [e["country"] for e in upcoming(store, countries=("USD", "EUR"))].count("EUR") == 1
        # Fresh calendar: a second refresh does not hit the network.
        assert refresh(store)["skipped"] is True
        store.close()
    print("econ calendar: ok")


if __name__ == "__main__":
    demo()
