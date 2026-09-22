# Spec: Genesis Markdown/10-Architecture/Market Data Sources.md · 60-UI/Widget Catalog.md
"""The Nasdaq-100 on the day, as area-by-market-cap and colour-by-change.

Same stance as ``quotes.py`` next door, and for the same reasons: this is a
public feed, so it is **tier 3** -- research and closed-market scaffolding,
never a number the pre-trade risk engine reads ([[Safety Invariants]] §11).
And it is the **settled session**: after the close ``regularMarketPrice`` is
that close and ``regularMarketPreviousClose`` is the one before it, which is
the same day-over-day change the watchlist and the chart panel show. Before the
close it is a delayed last trade, and the payload says which by carrying the
market state Yahoo reports.

**Why the screener and not 100 quote calls.** ``fast_info`` costs ~2.5s per
ticker; a hundred of those is four minutes. Yahoo's equity screener returns 250
rows -- symbol, market cap, change -- in under half a second, so four pages
cover the whole of NASDAQ's national market and everything here is one lookup
in that. The handful of members the screener misses fall back to ``fast_info``,
which at five symbols costs seconds rather than minutes.

**Membership is a static table and has to be.** No free feed publishes index
constituents, and asking a model which stocks are in the Nasdaq-100 is exactly
the confabulation [[Safety Invariants]] §10 forbids. So it lives below, with
its sector, and it is *hand-corrected* -- the index is reconstituted each
December. A name that has left the index or the exchange returns no data and is
reported in ``missing`` rather than drawn as a zero-change tile.
"""

from __future__ import annotations

import time
from typing import Any

__all__ = ["NASDAQ_100", "nasdaq_100_heatmap"]

#: Ticker -> GICS sector. The index as reconstituted December 2025.
#:
#: Correct this by hand when the index changes; the panel renders whatever is
#: here and reports what it could not price, so a stale entry shows up as a
#: name in ``missing`` rather than a wrong tile.
NASDAQ_100: dict[str, str] = {
    # Information Technology
    "NVDA": "Information Technology", "AAPL": "Information Technology",
    "MSFT": "Information Technology", "AVGO": "Information Technology",
    "AMD": "Information Technology", "QCOM": "Information Technology",
    "TXN": "Information Technology", "INTU": "Information Technology",
    "AMAT": "Information Technology", "LRCX": "Information Technology",
    "KLAC": "Information Technology", "ADI": "Information Technology",
    "MU": "Information Technology", "PANW": "Information Technology",
    "CRWD": "Information Technology", "SNPS": "Information Technology",
    "CDNS": "Information Technology", "MRVL": "Information Technology",
    "ADBE": "Information Technology", "NXPI": "Information Technology",
    "ROP": "Information Technology", "FTNT": "Information Technology",
    "ON": "Information Technology", "CDW": "Information Technology",
    "GFS": "Information Technology", "ARM": "Information Technology",
    "APP": "Information Technology", "ZS": "Information Technology",
    "TEAM": "Information Technology", "DDOG": "Information Technology",
    "WDAY": "Information Technology", "MDB": "Information Technology",
    "INTC": "Information Technology", "CSCO": "Information Technology",
    "ASML": "Information Technology", "SNDK": "Information Technology",
    "STX": "Information Technology", "PLTR": "Information Technology",
    "CTSH": "Information Technology", "TTD": "Information Technology",
    # Communication Services
    "GOOGL": "Communication Services", "GOOG": "Communication Services",
    "META": "Communication Services", "NFLX": "Communication Services",
    "CMCSA": "Communication Services", "TMUS": "Communication Services",
    "CHTR": "Communication Services", "TTWO": "Communication Services", "WBD": "Communication Services",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "BKNG": "Consumer Discretionary", "MELI": "Consumer Discretionary",
    "ABNB": "Consumer Discretionary", "ORLY": "Consumer Discretionary",
    "ROST": "Consumer Discretionary", "LULU": "Consumer Discretionary",
    "MAR": "Consumer Discretionary", "DASH": "Consumer Discretionary",
    "SBUX": "Consumer Discretionary",
    # Consumer Staples
    "COST": "Consumer Staples", "PEP": "Consumer Staples",
    "MDLZ": "Consumer Staples", "MNST": "Consumer Staples",
    "KDP": "Consumer Staples", "KHC": "Consumer Staples",
    "CCEP": "Consumer Staples",
    # Health Care
    "AMGN": "Health Care", "GILD": "Health Care", "VRTX": "Health Care",
    "REGN": "Health Care", "ISRG": "Health Care", "IDXX": "Health Care",
    "BIIB": "Health Care", "GEHC": "Health Care", "AZN": "Health Care",
    "DXCM": "Health Care",
    # Industrials
    "HON": "Industrials", "ADP": "Industrials", "CTAS": "Industrials",
    "PAYX": "Industrials", "FAST": "Industrials", "ODFL": "Industrials",
    "CSX": "Industrials", "PCAR": "Industrials", "VRSK": "Industrials",
    "CPRT": "Industrials", "AXON": "Industrials",
    # Energy · Utilities · Materials · Financials · Real Estate
    "FANG": "Energy", "BKR": "Energy",
    "AEP": "Utilities", "XEL": "Utilities", "EXC": "Utilities",
    "CEG": "Utilities",
    "LIN": "Materials",
    "PYPL": "Financials", "MSTR": "Financials",
    "CSGP": "Real Estate",
}

#: Fifteen minutes, matching ``quotes.py``. A settled close does not change, so
#: expiry only buys picking up today's once the session ends -- and the panel
#: has a refresh for when you want it sooner.
_TTL_SEC = 900

#: (time_bucket, payload). Module level: one daemon process, one settled close.
_CACHE: tuple[int, dict[str, Any]] | None = None


def _screened(
    exchanges: tuple[str, ...] = ("NMS",), pages: int = 4,
) -> dict[str, dict[str, Any]]:
    """Every name on ``exchanges`` by market cap, ``pages`` x 250 deep.

    A thousand NASDAQ rows reaches well below the smallest index member, so this
    is a superset in practice; anything it still misses is handled by the caller.
    """
    import yfinance

    rows: dict[str, dict[str, Any]] = {}
    for offset in range(0, pages * 250, 250):
        page = yfinance.screen(
            yfinance.EquityQuery("is-in", ["exchange", *exchanges]),
            sortField="intradaymarketcap", sortAsc=False, size=250, offset=offset,
        )
        for quote in page.get("quotes", []):
            symbol = quote.get("symbol")
            if symbol:
                rows[symbol] = quote
    return rows


def _row(symbol: str, quote: dict[str, Any]) -> dict[str, Any] | None:
    """One tile, or ``None`` when the feed cannot price it.

    Area needs a market cap and colour needs a change; a tile missing either is
    a lie in whichever channel it is missing, so it is dropped rather than
    defaulted to zero.
    """
    cap = quote.get("marketCap")
    close = quote.get("regularMarketPrice")
    prev = quote.get("regularMarketPreviousClose")
    if not cap or close is None or not prev:
        return None
    return {
        "symbol": symbol,
        "name": quote.get("shortName") or symbol,
        "sector": NASDAQ_100[symbol],
        "market_cap": float(cap),
        "close": round(float(close), 4),
        "prev_close": round(float(prev), 4),
        "change_pct": round((float(close) - float(prev)) / float(prev) * 100, 2),
    }


def _fallback(symbol: str) -> dict[str, Any] | None:
    """``fast_info`` for a member the screener did not return."""
    import yfinance

    try:
        info = yfinance.Ticker(symbol).fast_info
        return _row(symbol, {
            "marketCap": info.get("marketCap"),
            "regularMarketPrice": info.get("lastPrice"),
            "regularMarketPreviousClose": info.get("previousClose"),
        })
    except Exception:  # noqa: BLE001 - a delisted member is a row state, not a fault
        return None


def nasdaq_100_heatmap() -> dict[str, Any]:
    """``{as_of, market_state, rows, missing}`` for the whole index."""
    global _CACHE
    bucket = int(time.time() // _TTL_SEC)
    if _CACHE and _CACHE[0] == bucket:
        return _CACHE[1]

    try:
        import yfinance  # noqa: F401
    except ImportError:
        return {"error": "yfinance is not installed"}
    try:
        screened = _screened()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}

    rows, missing = [], []
    for symbol in NASDAQ_100:
        quote = screened.get(symbol)
        row = _row(symbol, quote) if quote else _fallback(symbol)
        (rows.append(row) if row else missing.append(symbol))

    # Whose session this is. "REGULAR" means these are delayed last trades and
    # will still move; "CLOSED"/"POST" means they are the settled close.
    states = {q.get("marketState") for q in screened.values() if q.get("marketState")}
    payload = {
        "index": "Nasdaq-100",
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "market_state": states.pop() if len(states) == 1 else "UNKNOWN",
        "rows": sorted(rows, key=lambda r: -r["market_cap"]),
        "missing": missing,
    }
    _CACHE = (bucket, payload)
    return payload


if __name__ == "__main__":  # pragma: no cover - needs network
    out = nasdaq_100_heatmap()
    assert "error" not in out, out
    assert len(out["rows"]) >= 90, f"only {len(out['rows'])} of {len(NASDAQ_100)} priced"
    assert {r["sector"] for r in out["rows"]} <= set(NASDAQ_100.values())
    assert all(-99 < r["change_pct"] < 99 for r in out["rows"])
    biggest = out["rows"][0]
    print(f"{len(out['rows'])} rows · {out['market_state']} · missing {out['missing']}")
    print(f"largest: {biggest['symbol']} {biggest['market_cap']:,.0f} {biggest['change_pct']:+.2f}%")
