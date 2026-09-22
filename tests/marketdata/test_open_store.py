"""One process, one file, one handle.

Spec: Genesis Markdown/10-Architecture/Market Data Sources.md

The bug these pin: DuckDB keys one database instance per file per process and
refuses a second connection whose configuration differs from the first. Three
call sites opened `~/.genesis/market/market.duckdb` independently -- the read
routes read-only, `build_source` writable, `CompanyStore` writable -- so the
daemon crashed the first time a chart command followed a read:

    FatalError: cannot open the market data store at ...: Connection Error:
    Can't open a connection to same database file with a different
    configuration than existing connections

It is an ordering bug, so it is tested as an ordering.
"""

from __future__ import annotations

import pytest

from genesis.company.store import CompanyStore
from genesis.marketdata.store import BarStore, close_open_stores, open_store


@pytest.fixture
def store_path(tmp_path):
    path = tmp_path / "market.duckdb"
    BarStore(path).close()  # create the file; read-only cannot
    yield path
    close_open_stores()


def test_one_handle_per_file(store_path):
    assert open_store(store_path, read_only=True) is open_store(store_path)


def test_read_then_write_does_not_crash(store_path):
    """The exact sequence that took the daemon down."""
    reader = open_store(store_path, read_only=True)
    assert reader.read_only

    writer = open_store(store_path, read_only=False)
    assert writer is reader
    assert not reader.read_only, "a write request must upgrade the shared handle"

    # And the upgraded handle can actually write, which is the point of asking.
    reader.conn.execute("CREATE TABLE t (x INTEGER)")
    reader.conn.execute("INSERT INTO t VALUES (1)")
    assert reader.conn.execute("SELECT count(*) FROM t").fetchone() == (1,)


def test_company_store_shares_the_handle(store_path):
    """The third opener. Company tables live in the same file as the bars."""
    reader = open_store(store_path, read_only=True)
    company = CompanyStore(store_path)
    assert company._store is reader
    assert not reader.read_only

    # Read through, never captured: the upgrade swapped the connection object,
    # and a CompanyStore holding the old one would be talking to a closed
    # connection with no obvious symptom.
    assert company.conn is reader.conn
    assert company.conn.execute("SELECT 1").fetchone() == (1,)


def test_closing_a_shared_store_is_a_noop(store_path):
    """Fifteen call sites close in a `finally`. None of them may take the
    process's store down with them."""
    store = open_store(store_path, read_only=True)
    store.close()
    assert store.conn.execute("SELECT 1").fetchone() == (1,)
    assert CompanyStore(store_path).close() is None
    assert store.conn.execute("SELECT 1").fetchone() == (1,)


def test_an_explicit_barstore_still_closes(tmp_path):
    """`BarStore(...)` direct is unshared -- tests and one-shot CLI use it."""
    store = BarStore(tmp_path / "own.duckdb")
    assert not store._shared
    store.close()
    with pytest.raises(Exception):
        store.conn.execute("SELECT 1")
