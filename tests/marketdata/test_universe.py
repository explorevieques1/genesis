# Spec: Genesis Markdown/50-Risk/Risk Envelope.md
"""The tradeable universe — a safety control, so its failure directions matter.

The allow-list decides what may be traded. Every test here is about what
happens when something goes wrong with it, because the interesting property is
not "it lists 503 names" but "it never lists more than it should".
"""

from __future__ import annotations

import json
import types
from pathlib import Path

from genesis.marketdata import universe as uni


def config_for(tmp_path: Path, *, equity: bool = True, roots=("ES", "NQ")):
    return types.SimpleNamespace(
        memory=types.SimpleNamespace(db_path=tmp_path / "memory.db"),
        risk=types.SimpleNamespace(symbol_allowlist=list(roots), equity_universe=equity),
    )


def test_a_missing_snapshot_degrades_to_futures_and_core_etfs(tmp_path: Path) -> None:
    """Never "everything", and never empty — an empty allow-list would stop the
    futures this desk was already trading."""
    u = uni.load(config_for(tmp_path))
    assert "ES" in u.symbols and "SPY" in u.symbols
    assert "AAPL" not in u.symbols, "no snapshot means no index membership"
    assert u.degraded and "universe refresh" in u.degraded


def test_a_corrupt_snapshot_degrades_the_same_way(tmp_path: Path) -> None:
    uni.path_for(config_for(tmp_path)).write_text("{not json", encoding="utf-8")
    u = uni.load(config_for(tmp_path))
    assert "ES" in u.symbols and "AAPL" not in u.symbols
    assert "unreadable" in u.degraded


def test_the_flag_off_means_futures_only(tmp_path: Path) -> None:
    """Widening a safety control is a decision, not a default."""
    uni.path_for(config_for(tmp_path)).write_text(
        json.dumps({"as_of": "2026-09-17", "equities": ["AAPL"], "etfs": ["SPY"]}), encoding="utf-8")
    u = uni.load(config_for(tmp_path, equity=False))
    assert u.symbols == ("ES", "NQ")


def test_a_snapshot_is_read_and_dated(tmp_path: Path) -> None:
    uni.path_for(config_for(tmp_path)).write_text(
        json.dumps({"as_of": "2026-09-17", "source": "SSGA SPY daily holdings",
                    "equities": ["AAPL", "CVX"], "etfs": ["SPY", "QQQ"]}), encoding="utf-8")
    u = uni.load(config_for(tmp_path))
    assert set(u.symbols) == {"ES", "NQ", "SPY", "QQQ", "AAPL", "CVX"}
    assert u.as_of == "2026-09-17" and u.age_days is not None


def test_an_old_snapshot_reports_stale_rather_than_being_trusted(tmp_path: Path) -> None:
    """A company removed from the index last month is one nobody meant to allow."""
    uni.path_for(config_for(tmp_path)).write_text(
        json.dumps({"as_of": "2020-01-01", "equities": ["AAPL"], "etfs": []}), encoding="utf-8")
    assert uni.load(config_for(tmp_path)).stale is True


def test_a_short_holdings_parse_refuses_to_become_the_allowlist(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    """A partial parse would silently shrink what may be traded, and an
    allow-list that shrank by accident refuses trades for an invisible reason."""
    import pytest

    monkeypatch.setattr(uni, "_holdings", lambda _fund: {"as_of": "17-Sep-2026",
                                                         "members": {"AAPL": ("Apple", 7.0)}},
                        raising=False)
    import genesis.marketdata.index_map as index_map

    monkeypatch.setattr(index_map, "_holdings", lambda _fund: {"as_of": "17-Sep-2026",
                                                               "members": {"AAPL": ("Apple", 7.0)}})
    with pytest.raises(ValueError, match="too few"):
        uni.refresh(config_for(tmp_path))
    assert not uni.path_for(config_for(tmp_path)).exists(), "nothing is written on a bad parse"
