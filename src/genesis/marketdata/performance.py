# Spec: Genesis Markdown/10-Architecture/Market Data Sources.md · 60-UI/Widget Catalog.md
"""Sector and futures performance over four windows -- the `PFM` module's feed.

Two universes, one shape. **Stocks** are the eleven GICS sectors as their SPDR
ETFs; **futures** are the front-month continuous contracts, plus the handful of
cash indices a futures board conventionally shows beside them.

Tier 3 and settled, like everything else in this directory: a public feed, the
last *completed* daily bars, never a number the pre-trade engine reads
([[Safety Invariants]] §11).

**One download per universe.** ``yfinance.download`` batches -- forty-nine
futures in a single call, six months of daily closes, from which all four
windows fall out by indexing. The alternative (a call per symbol per window) is
196 requests for the same numbers.

**Every ticker below was verified against the live feed**, which is not
pedantry: Yahoo answers an unknown future with an empty frame rather than an
error, so an unchecked table produces a board that is quietly missing rows.
Canola, SOFR, ethanol and gasoil have no Yahoo symbol at all and are therefore
absent by decision rather than by accident.

**A cash index is not a future**, and the two are not conflated: ``^VIX``,
``^GDAXI``, ``^STOXX50E``, ``DX-Y.NYB`` and ``BTC-USD`` carry ``kind="index"``,
so the panel can say what settles and what merely closes.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Any
from zoneinfo import ZoneInfo

# The eleven sectors already have one right answer in this repo. Importing it
# rather than retyping it means a sector list cannot drift between the chart
# the data-viz agent draws and the board the operator reads.
from genesis.agents.charting.data_viz import SECTOR_ETFS

__all__ = ["FUTURES", "WINDOWS", "performance"]

#: Window label -> sessions back. Five sessions is a week of *trading*, not a
#: week of calendar -- a Monday-to-Monday calendar week spans a holiday four
#: times a year and would silently compare six sessions to five.
WINDOWS: dict[str, int] = {"1D": 1, "1W": 5, "1M": 21, "3M": 63}

#: symbol -> (display name, board group, kind). Verified 2026-09-07.
FUTURES: dict[str, tuple[str, str, str]] = {
    # Indices — the equity-index futures, then the cash indices shown beside them.
    "ES=F": ("S&P 500", "Indices", "future"),
    "NQ=F": ("Nasdaq 100", "Indices", "future"),
    "YM=F": ("DJIA", "Indices", "future"),
    "RTY=F": ("Russell 2000", "Indices", "future"),
    "NKD=F": ("Nikkei 225", "Indices", "future"),
    "^STOXX50E": ("Euro Stoxx 50", "Indices", "index"),
    "^GDAXI": ("DAX", "Indices", "index"),
    "^VIX": ("VIX", "Indices", "index"),
    # Rates
    "ZQ=F": ("30 Day Fed Funds", "Rates", "future"),
    "ZT=F": ("2 Year Note", "Rates", "future"),
    "ZF=F": ("5 Year Note", "Rates", "future"),
    "ZN=F": ("10 Year Note", "Rates", "future"),
    "TN=F": ("Ultra 10 Year Note", "Rates", "future"),
    "ZB=F": ("30 Year Bond", "Rates", "future"),
    "UB=F": ("Ultra Bond", "Rates", "future"),
    # Energy
    "CL=F": ("Crude Oil WTI", "Energy", "future"),
    "BZ=F": ("Crude Oil Brent", "Energy", "future"),
    "NG=F": ("Natural Gas", "Energy", "future"),
    "RB=F": ("Gasoline RBOB", "Energy", "future"),
    "HO=F": ("Heating Oil", "Energy", "future"),
    # Metals
    "GC=F": ("Gold", "Metals", "future"),
    "SI=F": ("Silver", "Metals", "future"),
    "PL=F": ("Platinum", "Metals", "future"),
    "PA=F": ("Palladium", "Metals", "future"),
    "HG=F": ("Copper", "Metals", "future"),
    "ALI=F": ("Aluminum", "Metals", "future"),
    "TIO=F": ("Iron Ore", "Metals", "future"),
    "HRC=F": ("Steel HRC", "Metals", "future"),
    # Grains
    "ZS=F": ("Soybeans", "Grains", "future"),
    "ZM=F": ("Soybean Meal", "Grains", "future"),
    "ZL=F": ("Soybean Oil", "Grains", "future"),
    "ZC=F": ("Corn", "Grains", "future"),
    "ZW=F": ("Wheat", "Grains", "future"),
    "KE=F": ("KC Wheat", "Grains", "future"),
    "ZR=F": ("Rough Rice", "Grains", "future"),
    "ZO=F": ("Oats", "Grains", "future"),
    # Softs & meats
    "KC=F": ("Coffee", "Softs & Meats", "future"),
    "CC=F": ("Cocoa", "Softs & Meats", "future"),
    "SB=F": ("Sugar", "Softs & Meats", "future"),
    "CT=F": ("Cotton", "Softs & Meats", "future"),
    "OJ=F": ("Orange Juice", "Softs & Meats", "future"),
    "LBR=F": ("Lumber", "Softs & Meats", "future"),
    "LE=F": ("Live Cattle", "Softs & Meats", "future"),
    "GF=F": ("Feeder Cattle", "Softs & Meats", "future"),
    "HE=F": ("Lean Hogs", "Softs & Meats", "future"),
    # Currencies
    "DX-Y.NYB": ("USD", "Currencies", "index"),
    "6E=F": ("EUR", "Currencies", "future"),
    "6J=F": ("JPY", "Currencies", "future"),
    "6B=F": ("GBP", "Currencies", "future"),
    "6C=F": ("CAD", "Currencies", "future"),
    "6S=F": ("CHF", "Currencies", "future"),
    "6A=F": ("AUD", "Currencies", "future"),
    "6N=F": ("NZD", "Currencies", "future"),
    "BTC-USD": ("Bitcoin", "Currencies", "index"),
}

#: The order groups are drawn in. A board whose rows reshuffle between reads is
#: one you cannot read by position, which is most of what a board is for.
FUTURES_GROUPS = ["Indices", "Rates", "Energy", "Metals", "Grains",
                  "Softs & Meats", "Currencies"]

_TTL_SEC = 900
#: asset -> (time_bucket, payload).
_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}


def _universe(asset: str) -> dict[str, tuple[str, str, str]]:
    """symbol -> (display name, group, kind) for the asset class."""
    if asset == "futures":
        return FUTURES
    return {sym: (name, "Sectors", "etf") for sym, name in SECTOR_ETFS.items()}


def _returns(closes: Any) -> dict[str, float] | None:
    """Percent change over each window, or ``None`` if there is no 1D to show.

    A window longer than the history returns ``None`` *for that window only* --
    a newly listed contract has a 1D and no 3M, and dropping the whole row for
    that would lose the one number it does have.
    """
    series = closes.dropna()
    if len(series) < 2:
        return None
    out: dict[str, float | None] = {}
    last = float(series.iloc[-1])
    for label, back in WINDOWS.items():
        if len(series) <= back:
            out[label] = None
            continue
        prior = float(series.iloc[-1 - back])
        out[label] = round((last - prior) / prior * 100, 2) if prior else None
    return out  # type: ignore[return-value]


def performance(asset: str = "stocks") -> dict[str, Any]:
    """``{asset, as_of, windows, groups, rows, missing}``."""
    asset = "futures" if asset == "futures" else "stocks"
    bucket = int(time.time() // _TTL_SEC)
    hit = _CACHE.get(asset)
    if hit and hit[0] == bucket:
        return hit[1]

    try:
        import yfinance
    except ImportError:
        return {"error": "yfinance is not installed"}

    universe = _universe(asset)
    try:
        frame = yfinance.download(
            list(universe), period="6mo", interval="1d", auto_adjust=True,
            progress=False, threads=True, group_by="column",
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if frame is None or frame.empty:
        return {"error": "the feed returned no bars for the whole universe"}

    closes = frame["Close"]
    rows, missing = [], []
    for symbol, (name, group, kind) in universe.items():
        # An unknown symbol is an absent column, not an exception. Yahoo is
        # happy to answer a made-up future with silence.
        series = closes[symbol] if symbol in closes.columns else None
        returns = _returns(series) if series is not None else None
        if returns is None:
            missing.append(symbol)
            continue
        rows.append({
            "symbol": symbol, "name": name, "group": group, "kind": kind,
            "last": round(float(series.dropna().iloc[-1]), 4),
            "returns": returns,
        })

    order = FUTURES_GROUPS if asset == "futures" else ["Sectors"]
    last_bar = closes.dropna(how="all").index[-1].date()
    payload = {
        "asset": asset,
        # The session these closes belong to. Not "now" -- a settled close with
        # no date beside it is a number the operator will read as live.
        "as_of": str(last_bar),
        # **Whether that last bar is finished.** Equities and futures disagree
        # here far more often than they agree: a Globex session opens Sunday
        # evening and is dated for the *following* day, so on a Monday holiday
        # the sector board shows Friday's settled close while the futures board
        # shows a session still trading. Claiming both are "the close" would be
        # a number that moves under a label saying it cannot -- so the panel is
        # told which it has, and says so.
        "settled": last_bar < dt.datetime.now(ZoneInfo("America/New_York")).date(),
        "windows": list(WINDOWS),
        "groups": [g for g in order if any(r["group"] == g for r in rows)],
        "rows": rows,
        "missing": missing,
    }
    _CACHE[asset] = (bucket, payload)
    return payload


if __name__ == "__main__":  # pragma: no cover - needs network
    for which in ("stocks", "futures"):
        out = performance(which)
        assert "error" not in out, out
        assert out["rows"], out
        assert not out["missing"], f"unresolved tickers: {out['missing']}"
        best = max(out["rows"], key=lambda r: r["returns"]["1D"] or -99)
        print(f"{which:8} {len(out['rows']):3} rows · as of {out['as_of']} · "
              f"groups {out['groups']}")
        print(f"         best 1D: {best['name']} {best['returns']['1D']:+.2f}%")
