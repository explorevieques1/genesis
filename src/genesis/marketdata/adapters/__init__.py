# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Vendor adapters. One file per vendor, each satisfying ``Adapter``.

Imports are lazy -- ``databento`` and ``yfinance`` pull heavy dependency trees
and a missing one must degrade this package to "that vendor is unavailable",
never to "the market data plane failed to import". The daemon has to start on a
machine with no vendor packages at all and say honestly what it cannot reach.
"""

from __future__ import annotations

__all__ = ["CsvAdapter", "DatabentoAdapter", "YFinanceAdapter"]


def __getattr__(name: str) -> type:
    if name == "CsvAdapter":
        from genesis.marketdata.adapters.csv import CsvAdapter

        return CsvAdapter
    if name == "DatabentoAdapter":
        from genesis.marketdata.adapters.databento import DatabentoAdapter

        return DatabentoAdapter
    if name == "YFinanceAdapter":
        from genesis.marketdata.adapters.yfinance import YFinanceAdapter

        return YFinanceAdapter
    raise AttributeError(name)
