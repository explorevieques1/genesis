# Spec: Genesis Markdown/60-UI/Chart Tools.md
"""The drawing store: the round trip, and the refusals at the boundary."""

from __future__ import annotations

import pytest

from genesis.charting.drawings import MAX_PAYLOAD, DrawingStore
from genesis.errors import DegradedError

SERIES = "EQ:XNAS:NVDA|1D"


def store(tmp_path) -> DrawingStore:
    return DrawingStore(tmp_path / "drawings.db")


def test_round_trip_and_scoping(tmp_path) -> None:
    s = store(tmp_path)
    box = s.save(SERIES, "zone", {"from": 117.9, "to": 118.6, "from_time": 1, "to_time": 9})
    s.save(SERIES, "level", {"price": 122.1, "label": "PDH"})
    s.save("EQ:XNAS:AAPL|1D", "level", {"price": 200.0})

    held = s.list(SERIES)
    assert len(held) == 2
    # The payload is flattened onto the row, so a client reads one object.
    assert held[0]["id"] == box and held[0]["from"] == 117.9 and held[0]["kind"] == "zone"
    # A drawing belongs to one series and appears on no other chart.
    assert [d["price"] for d in s.list("EQ:XNAS:AAPL|1D")] == [200.0]

    # Same id, new geometry: an edit replaces rather than accumulating.
    s.save(SERIES, "zone", {"from": 118.0, "to": 119.0}, drawing_id=box)
    assert len(s.list(SERIES)) == 2
    assert s.list(SERIES)[0]["from"] == 118.0

    assert s.delete(box) and len(s.list(SERIES)) == 1
    assert s.clear(SERIES) == 1 and s.list(SERIES) == []


def test_the_boundary_refuses_what_it_cannot_draw(tmp_path) -> None:
    s = store(tmp_path)
    with pytest.raises(DegradedError):
        s.save(SERIES, "doodle", {"price": 1})     # not a drawable kind
    with pytest.raises(DegradedError):
        s.save("", "level", {"price": 1})          # no series
    with pytest.raises(DegradedError):
        s.save(SERIES, "level", {"note": "x" * (MAX_PAYLOAD + 1)})


def test_a_position_sketch_carries_no_size(tmp_path) -> None:
    """`trade_plan` is a drawing. Safety Invariants §1 — there is no order here.

    The store keeps what it is given, so this asserts the shape the surface
    sends: entry, stop, targets, and nothing that names an account or a size.
    """
    s = store(tmp_path)
    s.save(SERIES, "trade_plan", {
        "side": "long", "entry": 121.0, "stop": 118.4, "targets": [126.2],
    })
    plan = s.list(SERIES)[0]
    assert not {"size", "qty", "quantity", "account", "broker"} & set(plan)
