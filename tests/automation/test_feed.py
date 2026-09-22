# Spec: Genesis Markdown/60-UI/Feed.md
"""The feed is derived: what a run recorded decides what the trader sees."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from genesis.automation.feed import feed, items_from_run

NOW = datetime(2026, 9, 15, 20, 30, tzinfo=UTC)


def run(run_id: str, at: datetime, *outputs: dict, status: str = "ok") -> dict:
    return {
        "run_id": run_id, "workflow_id": "daily-movers", "version": 1,
        "started_at": at.isoformat(timespec="seconds"), "status": status,
        "steps": [{"step": f"s{i}", "status": "ok", "output": o} for i, o in enumerate(outputs)],
    }


def test_a_run_that_produced_nothing_is_not_news() -> None:
    quiet = run("r1", NOW, {"text": "not pre-market", "structured": {"stopped": True}})
    assert items_from_run(quiet, "Daily movers") is None


def test_artifacts_come_from_what_the_steps_returned() -> None:
    item = items_from_run(run(
        "r2", NOW,
        {"text": "brief written", "structured": {"brief": "br_1", "title": "Daily movers — 2026-09-15"}},
        {"text": "wrote to Daily Movers/2026-09-15", "structured": {"path": "Daily Movers/2026-09-15.md"}},
        {"text": "journalled", "structured": {"observation": "obs_1"}},
        {"text": "alert: sent", "structured": {"alert": "al_1", "title": "Daily movers — ZBH, CCI",
                                               "message": "ZBH +2.4%"}},
    ), "Daily movers")

    assert item is not None
    assert [a["kind"] for a in item["artifacts"]] == ["brief", "note", "observation"]
    # Each artifact names the module that opens it -- that is the click target.
    assert {a["module"] for a in item["artifacts"]} == {"news", "notebook", "journal-entries"}
    # An alert on the run titles the item; the workflow name is only the fallback.
    assert item["title"] == "Daily movers — ZBH, CCI"
    assert item["summary"] == "ZBH +2.4%"


def test_a_suppressed_alert_is_not_an_item() -> None:
    cooled = run("r3", NOW, {"text": "alert suppressed", "structured": {"suppressed": True}})
    assert items_from_run(cooled, "Daily movers") is None


def test_new_is_recency_and_order_is_newest_first() -> None:
    class Store:
        def list(self) -> list:
            return []

        def recent_runs(self, *, limit: int) -> list[dict]:
            return [run("fresh", NOW - timedelta(hours=2), {"structured": {"path": "a.md"}}),
                    run("stale", NOW - timedelta(hours=40), {"structured": {"path": "b.md"}})][:limit]

    out = feed(Store(), limit=10, now=NOW)
    assert [i["id"] for i in out["items"]] == ["fresh", "stale"]
    assert [i["new"] for i in out["items"]] == [True, False]
    assert out["new"] == 1
    # No workflow saved under that id: the feed falls back to the id, never crashes.
    assert out["items"][0]["workflow"]["name"] == "daily-movers"
