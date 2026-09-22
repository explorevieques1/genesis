# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""The market data plane: how bars enter Genesis and where they live.

Afferent, entirely. Read-only, retryable, no approval, no model anywhere in the
path -- Biological Design's ``afferent ≠ efferent``. There is no ``write``, no
``submit`` and no order anywhere in this package, and that is structural rather
than an omission: the Protocol in :mod:`~genesis.marketdata.interface` has two
methods and neither of them can act on the world.

Layout, in dependency order:

``normalize``   the one bar schema and the one symbol id. Everything depends on it.
``interface``   the Adapter Protocol, drawn to fit IBKR rather than to fit yfinance.
``budget``      the only code that knows a vendor quota. A reflex.
``store``       DuckDB. What the world did, in Decimal, written once.
``staleness``   every read reports its age. A reflex.
``adapters``    one file per vendor.
``source``      StoreBarSource -- the store wearing the Charting Engine's interface.
"""

from __future__ import annotations

__all__ = ["BarStore", "StoreBarSource"]


def __getattr__(name: str) -> type:
    # Lazy so that importing this package does not import duckdb. The daemon
    # imports broadly at startup and must not pay for a store it may not open.
    if name == "BarStore":
        from genesis.marketdata.store import BarStore

        return BarStore
    if name == "StoreBarSource":
        from genesis.marketdata.source import StoreBarSource

        return StoreBarSource
    raise AttributeError(name)
