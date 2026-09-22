# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Config -> a wired :class:`StoreBarSource`. One place, so chains stay honest.

Market Data Sources gives each consumer an ordered fallback chain, and Market
Data Plane requires that chain resolve in one place rather than inside each
agent. This module is that place on the construction side: an agent asks for
"the chart_markup source" and gets exactly the chain the config declares.

Adapters that cannot run are **dropped with a reason, not silently skipped**.
A chain that quietly shortens itself is how "databento first" becomes "yfinance
always" without anyone noticing the futures history stopped arriving.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from genesis.config import Config, MarketData
from genesis.marketdata.budget import Budget
from genesis.marketdata.interface import Adapter
from genesis.marketdata.source import StoreBarSource
from genesis.marketdata.store import BarStore, open_store

__all__ = ["BuiltSource", "build_adapters", "build_source"]


@dataclass
class BuiltSource:
    """A wired source, plus what was left out and why.

    The ``skipped`` list is the point. A caller can print it, and the reason a
    chain is shorter than configured becomes visible at the moment it matters
    rather than being inferred later from missing data.
    """

    source: StoreBarSource
    store: BarStore
    budget: Budget
    used: list[str]
    skipped: list[tuple[str, str]]


def build_adapters(
    settings: MarketData, chain: list[str]
) -> tuple[list[Adapter], list[tuple[str, str]]]:
    """Instantiate the named adapters, in order. Returns ``(adapters, skipped)``."""
    adapters: list[Adapter] = []
    skipped: list[tuple[str, str]] = []

    for name in chain:
        spec = settings.adapters.get(name)
        if spec is None:
            skipped.append((name, "not declared in marketdata.adapters"))
            continue
        if not spec.enabled:
            skipped.append((name, "disabled in config"))
            continue
        try:
            adapter = _instantiate(name, spec)
        except Exception as exc:
            skipped.append((name, str(exc)))
            continue
        available = getattr(adapter, "available", True)
        if not available:
            skipped.append(
                (name, "missing API key or package — see .env.example")
            )
            continue
        adapters.append(adapter)
    return adapters, skipped


def _instantiate(name: str, spec: Any) -> Adapter:
    if name == "databento":
        from genesis.marketdata.adapters.databento import DatabentoAdapter

        return DatabentoAdapter(tier=spec.tier)
    if name == "yfinance":
        from genesis.marketdata.adapters.yfinance import YFinanceAdapter

        return YFinanceAdapter(tier=spec.tier)
    if name == "csv":
        from genesis.marketdata.adapters.csv import CsvAdapter

        if spec.root is None:
            raise ValueError("csv adapter needs a `root`")
        return CsvAdapter(root=spec.root.expanduser(), tier=spec.tier)
    if name == "ibkr":
        from genesis.marketdata.adapters.ibkr import IbkrAdapter, IbkrConnection

        # tier comes from config, and it is 3 until the reconciliation in
        # `genesis.marketdata.reconcile` has been run and its tolerance written
        # into Market Data Sources.md. Promoting here would put the decision in
        # the wrong place -- see that note's warning callout.
        return IbkrAdapter(
            connection=IbkrConnection(
                host=spec.host or "127.0.0.1",
                port=spec.port or 4002,
                client_id=spec.client_id if spec.client_id is not None else 17,
                market_data_type=spec.market_data_type or "delayed",
                use_watchdog=spec.use_watchdog,
            ),
            tier=spec.tier,
        )
    raise ValueError(f"unknown adapter {name!r}")


def build_source(
    config: Config, consumer: str = "default", *, allow_fetch: bool = True
) -> BuiltSource:
    """The store and the consumer's chain, wired and ready."""
    settings = config.marketdata
    chain = settings.chain_for(consumer)
    adapters, skipped = build_adapters(settings, chain)
    # The process's handle, not a second connection. A chart command running
    # inside `genesis serve` shares the store the read routes already opened,
    # and upgrades it to writable if this is the first write.
    store = open_store(settings.store_path)
    budget = Budget(settings.budget_path)
    for adapter in adapters:
        caps = adapter.capabilities()
        budget.register(caps.name, caps.pacing)
    return BuiltSource(
        source=StoreBarSource(
            store=store,
            adapters=adapters,
            budget=budget,
            # An empty chain is "store only" (Market Data Sources: backtests
            # read stored bars only). Honouring that here rather than letting
            # an empty adapter list fail obscurely later.
            allow_fetch=allow_fetch and bool(chain),
        ),
        store=store,
        budget=budget,
        used=[a.capabilities().name for a in adapters],
        skipped=skipped,
    )
