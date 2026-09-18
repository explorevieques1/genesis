# Spec: Genesis Markdown/20-Agents/Execution/Agent — Order Manager.md §Acceptance criteria
from __future__ import annotations

from decimal import Decimal as D
from pathlib import Path

import pytest

from genesis.config import load_config
from genesis.execution import halt
from genesis.execution.order_manager import OrderManager, Refused

from tests.execution.fake_broker import FakeBroker

NQ = "FUT:CME:NQ:2026-12"


def manager(tmp_path: Path, broker: FakeBroker | None = None, mode: str = "confirm") -> tuple[OrderManager, FakeBroker]:
    cfg = load_config(None)
    cfg = cfg.model_copy(update={
        "execution": cfg.execution.model_copy(update={"state_dir": tmp_path, "enabled": True}),
        "approval": cfg.approval.model_copy(update={"mode": mode}),
    })
    events: list[tuple[str, dict]] = []
    b = broker or FakeBroker()
    m = OrderManager(cfg, lambda e, d: events.append((e, d)), broker=b, threaded=False)
    m.events = events  # type: ignore[attr-defined]
    m._killswitch_ok = True
    m.open()
    return m, b


def ticket(**kw):
    t = {"symbol_id": NQ, "side": "buy", "qty": 1, "order_type": "limit", "limit_price": "29360",
         "stop": {"kind": "fixed", "offset": "20"}, "target": {"offset": "40"}}
    t.update(kw)
    return t


def test_confirm_mode_places_a_native_bracket_only_with_a_named_confirmation(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    assert proposed["ok"] and proposed["approval"]["requires_confirmation"]
    aid = proposed["approval"]["approval_id"]
    with pytest.raises(Refused, match="must name NQZ6"):
        m.place(aid, {"symbol": "yes"})
    assert b.placed == []

    proposed = m.propose(ticket())
    out = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})
    refs = {s["ref"]: s for s in b.placed}
    cid = out["client_order_id"]
    assert set(refs) == {cid, f"{cid}_sl", f"{cid}_tp"}
    assert refs[f"{cid}_sl"]["stop"] == D("29340") and refs[f"{cid}_tp"]["limit"] == D("29400")
    assert refs[f"{cid}_sl"]["parent_ref"] == cid
    assert all(m.ledger.order("DU123", r)["approval_id"] == proposed["approval"]["approval_id"] for r in refs)


def test_nothing_reaches_the_broker_without_an_approval(tmp_path):
    m, b = manager(tmp_path)
    with pytest.raises(Refused, match="unknown approval"):
        m.place("appr_forged", {"symbol": "NQZ6", "qty": 1})
    rejected = m.propose(ticket(stop={"kind": "none"}))
    assert not rejected["ok"] and "approval" not in rejected
    halt.engage(m.halt_path, level="halt", trigger="test")
    assert not m.propose(ticket())["ok"]
    assert b.placed == []


def test_an_approval_is_refused_if_the_kill_switch_fired_after_it(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    halt.engage(m.halt_path, level="halt", trigger="test")
    with pytest.raises(Refused, match="kill switch"):
        m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})
    assert b.placed == []


def test_market_entry_places_its_stop_at_the_real_fill_price(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket(order_type="market", limit_price=None))
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    assert [s["ref"] for s in b.placed] == [cid]          # nothing guessed from a delayed quote
    b.fill(cid, D("29380"))
    m.pump(0)
    stops = {s["role"]: s for s in b.placed[1:]}
    assert stops["stop"]["stop"] == D("29360") and stops["target"]["limit"] == D("29420")
    assert m.ledger.count_fills() == 1
    assert any(e == "order.filled" for e, _ in m.events)
    assert m.quality.recent()[0].verdict == "unmeasured"   # delayed arrival quote


def test_trailing_stop_travels_with_the_parent(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket(order_type="market", limit_price=None, stop={"kind": "trail", "trail": "25"},
                                target=None))
    m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})
    assert [(s["type"], s.get("trail")) for s in b.placed] == [("market", None), ("trail", D("25"))]


def test_restart_adopts_working_orders_without_placing_them_again(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})
    b.fill(b.placed[0]["ref"], D("29360"))
    m.pump(0)
    placed = len(b.placed)
    m.ledger.close()

    again, _ = manager(tmp_path, broker=b)
    assert again._recon["matched"], again._recon
    assert len(b.placed) == placed
    assert not halt.read(again.halt_path)["engaged"]


def test_a_position_genesis_did_not_open_halts_until_adopted(tmp_path):
    b = FakeBroker()
    b.pos[555] = (2, D("29000"))
    m, _ = manager(tmp_path, broker=b)
    assert m._recon["matched"] is False and halt.read(m.halt_path)["engaged"]
    with pytest.raises(Refused, match="reconciliation must pass"):
        m.resume("dashboard", "")
    m.adopt("dashboard")
    assert m._recon["matched"]
    with pytest.raises(Refused, match="dashboard"):
        m.resume("voice", "")
    assert m.resume("dashboard", "old paper position")["ok"]


def test_halt_cancels_entries_and_keeps_every_exit_order(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket(qty=1))
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    b.fill(cid, D("29360"))
    m.pump(0)
    b.mid = D("29370")
    second = m.propose(ticket(limit_price="29350"))
    m.place(second["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})
    halt.engage(m.halt_path, level="halt", trigger="test")
    m._watch_halt()
    working = {o["ref"] for o in b.orders if o["working"]}
    assert working == {f"{cid}_sl", f"{cid}_tp"}          # exits stay; the second entry is gone
    assert ("halt.engaged", {"trigger": "test", "level": "halt"}) in m.events


def test_a_protective_stop_cannot_be_cancelled_with_the_position_open(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    b.fill(cid, D("29360"))
    m.pump(0)
    with pytest.raises(Refused, match="protective stop"):
        m.cancel(f"{cid}_sl")


def test_an_unprotected_position_is_flattened_after_the_grace_period(tmp_path, monkeypatch):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    b.fill(cid, D("29360"))
    m.pump(0)
    b._find(f"{cid}_sl").update(working=False, status="Cancelled")  # the stop vanished at the broker
    m._protect()
    assert 555 in m._unprotected
    m._unprotected[555] -= 10
    m._protect()
    closes = [s for s in b.placed if s["role"] == "close"]
    assert closes and closes[0]["side"] == "sell" and closes[0]["type"] == "market"


def test_flatten_cancels_protection_then_closes(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket(qty=2))
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 2})["client_order_id"]
    b.fill(cid, D("29360"))
    m.pump(0)
    out = m.flatten(NQ)
    assert out["ok"]
    assert not any(o["working"] and o["ref"].startswith(cid + "_") for o in b.orders)
    assert b.placed[-1]["role"] == "close" and b.placed[-1]["qty"] == 2


def test_one_click_needs_auto_mode_and_the_dashboard(tmp_path, monkeypatch):
    import genesis.config as gc

    monkeypatch.setattr(gc, "DEFAULT_CONFIG_PATH", tmp_path / "config.yaml")
    m, b = manager(tmp_path)
    with pytest.raises(Refused, match="one-click trading is off"):
        m.submit(ticket())
    with pytest.raises(Refused, match="dashboard"):
        m.set_mode("auto-within-limits", "voice")
    m.set_mode("auto-within-limits", "dashboard")
    out = m.submit(ticket())
    assert out["placed"] and len(b.placed) == 3
    assert "auto-within-limits" in (tmp_path / "config.yaml").read_text()


def test_moving_a_limit_entry_moves_its_bracket(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    m.modify(cid, {"limit_price": "29350"})
    by = {o["ref"]: o for o in b.orders}
    assert by[cid]["limit"] == D("29350") and by[f"{cid}_sl"]["stop"] == D("29330")
    assert by[f"{cid}_tp"]["limit"] == D("29390")


def test_a_failed_placement_is_recorded_and_not_retried(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    b.fail_place = True
    with pytest.raises(Refused, match="Nothing was retried"):
        m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})
    assert b.placed == []
    order = m.ledger.orders()[0]
    assert m.ledger.order_state("DU123", order["client_order_id"]) == "rejected"


def test_daily_pnl_falls_back_to_net_liquidation_since_the_session_opened(tmp_path):
    m, b = manager(tmp_path)
    b.pnl = None
    assert m._daily_pnl() == D(0)              # first look this session: snapshot taken
    b.net_liquidation = lambda: D(998_500)
    assert m._daily_pnl() == D(-1500)


def test_native_bracket_children_carry_no_oca_group_so_they_can_be_moved(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    assert all(not s.get("oca") for s in b.placed)
    m.modify(f"{cid}_sl", {"stop_price": "29345"})
    assert b._find(f"{cid}_sl")["stop"] == D("29345")


def test_converting_a_bracket_stop_to_a_trail_keeps_a_stop_working_throughout(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket())
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    b.fill(cid, D("29360"))
    m.pump(0)
    m.modify(f"{cid}_sl", {"trail_amount": "10"})
    working = {o["ref"]: o for o in b.orders if o["working"]}
    assert set(working) == {f"{cid}_sl_tr2", f"{cid}_sl_tp2"}, working
    assert working[f"{cid}_sl_tr2"]["stop"] < D("29340")      # trigger beyond the old stop
    assert working[f"{cid}_sl_tp2"]["limit"] > D("29400")     # target beyond the old target
    assert m._state()["positions"][0]["protected"]


def test_converting_a_market_entrys_stop_to_a_trail_survives_the_oca_cascade(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket(order_type="market", limit_price=None))
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    b.fill(cid, D("29380"))
    m.pump(0)
    stop = next(o["ref"] for o in b.orders if o["working"] and o["type"] == "stop")
    m.modify(stop, {"trail_amount": "10"})
    working = [o for o in b.orders if o["working"]]
    assert sorted(o["type"] for o in working) == ["limit", "trail"], working
    assert m._state()["positions"][0]["protected"]


def test_replayed_fills_on_connect_do_not_touch_a_new_brackets_children(tmp_path):
    m, b = manager(tmp_path)
    proposed = m.propose(ticket(order_type="market", limit_price=None))
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    b.fill(cid, D("29380"))
    m.pump(0)
    m.flatten(NQ)
    b.fill(b.placed[-1]["ref"], D("29390"))
    m.pump(0)
    second = m.propose(ticket())
    cid2 = m.place(second["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    b.in_callback = True
    for fill in list(b.fills):          # IBKR replays today's executions
        m._on_fill(fill)
    b.in_callback = False
    m.pump(0)
    assert {o["ref"] for o in b.orders if o["working"]} == {cid2, f"{cid2}_sl", f"{cid2}_tp"}


def test_a_market_order_that_fills_during_placement_still_gets_its_stop(tmp_path):
    """Seen live 2026-09-14: the fill arrived inside place(), before the manager
    knew protection was owed."""
    m, b = manager(tmp_path)
    b.fill_market_on_place = True
    proposed = m.propose(ticket(order_type="market", limit_price=None))
    cid = m.place(proposed["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})["client_order_id"]
    roles = sorted(s["role"] for s in b.placed[1:])
    assert roles == ["stop", "target"], b.placed
    assert cid not in m._pending
    assert m._state()["positions"][0]["protected"]


def test_independent_orders_each_transmit_and_a_bracket_waits_for_its_last_child():
    from genesis.execution.ibkr_broker import _transmits

    bracket = [{"ref": "e"}, {"ref": "e_sl", "parent_ref": "e"}, {"ref": "e_tp", "parent_ref": "e"}]
    assert [_transmits(bracket, i) for i in range(3)] == [False, False, True]
    standalone = [{"ref": "e_sl1"}, {"ref": "e_tp1"}]
    assert [_transmits(standalone, i) for i in range(2)] == [True, True]


def test_a_missing_bid_is_not_averaged_into_the_quote():
    from types import SimpleNamespace

    from genesis.execution.ibkr_broker import IbkrBroker

    broker = IbkrBroker(host="h", port=1, client_id=30)
    broker.ib = SimpleNamespace(reqMktData=None, sleep=lambda s: None)
    broker._tickers[1] = SimpleNamespace(bid=-1.0, ask=29458.5, last=29458.25, marketDataType=3)
    q = broker.quote(SimpleNamespace(con_id=1))
    assert q["bid"] is None and q["mid"] == D("29458.25")


class SmallAccount(FakeBroker):
    """$10,000 of equity: at a 6% heat limit that is $600 of open risk, and one
    NQ contract with a 20-point stop is $400 of it."""

    def net_liquidation(self):
        return D(10_000)


def test_heat_counts_a_working_entry_before_it_fills(tmp_path):
    """Two quick entries must not both pass heat because neither has filled yet."""
    m, b = manager(tmp_path, SmallAccount())
    first = m.propose(ticket(qty=1))
    assert first["ok"], first
    m.place(first["approval"]["approval_id"], {"symbol": "NQZ6", "qty": 1})
    assert not b.pos, "still working, not filled"

    # A different price, so the duplicate check is not what stops it.
    second = m.propose(ticket(qty=1, limit_price="29350"))
    assert not second["ok"]
    assert second["decision"]["binding_check"] == "portfolio_heat", second["decision"]
    assert "one more contract" in second["reason"]


def test_heat_with_room_passes_through_the_real_path(tmp_path):
    m, _ = manager(tmp_path, SmallAccount())
    proposed = m.propose(ticket(qty=1))
    assert proposed["ok"], proposed
    heat = [c for c in proposed["decision"]["checks"] if c["id"] == "portfolio_heat"]
    assert heat and heat[0]["result"] == "pass", proposed["decision"]["checks"]
    assert "4.00%" in heat[0]["detail"]  # $400 of $10,000
