# Spec: Genesis Markdown/20-Agents/Execution/Agent — Execution Quality.md §Acceptance criteria
"""Slippage against hand-computed fixtures, for buys and sells."""

from __future__ import annotations

from decimal import Decimal as D

from genesis.agents.execution.execution_quality import QualityStore, daily_aggregate, measure_fill


def fill(side: str, price: str, source: str = "realtime", **kw):
    base = dict(fill_id=f"f_{side}_{price}", order="o", symbol="NQZ6", side=side, qty=2,
                fill_price=D(price), multiplier=D(20), fees=D("4.50"), order_type="market",
                ts="2026-09-14T14:00:00+00:00", arrival_mid=D(20000), arrival_bid=D("19999.75"),
                arrival_ask=D("20000.25"), arrival_source=source, time_to_fill_ms=300)
    base.update(kw)
    return measure_fill(**base)


def test_buy_above_mid_is_adverse_and_priced_in_dollars():
    q = fill("buy", "20001")
    assert q.arrival_bps == "0.50"          # 1/20000 × 10,000
    assert q.slippage_dollars == "40.00"    # 1 pt × 2 × $20
    assert q.spread_at_arrival_bps == "0.25"


def test_sell_below_mid_is_adverse_too():
    q = fill("sell", "19999")
    assert q.arrival_bps == "0.50" and q.slippage_dollars == "40.00"
    assert fill("sell", "20001").verdict == "good"


def test_adverse_selection_negative_means_price_went_our_way():
    assert fill("buy", "20000", mid_30s_after=D(20010)).adverse_selection_30s_bps == "-5.00"


def test_verdicts_pathological_only_when_it_is():
    assert fill("buy", "20000.25").verdict == "normal"
    assert fill("buy", "20040").verdict == "pathological"   # 20 bps on a 0.25 bps spread


def test_a_delayed_benchmark_is_never_a_verdict():
    q = fill("buy", "20040", source="delayed")
    assert q.verdict == "unmeasured" and "delay" in q.why


def test_daily_aggregate_excludes_unmeasured_and_says_so(tmp_path):
    store = QualityStore(tmp_path / "q.db")
    for q in (fill("buy", "20001"), fill("sell", "19999"), fill("buy", "20050", source="delayed")):
        store.put(q)
    agg = daily_aggregate("2026-09-14", store.on("2026-09-14"), limit_orders_placed=4, limit_orders_filled=3)
    assert agg["measured_fills"] == 2 and agg["unmeasured_fills"] == 1
    assert agg["median_arrival_slippage_bps"] == "0.50"
    assert agg["limit_fill_rate"] == 0.75 and agg["fees_per_contract"] == "2.25"
