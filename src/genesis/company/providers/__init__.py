# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""One module per source. Imports are lazy, for the same reason the market
data adapters' are: a missing vendor package must degrade to "that source is
unavailable", never to "the company model failed to import"."""

from __future__ import annotations

__all__ = ["EdgarProvider", "YFinanceProvider"]


def __getattr__(name: str) -> type:
    if name == "YFinanceProvider":
        from genesis.company.providers.yfinance import YFinanceProvider

        return YFinanceProvider
    if name == "EdgarProvider":
        from genesis.company.providers.edgar import EdgarProvider

        return EdgarProvider
    raise AttributeError(name)
