# Spec: Genesis Markdown/70-Schemas/Watchlist Store.md
"""The watchlist store and its routes -- lists, sections, and the tier-3 quote.

The store's own arithmetic is checked in its ``__main__``; this is the HTTP
round trip and the one property that matters for [[Safety Invariants]]: a
watchlist edit writes the trader's own file and reaches no order path.
"""

from __future__ import annotations

import pytest

from genesis.watchlist.store import WatchlistStore


def test_sections_and_idempotent_add(tmp_path):
    s = WatchlistStore(tmp_path / "wl.db")
    a = s.create("Semis")
    s.add(a, "nvda")
    s.add(a, "amd", group="laggards")
    s.add(a, "NVDA", group="leaders")  # same symbol -> regroup, not duplicate
    (lst,) = s.lists()
    assert [m["symbol"] for m in lst["members"]] == ["NVDA", "AMD"]
    assert lst["members"][0]["group"] == "leaders"


def test_a_bad_ticker_is_refused_not_repaired(tmp_path):
    s = WatchlistStore(tmp_path / "wl.db")
    a = s.create("x")
    with pytest.raises(Exception, match="ticker"):
        s.add(a, "not real!!")


def test_routes_round_trip(monkeypatch, tmp_path):
    starlette_testclient = pytest.importorskip("starlette.testclient")
    from genesis.server.app import EventBus, build_app
    from genesis.server import watchlist_routes as mod

    monkeypatch.setattr(mod, "_store", lambda: WatchlistStore(tmp_path / "wl.db"))

    with starlette_testclient.TestClient(build_app(EventBus())) as c:
        assert c.get("/v1/watchlists").json()["watchlists"] == []
        c.post("/v1/watchlists/new", json={"name": "Energy"})
        lid = c.get("/v1/watchlists").json()["watchlists"][0]["id"]
        c.post(f"/v1/watchlists/{lid}/add", json={"symbol": "xom", "group": "majors"})
        body = c.post(f"/v1/watchlists/{lid}/add", json={"symbol": "cvx"}).json()
        assert body["ok"] is True
        members = body["watchlists"][0]["members"]
        assert {m["symbol"] for m in members} == {"XOM", "CVX"}

        bad = c.post(f"/v1/watchlists/{lid}/add", json={"symbol": "@@@"})
        assert bad.status_code == 400 and bad.json()["ok"] is False

        c.post(f"/v1/watchlists/{lid}/remove", json={"symbol": "xom"})
        c.post(f"/v1/watchlists/{lid}/delete", json={})
        assert c.get("/v1/watchlists").json()["watchlists"] == []


def _fake_yfinance(monkeypatch, frame):
    """Stand in for the vendor with a real DataFrame -- the shape `_one` parses."""
    import sys

    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        type("M", (), {
            "Ticker": staticmethod(
                lambda s: type("T", (), {"history": lambda self, **kw: frame})()
            )
        }),
    )


def test_the_change_is_the_last_close_against_the_one_before(monkeypatch):
    """The sign of every row depends on which end of the frame is "latest".

    ``history`` returns bars oldest-first. Reading the wrong end flips the sign
    of every percentage on the panel and dates the list to the wrong session --
    a wrong answer that looks entirely plausible, which is why it is pinned
    rather than left to the eye. The double is a real ``DataFrame`` with a real
    ``DatetimeIndex``, because the ordering is the thing under test.
    """
    pd = pytest.importorskip("pandas")
    from genesis.marketdata import quotes as q

    frame = pd.DataFrame(
        {"Close": [100.0, 110.0]},
        index=pd.to_datetime(["2026-09-03", "2026-09-04"]),
    )
    _fake_yfinance(monkeypatch, frame)
    q._CACHE.clear()

    got = q.day_quotes(["NVDA"])["NVDA"]
    assert got["close"] == 110.0, f"read the wrong end of the frame: {got}"
    assert got["prev_close"] == 100.0
    assert got["change"] == 10.0
    assert got["change_pct"] == 10.0
    assert got["as_of"] == "2026-09-04"


def test_a_single_close_is_absence_not_a_zero_change(monkeypatch):
    """One bar cannot produce a day change, and must not be rendered as flat."""
    pd = pytest.importorskip("pandas")
    from genesis.marketdata import quotes as q

    frame = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2026-09-04"]))
    _fake_yfinance(monkeypatch, frame)
    q._CACHE.clear()

    assert "error" in q.day_quotes(["NEWIPO"])["NEWIPO"]


def test_quotes_route_is_labelled_tier_3(monkeypatch, tmp_path):
    starlette_testclient = pytest.importorskip("starlette.testclient")
    from genesis.server.app import EventBus, build_app
    from genesis.marketdata import quotes as q

    # The cache is module-level and time-bucketed, so a symbol another test
    # already asked for would answer from it and skip `_one` entirely.
    q._CACHE.clear()
    monkeypatch.setattr(q, "_one", lambda sym: {"close": 1.0, "prev_close": 2.0,
                                                "change": -1.0, "change_pct": -50.0,
                                                "as_of": "2026-09-04"})
    with starlette_testclient.TestClient(build_app(EventBus())) as c:
        body = c.get("/v1/market/quotes?symbols=NVDA,AAPL").json()
    assert body["tier"] == 3
    assert body["quotes"]["NVDA"]["change_pct"] == -50.0
