# Spec: Genesis Markdown/60-UI/Index Movers.md
"""Who is carrying an index today: members by weight, coloured by change.

**Membership comes from the fund, not from memory.** State Street publishes the
daily holdings of SPY, DIA and every Select Sector SPDR as an xlsx -- ticker,
weight, as-of date. That is the constituent list the ETF actually holds, which
is as close to the index as free data gets, and the weights *are* the slice
sizes. No model, and no hand-typed 500-name table (see ``heatmap.py`` for why a
model asked "what is in the S&P" is the wrong source).

The Nasdaq-100 is the exception: Invesco publishes no plain QQQ file, so it uses
the hand-corrected table in ``heatmap.py`` with market-cap weights, and the
payload's ``weight_basis`` says which kind of weight you are looking at.

Sectors for S&P members come from *which sector SPDR holds them* -- the eleven
funds partition the S&P 500 by GICS sector, so the union is the sector map.

Tier 3 throughout. Changes are the screener's session change; before the close
they are delayed trades and ``market_state`` says so.
"""

from __future__ import annotations

import io
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from genesis.agents.charting.data_viz import SECTOR_ETFS
from genesis.marketdata.heatmap import NASDAQ_100, _screened

__all__ = ["UNIVERSES", "index_map"]

#: code -> (display name, SPDR fund whose holdings define it, or None).
UNIVERSES: dict[str, tuple[str, str | None]] = {
    "SPX": ("S&P 500", "SPY"),
    "NDX": ("Nasdaq-100", None),
    "DJIA": ("Dow Jones", "DIA"),
    # Small caps: the Russell 2000 would be the natural pick, but iShares serves
    # its holdings file only to a browser, so the S&P 600 -- same asset class,
    # same SSGA feed as everything else here -- is the universe we can actually
    # source. Its members sit below the screener's first 1,500 names, hence the
    # deeper quote pull in ``index_map``.
    "SML": ("S&P 600 Small Cap", "SPSM"),
    **{etf: (name, etf) for etf, name in SECTOR_ETFS.items()},
}

_SSGA = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/"
    "etfs/us/holdings-daily-us-en-{fund}.xlsx"
)
_HOLDINGS_TTL = 12 * 3600  # published once a day
_QUOTES_TTL = 900
_holdings_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_quotes_cache: dict[int, tuple[int, dict[str, dict[str, Any]]]] = {}
_EQUITY = re.compile(r"[A-Z]{1,5}([.\-][A-Z])?")
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _xlsx_rows(blob: bytes) -> list[list[str]]:
    """First sheet as rows of strings. Stdlib only -- shared strings, inline
    strings and numbers are all these files use."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
    rows = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(f"{{{_NS['m']}}}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", _NS):
            col = 0
            for ch in c.get("r", "A").rstrip("0123456789"):
                col = col * 26 + ord(ch) - 64
            kind, v = c.get("t"), c.find("m:v", _NS)
            if kind == "s" and v is not None:
                cells[col - 1] = shared[int(v.text or 0)]
            elif kind == "inlineStr":
                cells[col - 1] = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            elif v is not None:
                cells[col - 1] = v.text or ""
        rows.append([cells.get(i, "") for i in range(max(cells, default=-1) + 1)])
    return rows


def parse_holdings(blob: bytes) -> dict[str, Any]:
    """``{as_of, members: {ticker: (name, weight)}}`` from one SSGA file."""
    rows = _xlsx_rows(blob)
    as_of = next((r[1].removeprefix("As of ").strip() for r in rows if r and r[0] == "Holdings:" and len(r) > 1), None)
    header = next(i for i, r in enumerate(rows) if "Ticker" in r and "Weight" in r)
    cols = {name: j for j, name in enumerate(rows[header])}
    members: dict[str, tuple[str, float]] = {}
    for r in rows[header + 1:]:
        ticker = r[cols["Ticker"]].strip() if len(r) > cols["Weight"] else ""
        # Cash, index futures (`IXPU6`), placeholder ids (`2682320D`) and footer
        # lines: not an exchange ticker, so not a member to price.
        if not _EQUITY.fullmatch(ticker) or not r[cols["Weight"]]:
            continue
        try:
            weight = float(r[cols["Weight"]])
        except ValueError:
            continue
        members[ticker.replace(".", "-")] = (r[cols["Name"]].strip(), weight)
    return {"as_of": as_of, "members": members}


def _holdings(fund: str) -> dict[str, Any]:
    hit = _holdings_cache.get(fund)
    if hit and time.time() - hit[0] < _HOLDINGS_TTL:
        return hit[1]
    request = urllib.request.Request(_SSGA.format(fund=fund.lower()), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        parsed = parse_holdings(response.read())
    if not parsed["members"]:
        raise ValueError(f"{fund} holdings file had no members")
    _holdings_cache[fund] = (time.time(), parsed)
    return parsed


def _sector_map() -> dict[str, str]:
    with ThreadPoolExecutor(max_workers=6) as pool:
        files = dict(zip(SECTOR_ETFS, pool.map(_holdings, SECTOR_ETFS)))
    return {t: SECTOR_ETFS[etf] for etf, f in files.items() for t in f["members"]}


def _quotes(pages: int = 6) -> dict[str, dict[str, Any]]:
    """NASDAQ + NYSE + Cboe + NYSE American, ``pages`` x 250 deep by market cap.

    Six pages is ~1.5s and covers every S&P 500 member but a handful. Small-cap
    universes start where that ends, so they ask for twenty.
    """
    bucket = int(time.time() // _QUOTES_TTL)
    hit = _quotes_cache.get(pages)
    if hit and hit[0] == bucket:
        return hit[1]
    rows = _screened(("NMS", "NYQ", "BTS", "ASE", "NGM", "NCM"), pages=pages)
    _quotes_cache[pages] = (bucket, rows)
    return rows


def _change(symbol: str, quote: dict[str, Any] | None) -> dict[str, Any] | None:
    if quote is None:
        import yfinance

        try:
            info = yfinance.Ticker(symbol).fast_info
            quote = {"regularMarketPrice": info.get("lastPrice"),
                     "regularMarketPreviousClose": info.get("previousClose"),
                     "marketCap": info.get("marketCap"),
                     "regularMarketVolume": info.get("lastVolume")}
        except Exception:  # noqa: BLE001 - an unpriceable member is a row state
            return None
    close, prev = quote.get("regularMarketPrice"), quote.get("regularMarketPreviousClose")
    if close is None or not prev:
        return None
    volume = quote.get("regularMarketVolume")
    return {
        "close": round(float(close), 4),
        "change_pct": round((float(close) - float(prev)) / float(prev) * 100, 2),
        "market_cap": float(quote["marketCap"]) if quote.get("marketCap") else None,
        "volume": int(volume) if volume else None,
        "dollar_volume": round(float(close) * float(volume)) if volume else None,
        "quote_name": quote.get("shortName"),
    }


def summarise_group(rows: list[dict[str, Any]], top: int = 5) -> dict[str, Any]:
    """Weight, weighted change, and the top/bottom ``top`` of one set of rows.

    The weighted change is the members' move, not the ETF's print -- close to
    it, not equal (cash, fees, and whichever members could not be priced).
    """
    weight = sum(r["weight"] for r in rows)
    ranked = sorted(rows, key=lambda r: r["change_pct"], reverse=True)
    return {
        "count": len(rows),
        "weight": round(weight, 4),
        "change_pct": round(sum(r["weight"] * r["change_pct"] for r in rows) / weight, 2) if weight else None,
        "advancers": sum(r["change_pct"] > 0 for r in rows),
        "decliners": sum(r["change_pct"] < 0 for r in rows),
        "gainers": [r for r in ranked[:top] if r["change_pct"] > 0],
        "losers": [r for r in reversed(ranked[-top:]) if r["change_pct"] < 0],
    }


def index_map(code: str) -> dict[str, Any]:
    """``{code, index, rows, total, sectors, missing, ...}`` or ``{error}``."""
    code = code.upper()
    if code not in UNIVERSES:
        return {"error": f"unknown index {code}; one of {', '.join(UNIVERSES)}"}
    name, fund = UNIVERSES[code]
    try:
        quotes = _quotes(20 if code == "SML" else 6)
        if fund is None:
            members = {t: (None, None) for t in NASDAQ_100}
            sectors, holdings_as_of, basis = dict(NASDAQ_100), None, "market cap"
        else:
            held = _holdings(fund)
            members, holdings_as_of, basis = held["members"], held["as_of"], f"{fund} holdings weight"
            # Only the S&P 500 (and the Dow, a subset of it) is partitioned by the
            # sector SPDRs; anything else is one group under its own name.
            sectors = _sector_map() if code in ("SPX", "DJIA") else {t: name for t in members}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}

    rows, missing = [], []
    for ticker, (holding_name, weight) in members.items():
        priced = _change(ticker, quotes.get(ticker))
        if priced is None or (weight is None and priced["market_cap"] is None):
            missing.append(ticker)
            continue
        rows.append({
            "symbol": ticker,
            "name": priced["quote_name"] or holding_name or ticker,
            "sector": sectors.get(ticker, "Other"),
            "weight": weight if weight is not None else priced["market_cap"],
            "close": priced["close"],
            "change_pct": priced["change_pct"],
            "market_cap": priced["market_cap"],
            "volume": priced["volume"],
            "dollar_volume": priced["dollar_volume"],
        })
    if fund is None:  # market caps -> percent of the priced total
        total_cap = sum(r["weight"] for r in rows) or 1
        for r in rows:
            r["weight"] = round(r["weight"] / total_cap * 100, 4)

    by_sector: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_sector.setdefault(r["sector"], []).append(r)
    states = {q.get("marketState") for q in quotes.values() if q.get("marketState")}
    return {
        "code": code,
        "index": name,
        "weight_basis": basis,
        "holdings_as_of": holdings_as_of,
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "market_state": states.pop() if len(states) == 1 else "UNKNOWN",
        "rows": sorted(rows, key=lambda r: -r["weight"]),
        "total": summarise_group(rows),
        "sectors": dict(sorted(
            ((s, summarise_group(rs)) for s, rs in by_sector.items()),
            key=lambda kv: -kv[1]["weight"],
        )),
        "missing": missing,
        "universes": [{"code": c, "name": n} for c, (n, _) in UNIVERSES.items()],
    }


if __name__ == "__main__":  # pragma: no cover - needs network
    for c in ("DJIA", "XLE", "SPX", "NDX", "SML"):
        t = time.time()
        out = index_map(c)
        assert "error" not in out, out
        tot = out["total"]
        print(f"{c}: {tot['count']} priced, missing {out['missing']}, {tot['change_pct']:+.2f}% "
              f"· top {[g['symbol'] for g in tot['gainers']]} · {time.time() - t:.1f}s")
