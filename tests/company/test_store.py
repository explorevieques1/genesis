# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""The cache: per-group TTLs, provenance survival, and no network on a repeat.

The property that matters is the last one. One profile is a dozen HTTP requests
to a vendor that rate limits without warning, so "a second lookup costs
nothing" is not an optimisation here -- it is what makes the feature usable at
all.
"""

from __future__ import annotations

import socket
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from genesis.company.schema import (
    CompanyProfile,
    FinancialStatement,
    Sourced,
    StatementLine,
)
from genesis.company.store import CompanyStore


@pytest.fixture
def store(tmp_path):
    s = CompanyStore(tmp_path / "c.duckdb")
    yield s
    s.close()


def profile_with(**fields) -> CompanyProfile:
    p = CompanyProfile("NVDA")
    p.set("long_name", Sourced("NVIDIA Corporation", "yfinance", group="identity"))
    p.set("sector", Sourced("Technology", "yfinance", group="identity"))
    for name, entry in fields.items():
        p.set(name, entry)
    return p


def test_a_profile_round_trips(store):
    store.write(profile_with())
    got = store.read("NVDA")
    assert got is not None
    assert got.name == "NVIDIA Corporation"
    assert got.is_identified


def test_decimals_survive_the_round_trip(store):
    """A market cap through float loses precision permanently.
    Conventions.md §Money is not a judgement call."""
    store.write(profile_with(
        market_cap=Sourced(Decimal("5562502742016.00"), "yfinance", group="market")
    ))
    got = store.read("NVDA")
    cached = got.get("market_cap")
    # Assert the TYPE, not just the value. The first version of this test wrote
    # `Decimal(got.get(...)) == ...`, and the coercion in the assertion
    # re-created the type the store had lost -- so it passed while the cache
    # was handing back strings.
    assert isinstance(cached, Decimal), f"cache returned {type(cached).__name__}"
    assert cached == Decimal("5562502742016.00")


def test_provenance_survives_the_round_trip(store):
    """A cached value that lost its source cannot be spoken. Safety
    Invariants §10 applies to a cache hit exactly as to a fresh fetch."""
    store.write(profile_with(
        pe_trailing=Sourced(
            Decimal("29.16"), "yfinance", tier=3, group="market",
            derived=True, conflict="edgar disagrees",
        )
    ))
    entry = store.read("NVDA").sourced("pe_trailing")
    assert entry.source == "yfinance"
    assert entry.derived is True
    assert entry.conflict == "edgar disagrees"
    assert "DISPUTED" in entry.label()


def test_an_expired_field_is_not_returned(store):
    """The market group's TTL is 15 minutes. A price from an hour ago is not
    a slightly old price -- it is one the caller must refetch."""
    stale = profile_with(
        price=Sourced(
            Decimal("230.36"), "yfinance", group="market",
            as_of=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    store.write(stale)
    got = store.read("NVDA")
    assert got.get("price") is None
    assert got.get("sector") == "Technology", "identity has a 30-day TTL"


def test_groups_expire_independently(store):
    """The whole reason for per-group TTLs: a 15-minute price must not drag
    a 30-day sector out of the cache with it."""
    p = profile_with(
        price=Sourced(
            Decimal("1"), "yfinance", group="market",
            as_of=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    store.write(p)
    assert store.fresh_groups("NVDA") == {"identity"}


def test_statement_lines_keep_both_dates(store):
    """Hazard 2 must survive storage, or an as-of query silently breaks after
    a cache refresh."""
    p = profile_with()
    p.statements[("income", "annual")] = FinancialStatement(
        statement="income",
        frequency="annual",
        lines=(
            StatementLine(
                concept="revenue",
                value=Decimal("215938000000"),
                fiscal_period_end=date(2026, 1, 25),
                filed_date=date(2026, 2, 25),
                frequency="annual",
                source="edgar",
            ),
        ),
        source="edgar",
    )
    store.write(p)

    line = store.read("NVDA").statement("income", "annual").concept("revenue")
    assert line.fiscal_period_end == date(2026, 1, 25)
    assert line.filed_date == date(2026, 2, 25)
    assert line.known_by(date(2026, 1, 25)) is False
    assert line.known_by(date(2026, 3, 1)) is True


def test_reading_an_unknown_symbol_returns_none(store):
    assert store.read("NOTHELD") is None


def test_rewriting_replaces_rather_than_duplicates(store):
    store.write(profile_with(price=Sourced(Decimal("1"), "yfinance", group="market")))
    store.write(profile_with(price=Sourced(Decimal("2"), "yfinance", group="market")))
    got = store.read("NVDA")
    assert Decimal(got.get("price")) == Decimal("2")


def test_the_second_resolve_makes_no_network_call(store, monkeypatch):
    """The load-bearing property. Proven by removing `socket` from the
    interpreter rather than by counting calls, so a request escaping from any
    layer -- a provider, an SDK, an HTTP pool warming itself -- fails loudly."""
    from genesis.company.profile import resolve

    store.write(profile_with(
        market_cap=Sourced(Decimal("5.5e12"), "yfinance", group="market")
    ))

    def no_network(*args, **kwargs):
        raise AssertionError("a network call escaped on a cached lookup")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    result = resolve("NVDA", store=store)
    assert result.from_cache is True
    assert result.network_calls == 0
    assert result.profile.name == "NVIDIA Corporation"


def test_an_unidentified_cache_entry_forces_a_refetch(store, monkeypatch):
    """A cached profile that lost its identity group has effectively expired,
    whatever else survived -- and must not be served as a company."""
    from genesis.company import profile as profile_module

    junk = CompanyProfile("NVDA")
    junk.set("price", Sourced(Decimal("1"), "yfinance", group="market"))
    store.write(junk)

    called = {"n": 0}

    def fake_fetch(ticker, *, use_edgar):
        called["n"] += 1
        return profile_with(), ["yfinance"], 1

    monkeypatch.setattr(profile_module, "_fetch", fake_fetch)
    result = profile_module.resolve("NVDA", store=store)
    assert called["n"] == 1
    assert result.from_cache is False
