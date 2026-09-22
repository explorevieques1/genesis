# Spec: Genesis Markdown/20-Agents/Research/Agent — Screener.md
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from genesis.commands import match_command
from genesis.screener.chat import history_from, respond
from genesis.screener.scan import ScanError, expression, parse_expression, run, validate
from genesis.screener.snapshot import Snapshot, build_snapshot, load_snapshot, row_from_info

NOW = datetime.now(UTC).isoformat(timespec="seconds")
ROWS = [
    {"symbol": "AAA", "name": "Cheap Tech", "sector": "Technology", "pe_forward": 12.0, "revenue_growth": 20.0, "market_cap_b": 50.0},
    {"symbol": "BBB", "name": "Pricey Tech", "sector": "Technology", "pe_forward": 40.0, "revenue_growth": 30.0, "market_cap_b": 900.0},
    {"symbol": "CCC", "name": "Loss Energy", "sector": "Energy", "revenue_growth": 5.0, "market_cap_b": 20.0},
]
SNAP = Snapshot(ROWS, NOW, [])
SAVED: list[dict] = []
#: Never touch the operator's real ~/.genesis store from a test.
ISOLATED = {"snapshot_fn": lambda: SNAP, "remember": SAVED.append, "recall": lambda: SAVED[-1] if SAVED else None}


def test_units_are_normalised_to_percent_and_billions() -> None:
    row = row_from_info("KO", {"shortName": "Coca-Cola", "profitMargins": 0.2856, "dividendYield": 2.4,
                               "marketCap": 384e9, "freeCashflow": 19.2e9, "trailingPE": None}, "Cons. Staples")
    assert row["margin_net"] == 28.56 and row["dividend_yield"] == 2.4
    assert row["market_cap_b"] == 384 and row["fcf_yield"] == 5.0
    assert "pe_trailing" not in row  # absent stays absent


def test_absent_never_passes_and_is_counted() -> None:
    out = run(validate({"criteria": [{"field": "pe_forward", "op": "<", "value": 15}]}), SNAP)
    assert [m["symbol"] for m in out["matches"]] == ["AAA"]
    assert out["missing"] == {"pe_forward": 1} and out["degraded"] is False


def test_typed_expression_builds_the_same_scan() -> None:
    raw = parse_expression("sector=technology revenue_growth>=20 sort:-market_cap_b top:1")
    out = run(validate(raw), SNAP)
    assert out["count"] == 2 and [m["symbol"] for m in out["matches"]] == ["BBB"]


def test_any_scan_round_trips_through_the_typed_grammar() -> None:
    scan = validate({"criteria": [{"field": "pe_forward", "op": "between", "value": [10, 20]},
                                  {"field": "sector", "op": "in", "value": ["Technology", "Health Care"]},
                                  {"field": "industry", "op": "contains", "value": "semi"}],
                     "sort": {"field": "roe", "direction": "asc"}, "limit": 10})
    assert validate(parse_expression(expression(scan))) == scan


def test_invented_fields_and_sectors_are_refused() -> None:
    with pytest.raises(ScanError) as exc:
        validate({"criteria": [{"field": "insider_buying", "op": ">", "value": 1},
                               {"field": "sector", "op": "=", "value": "Crypto"}]})
    assert len(exc.value.problems) == 2


def test_stale_snapshot_is_degraded() -> None:
    assert run(validate({"criteria": []}), Snapshot(ROWS, "2020-01-01T00:00:00+00:00", []))["degraded"]


def test_snapshot_keeps_the_old_table_when_the_fetch_mostly_fails(tmp_path) -> None:
    db = tmp_path / "s.db"
    info = {"quoteType": "EQUITY", "marketCap": 1e9}
    assert build_snapshot(db, members={"A": "Energy", "B": None}, fetch=lambda s: info)["ok"]

    def broken(symbol: str) -> dict:
        raise RuntimeError("yahoo down")

    assert not build_snapshot(db, members={"A": None, "B": None}, fetch=broken)["ok"]
    assert [r["symbol"] for r in load_snapshot(db).rows] == ["A", "B"]


class FakeModel:
    def __init__(self, *replies: dict) -> None:
        self.replies, self.prompts = list(replies), []

    def complete(self, prompt: str, **_: object) -> SimpleNamespace:
        self.prompts.append(prompt)
        return SimpleNamespace(text=json.dumps(self.replies.pop(0)))


def test_model_scan_is_repaired_once_then_run_with_readings_and_question() -> None:
    bad = {"intent": "screen", "scan": {"criteria": [{"field": "cheapness", "op": "<", "value": 1}]}}
    good = {"intent": "screen", "understood": "Cheap growing tech",
            "scan": {"criteria": [{"field": "pe_forward", "op": "<", "value": 15}]},
            "readings": [{"phrase": "cheap", "as": "pe_forward < 15", "why": "market multiple"}],
            "question": "Only Technology?", "choices": ["only Technology"]}
    model = FakeModel(bad, good)
    result = respond("find cheap stocks", [], backend_fn=lambda: model, **ISOLATED)
    assert result.ok and result.command == "screen.model"
    assert "REJECTED" in model.prompts[1]
    screen = json.loads(result.data["screen"])
    assert screen["count"] == 1 and screen["readings"][0]["phrase"] == "cheap"
    assert result.spoken.endswith("Only Technology?")


def test_follow_up_carries_the_previous_scan_and_not_screen_is_handed_back() -> None:
    first = respond("scr pe_forward<50", **ISOLATED)
    turns = [{"role": "operator", "text": "chart NVDA"}, {"role": "genesis", "text": "", "command": "chart"},
             {"role": "operator", "text": "scr pe_forward<50"},
             {"role": "genesis", "text": first.spoken, "command": first.command, "data": first.data}]
    history = history_from(turns)
    assert [h[0] for h in history] == ["scr pe_forward<50"]

    model = FakeModel({"intent": "not_screen"})
    SAVED.append({"scan": {"criteria": [{"field": "roe", "op": ">", "value": 20}]}})  # edited in SCR
    result = respond("only tech", history, backend_fn=lambda: model, **ISOLATED)
    assert '"pe_forward"' in model.prompts[0] and result.command == "screen.not_screen"
    assert "ON THE TRADER'S SCREEN NOW" in model.prompts[0] and '"roe"' in model.prompts[0]


def test_sentences_route_to_the_screen_command() -> None:
    for text in ("scr pe_trailing<20", "find me cheap tech stocks", "which companies have margins over 30%",
                 "screen the s&p for dividend payers", "stocks well below their 52 week high",
                 "stocks trading at deep discounts to their yearly highs", "cheap tech stocks",
                 "companies with net margins over 30%"):
        hit = match_command(text)
        assert hit and hit.command.name == "screen", text
    assert match_command("scr pe_trailing<20").args["text"] == "scr pe_trailing<20"
    assert match_command("chart NVDA").command.name == "chart"
    assert match_command("what is NVDA").command.name == "company"
