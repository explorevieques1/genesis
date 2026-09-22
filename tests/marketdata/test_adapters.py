# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Adapters: the CSV replay path, and the refusals the other two make.

No network is touched here. The databento and yfinance tests exercise the
paths that run *before* a request would be sent -- capability declarations and
refusals -- because those are the parts that must be right whether or not a key
is present, and because a test suite that needs a vendor is a test suite that
does not run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from genesis.errors import DegradedError
from genesis.marketdata.adapters.csv import CsvAdapter
from genesis.marketdata.adapters.databento import DatabentoAdapter
from genesis.marketdata.adapters.yfinance import YFinanceAdapter
from genesis.marketdata.interface import BarRequest, chunk_request

ES = "FUT:CME:ES:2025-12"


def request(symbol: str = ES, tf: str = "1D", days: int = 30) -> BarRequest:
    end = datetime(2026, 4, 1, tzinfo=UTC)
    return BarRequest(symbol, tf, end - timedelta(days=days), end)


# -- CSV replay ------------------------------------------------------------


@pytest.fixture
def replay(tmp_path):
    root = tmp_path / "replay"
    folder = root / ES.replace(":", "_")
    folder.mkdir(parents=True)
    (folder / "1D.csv").write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2026-03-02T00:00:00Z,4500.00,4510.25,4495.50,4505.75,1200000\n"
        "2026-03-03T00:00:00Z,4505.75,4520.00,4501.00,4518.25,1350000\n"
        "2026-03-04T00:00:00Z,4518.25,4525.50,4505.00,4507.00,1100000\n"
    )
    return CsvAdapter(root=root)


def test_csv_replay_is_exact(replay):
    bars = replay.fetch(request(days=60))
    assert len(bars) == 3
    assert bars[0].close == Decimal("4505.75")
    assert bars[-1].high == Decimal("4525.50")
    assert all(b.tier == 3 for b in bars)


def test_csv_replay_is_deterministic(replay):
    """The market data is identical across reads. `ingested_at` is not, and
    should not be -- it records when WE saw it, which genuinely differs. The
    determinism that matters is of the facts, so that is what is compared."""

    def facts(bars):
        return [(b.ts, b.open, b.high, b.low, b.close, b.volume) for b in bars]

    assert facts(replay.fetch(request(days=60))) == facts(
        replay.fetch(request(days=60))
    )


def test_csv_honours_the_half_open_window(replay):
    """start <= ts < end, so two adjacent requests concatenate without a
    duplicate or a hole at the seam."""
    boundary = datetime(2026, 3, 3, tzinfo=UTC)
    left = replay.fetch(
        BarRequest(ES, "1D", datetime(2026, 3, 1, tzinfo=UTC), boundary)
    )
    right = replay.fetch(
        BarRequest(ES, "1D", boundary, datetime(2026, 3, 10, tzinfo=UTC))
    )
    assert len(left) == 1 and len(right) == 2
    assert {b.ts for b in left}.isdisjoint({b.ts for b in right})


def test_a_missing_ohlc_column_is_refused(tmp_path):
    folder = tmp_path / "r" / ES.replace(":", "_")
    folder.mkdir(parents=True)
    (folder / "1D.csv").write_text("Date,Open,High,Volume\n2026-03-02,1,2,3\n")
    with pytest.raises(DegradedError, match="missing column"):
        CsvAdapter(root=tmp_path / "r").fetch(request())


def test_a_missing_file_degrades_rather_than_crashes(tmp_path):
    with pytest.raises(DegradedError, match="no replay file"):
        CsvAdapter(root=tmp_path).fetch(request())


# -- refusals --------------------------------------------------------------


def test_yfinance_refuses_dated_futures():
    """Its 'ES=F' is a continuous front-month series with an undocumented
    roll -- a different instrument, and one that looks like the others.
    Open Questions §13."""
    with pytest.raises(DegradedError, match="continuous"):
        YFinanceAdapter().fetch(request())


def test_yfinance_declares_that_it_cannot_serve_futures():
    """Declared as data, so a chain can route around it without a failed
    request."""
    assert "FUT" not in YFinanceAdapter().capabilities().asset_classes


def test_databento_without_a_key_degrades_with_an_actionable_message():
    adapter = DatabentoAdapter(api_key=None)
    assert adapter.available is False
    with pytest.raises(DegradedError, match=r"\.env"):
        adapter.fetch(request())


def test_databento_refuses_a_timeframe_it_does_not_publish():
    """Rather than resampling behind the caller's back -- which is how a
    '4H bar from Databento' turns out to be nothing of the sort."""
    adapter = DatabentoAdapter(api_key="db-" + "0" * 32)
    with pytest.raises(DegradedError, match="not"):
        adapter.fetch(request(tf="4H"))


def test_databento_maps_a_dated_contract_to_the_cme_spelling():
    assert DatabentoAdapter._vendor_symbol(
        __import__(
            "genesis.marketdata.normalize", fromlist=["parse_instrument_id"]
        ).parse_instrument_id(ES)
    ) == "ESZ5"


# -- chunking --------------------------------------------------------------


def test_chunking_splits_to_the_vendors_span_limit():
    """IBKR's per-bar-size duration cap, generalised. Walks FORWARD so a
    partial failure leaves a contiguous prefix rather than an island."""
    caps = YFinanceAdapter().capabilities()
    pieces = chunk_request(request("EQ:XNAS:AAPL", "1m", days=30), caps)

    assert len(pieces) > 1
    assert pieces[0].start == request("EQ:XNAS:AAPL", "1m", days=30).start
    for a, b in zip(pieces, pieces[1:]):
        assert a.end == b.start, "chunks must abut exactly — no hole, no overlap"
    assert pieces[-1].end == request("EQ:XNAS:AAPL", "1m", days=30).end


def test_an_uncapped_timeframe_is_not_chunked():
    caps = DatabentoAdapter(api_key="x").capabilities()
    assert len(chunk_request(request(days=3650), caps)) == 1
