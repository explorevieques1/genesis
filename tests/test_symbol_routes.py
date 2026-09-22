# Spec: Genesis Markdown/10-Architecture/Charting Engine.md §Symbol search
"""IBKR contracts map to canonical ids deterministically, a futures root is
expanded into dated contracts rather than guessed, and load refuses a write
without a JSON content type."""

from __future__ import annotations

from types import SimpleNamespace as NS

from genesis.server import symbol_routes as sr


def test_contracts_map_to_canonical_ids() -> None:
    assert sr.symbol_id_for("STK", "NVDA", "NASDAQ") == "EQ:XNAS:NVDA"
    assert sr.symbol_id_for("STK", "VOD", "LSE") == "EQ:LSE:VOD"
    assert sr.symbol_id_for("IND", "SPX", "CBOE") == "IDX:CBOE:SPX"
    assert sr.symbol_id_for("CASH", "EUR", "IDEALPRO", currency="USD") == "FX:IDEALPRO:EURUSD"
    assert sr.symbol_id_for("CRYPTO", "BTC", "PAXOS") == "CRYPTO:PAXOS:BTC"
    assert sr.symbol_id_for("FUT", "NQ", "CME", contract_month="20261218") == "FUT:CME:NQ:2026-12"
    assert sr.symbol_id_for("FUT", "NQ", "CME") is None  # a family, not an instrument
    assert sr.symbol_id_for("OPT", "NVDA", "SMART") is None


def test_search_lists_matches_and_dated_futures(monkeypatch) -> None:
    def contract(**kw):
        base = dict(secType="", symbol="", primaryExchange="", exchange="", currency="USD",
                    description="", localSymbol="", lastTradeDateOrContractMonth="")
        return NS(**{**base, **kw})

    class FakeIB:
        def reqMatchingSymbols(self, q):
            return [
                NS(contract=contract(secType="IND", symbol="NQ", primaryExchange="CME", description="E-mini Nasdaq"),
                   derivativeSecTypes=["FUT", "OPT"]),
                NS(contract=contract(secType="STK", symbol="NQ", primaryExchange="LSE", currency="GBP"),
                   derivativeSecTypes=[]),
            ]

        def reqContractDetails(self, c):
            return [
                NS(contract=contract(symbol="NQ", exchange="CME", localSymbol="NQH9",
                                     lastTradeDateOrContractMonth="20290316"), contractMonth="202903", longName=""),
                NS(contract=contract(symbol="NQ", exchange="CME", localSymbol="NQZ0",
                                     lastTradeDateOrContractMonth="20001215"), contractMonth="200012", longName=""),
            ]

    monkeypatch.setattr(sr, "_ib", FakeIB)
    monkeypatch.setattr(sr, "_CACHE", {})
    ids = [r["symbol_id"] for r in sr.search("nq")]
    assert ids == ["IDX:CME:NQ", "EQ:LSE:NQ", "FUT:CME:NQ:2029-03"]  # expired month dropped


def test_load_without_json_content_type_is_refused() -> None:
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    client = TestClient(Starlette(routes=sr.symbol_routes()))
    r = client.post("/v1/market/load", content='{"symbol_id":"NVDA"}', headers={"content-type": "text/plain"})
    assert r.status_code == 415
