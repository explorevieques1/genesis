# Spec: Genesis Markdown/20-Agents/Research/Agent — Screener.md
"""One row of fundamentals per S&P 500 member, refreshed while the market is closed.

**Membership is SPY's own holdings file** (:mod:`genesis.marketdata.index_map`),
sectors are which sector SPDR holds the name. Never model memory.

**Numbers are yfinance ``.info``**, one call per member, tier 3. Converted once,
here, into the units a person says out loud: ratios are percent (``margin_net``
27.6, not 0.276), sizes are billions. yfinance is not consistent about this --
``dividendYield`` and ``debtToEquity`` already arrive as percent while every
other ratio is a fraction -- so leaving it to the caller means the model and a
typed ``scr`` command would disagree about what "10" means.

A value yfinance does not report stays absent. A company with negative earnings
has no P/E, and the scan excludes it from a P/E criterion rather than treating
the gap as zero.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from genesis.agents.charting.data_viz import SECTOR_ETFS
from genesis.memory.db import connect, transaction

__all__ = [
    "FIELDS", "SECTORS", "TEXT_FIELDS", "Snapshot", "build_snapshot", "load_current", "load_snapshot",
    "save_current", "snapshot_path",
]

log = logging.getLogger(__name__)

Info = dict[str, Any]


def _key(name: str, scale: float = 1.0) -> Callable[[Info], float | None]:
    def read(info: Info) -> float | None:
        value = info.get(name)
        return float(value) * scale if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return read


def _ratio(num: str, den: str, *, minus_one: bool = False) -> Callable[[Info], float | None]:
    def read(info: Info) -> float | None:
        a, b = _key(num)(info), _key(den)(info)
        if a is None or not b:
            return None
        return (a / b - (1 if minus_one else 0)) * 100
    return read


#: name -> (unit, meaning, reader). The closed vocabulary the scan and the
#: interpreter share; a field not here does not exist.
FIELDS: dict[str, tuple[str, str, Callable[[Info], float | None]]] = {
    "price": ("$", "last price", _key("currentPrice")),
    "market_cap_b": ("$B", "market capitalisation in billions", _key("marketCap", 1e-9)),
    "pe_trailing": ("x", "price / trailing-12-month EPS; absent when earnings are negative", _key("trailingPE")),
    "pe_forward": ("x", "price / next-12-month consensus EPS", _key("forwardPE")),
    "peg": ("x", "trailing P/E divided by expected EPS growth", _key("trailingPegRatio")),
    "price_to_book": ("x", "price / book value per share", _key("priceToBook")),
    "price_to_sales": ("x", "market cap / trailing-12-month revenue", _key("priceToSalesTrailing12Months")),
    "ev_to_ebitda": ("x", "enterprise value / EBITDA", _key("enterpriseToEbitda")),
    "eps_trailing": ("$", "trailing-12-month diluted EPS", _key("trailingEps")),
    "eps_forward": ("$", "next-12-month consensus EPS", _key("forwardEps")),
    "revenue_b": ("$B", "trailing-12-month revenue in billions", _key("totalRevenue", 1e-9)),
    "revenue_growth": ("%", "revenue growth, latest quarter vs a year earlier", _key("revenueGrowth", 100)),
    "earnings_growth": ("%", "EPS growth, latest quarter vs a year earlier", _key("earningsGrowth", 100)),
    "margin_gross": ("%", "gross margin", _key("grossMargins", 100)),
    "margin_operating": ("%", "operating margin", _key("operatingMargins", 100)),
    "margin_net": ("%", "net profit margin", _key("profitMargins", 100)),
    "roe": ("%", "return on equity", _key("returnOnEquity", 100)),
    "roa": ("%", "return on assets", _key("returnOnAssets", 100)),
    "debt_to_equity": ("%", "total debt / equity in percent (150 = 1.5x); absent for most banks", _key("debtToEquity")),
    "current_ratio": ("x", "current assets / current liabilities", _key("currentRatio")),
    "free_cash_flow_b": ("$B", "trailing free cash flow in billions", _key("freeCashflow", 1e-9)),
    "fcf_yield": ("%", "free cash flow / market cap", _ratio("freeCashflow", "marketCap")),
    "dividend_yield": ("%", "forward dividend yield; absent when no dividend", _key("dividendYield")),
    "payout_ratio": ("%", "dividends / earnings", _key("payoutRatio", 100)),
    "beta": ("x", "5-year beta vs the market", _key("beta")),
    "change_52w": ("%", "price change over the last 52 weeks", _key("52WeekChange", 100)),
    "from_52w_high": ("%", "distance below the 52-week high (-20 = 20% below)", _ratio("currentPrice", "fiftyTwoWeekHigh", minus_one=True)),
    "short_float": ("%", "shares sold short / float", _key("shortPercentOfFloat", 100)),
    "inst_ownership": ("%", "held by institutions", _key("heldPercentInstitutions", 100)),
    "analyst_rating": ("score", "mean analyst recommendation: 1 strong buy, 3 hold, 5 sell", _key("recommendationMean")),
    "analyst_count": ("n", "number of analysts covering", _key("numberOfAnalystOpinions")),
    "target_upside": ("%", "mean analyst price target vs current price", _ratio("targetMeanPrice", "currentPrice", minus_one=True)),
}

TEXT_FIELDS = {
    "sector": "GICS sector, one of the listed names",
    "industry": "yfinance industry label, e.g. 'Semiconductors'",
    "name": "company name",
}

SECTORS = tuple(SECTOR_ETFS.values())

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    symbol TEXT PRIMARY KEY,
    row    TEXT NOT NULL           -- JSON: text fields + numeric fields present
);
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""


class Snapshot:
    """The universe as last fetched. Rows are plain dicts."""

    def __init__(self, rows: list[dict[str, Any]], as_of: str | None, failed: list[str]) -> None:
        self.rows = rows
        self.as_of = as_of
        self.failed = failed

    def age_hours(self, now: datetime | None = None) -> float | None:
        if not self.as_of:
            return None
        then = datetime.fromisoformat(self.as_of)
        return ((now or datetime.now(UTC)) - then).total_seconds() / 3600


def snapshot_path() -> Path:
    from genesis.config import load_config

    return load_config().memory.db_path.expanduser().parent / "screener.db"


def row_from_info(symbol: str, info: Info, sector: str | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": symbol,
        "name": info.get("shortName") or info.get("longName") or symbol,
        "sector": sector or info.get("sector"),
        "industry": info.get("industry"),
    }
    for name, (_unit, _meaning, read) in FIELDS.items():
        value = read(info)
        if value is not None:
            row[name] = round(value, 4)
    return row


def _yf_info(symbol: str) -> Info:
    import yfinance as yf

    for attempt in range(3):
        try:
            return yf.Ticker(symbol).info or {}
        except Exception:  # noqa: BLE001 - yfinance raises anything; retried, then reported
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return {}


def build_snapshot(
    path: Path | str | None = None,
    *,
    members: dict[str, str | None] | None = None,
    fetch: Callable[[str], Info] = _yf_info,
    workers: int = 8,
) -> dict[str, Any]:
    """Fetch every member and replace the snapshot. ``members`` is symbol -> sector.

    Replaces only when at least 90% of members came back: a Yahoo outage must
    leave yesterday's snapshot in place, not a table of forty names.
    """
    if members is None:
        from genesis.marketdata.index_map import _holdings, _sector_map

        sectors = _sector_map()
        members = {t: sectors.get(t) for t in _holdings("SPY")["members"]}

    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    failed: list[str] = []

    def one(symbol: str) -> dict[str, Any] | None:
        try:
            info = fetch(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("screener snapshot: %s failed: %s", symbol, exc)
            return None
        return row_from_info(symbol, info, members[symbol]) if info.get("quoteType") or info.get("marketCap") else None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for symbol, row in zip(members, pool.map(one, members)):
            (rows.append(row) if row else failed.append(symbol))

    as_of = datetime.now(UTC).isoformat(timespec="seconds")
    replaced = bool(members) and len(rows) >= 0.9 * len(members)
    if replaced:
        conn = connect(path or snapshot_path())
        conn.executescript(SCHEMA)
        with transaction(conn) as tx:
            tx.execute("DELETE FROM snapshot")
            tx.executemany("INSERT INTO snapshot (symbol, row) VALUES (?, ?)",
                           [(r["symbol"], json.dumps(r)) for r in rows])
            tx.executemany("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)",
                           [("as_of", as_of), ("failed", json.dumps(failed))])
        conn.close()
    return {
        "ok": replaced,
        "members": len(members),
        "fetched": len(rows),
        "failed": failed,
        "as_of": as_of if replaced else None,
        "elapsed_s": round(time.monotonic() - started, 1),
    }


def save_current(payload: dict[str, Any], path: Path | str | None = None) -> None:
    """The screen last run from any door -- chat, ⌘K, voice or the SCR panel.

    One slot, overwritten. The SCR module shows it and the next chat turn edits
    it, which is what keeps a hand edit in the panel and the conversation on the
    same scan.
    """
    conn = connect(path or snapshot_path())
    conn.executescript(SCHEMA)
    with transaction(conn) as tx:
        tx.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('current', ?)",
                   (json.dumps({**payload, "saved_at": datetime.now(UTC).isoformat(timespec="seconds")}, default=str),))
    conn.close()


def load_current(path: Path | str | None = None) -> dict[str, Any] | None:
    target = Path(path) if path else snapshot_path()
    if not target.exists():
        return None
    conn = connect(target)
    conn.executescript(SCHEMA)
    row = conn.execute("SELECT v FROM meta WHERE k = 'current'").fetchone()
    conn.close()
    return json.loads(row[0]) if row else None


def load_snapshot(path: Path | str | None = None) -> Snapshot:
    target = Path(path) if path else snapshot_path()
    if str(target) != ":memory:" and not target.exists():
        return Snapshot([], None, [])
    conn = connect(target)
    conn.executescript(SCHEMA)
    rows = [json.loads(r[0]) for r in conn.execute("SELECT row FROM snapshot ORDER BY symbol")]
    meta = dict(conn.execute("SELECT k, v FROM meta").fetchall())
    conn.close()
    return Snapshot(rows, meta.get("as_of"), json.loads(meta.get("failed", "[]")))
