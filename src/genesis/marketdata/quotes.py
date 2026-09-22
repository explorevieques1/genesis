# Spec: Genesis Markdown/10-Architecture/Market Data Sources.md
"""Daily closes for the watchlist. Tier 3, and labelled as such.

The bar store (``/v1/market/bars``) only holds series Genesis has deliberately
ingested. A watchlist reaches wider than that on purpose, so its red/green
needs a source that answers for any ticker -- which means a public feed, which
means **tier 3**: research and closed-market scaffolding, never a number the
pre-trade risk engine reads. [[Safety Invariants]] §11 keeps tier 1 as the only
feed sizing and stops may touch.

**Settled closes, not a live price.** There is no realtime feed wired to
Genesis, so this reports the last *completed* daily close against the one
before it -- the same day-over-day change the chart panel computes from bars on
disk, and the same stance it takes ("closed bars only"). ``fast_info.last_price``
was the obvious alternative and is the wrong one here: it is a delayed
last-trade that moves intraday, so two rows refreshed a minute apart would
disagree with each other and with every chart on the surface, while looking
authoritative. A close has a date, and the panel shows it.

One ``history`` call per symbol, wrapped in a per-minute TTL cache -- a
watchlist refreshes on demand and a dozen rows must not be a dozen network hits
each time. The cache is generous on purpose: a settled close does not change.
"""

from __future__ import annotations

import time
from typing import Any

from genesis.company.symbols import to_yahoo

__all__ = ["HISTORY_WINDOWS", "day_quotes", "price_history"]

#: symbol -> (time_bucket, payload). Module-level: the daemon is one process
#: and a settled close is the same for every reader of it.
_CACHE: dict[str, tuple[int, dict[str, Any]]] = {}

#: Fifteen minutes. A completed daily close does not change, so the only thing
#: expiry buys is picking up *today's* close once the session settles -- which
#: does not need a tight loop. Refresh in the panel forces a re-read anyway.
_TTL_SEC = 900


def _one(symbol: str) -> dict[str, Any]:
    try:
        import yfinance
    except ImportError:
        return {"error": "yfinance is not installed"}
    try:
        frame = yfinance.Ticker(to_yahoo(symbol)).history(
            period="1mo", interval="1d", auto_adjust=True,
        )
    except Exception as exc:  # noqa: BLE001 - a bad ticker is a row state, not a fault
        return {"error": f"{type(exc).__name__}: {exc}"}
    if frame is None or frame.empty:
        return {"error": "no daily bars"}

    closes = frame["Close"].dropna()
    if len(closes) < 2:
        return {"error": "only one close held — no change to compute"}

    close = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    change = close - prev
    return {
        "close": round(close, 4),
        "prev_close": round(prev, 4),
        "change": round(change, 4),
        "change_pct": round(change / prev * 100, 2) if prev else None,
        # Which session this is. A settled close with no date beside it is a
        # number the operator will read as "now".
        "as_of": closes.index[-1].date().isoformat(),
    }


def day_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """``{symbol: {last, prev_close, change, change_pct, currency}}`` or ``{error}``.

    Keyed by the symbol as passed in, so the caller does not have to track the
    Yahoo spelling.
    """
    now_bucket = int(time.time() // _TTL_SEC)
    out: dict[str, dict[str, Any]] = {}
    for raw in symbols:
        sym = (raw or "").strip().upper()
        if not sym:
            continue
        hit = _CACHE.get(sym)
        if hit and hit[0] == now_bucket:
            out[sym] = hit[1]
            continue
        payload = _one(sym)
        _CACHE[sym] = (now_bucket, payload)
        out[sym] = payload
    return out


#: Window -> yfinance (period, interval). 1D is 5-minute bars, the rest daily
#: or weekly -- enough points for a thumbnail, never enough to trade on.
HISTORY_WINDOWS: dict[str, tuple[str, str]] = {
    "1D": ("1d", "5m"), "YTD": ("ytd", "1d"), "1Y": ("1y", "1d"), "5Y": ("5y", "1wk"),
}
_HISTORY_CACHE: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}


def price_history(symbol: str, window: str) -> dict[str, Any]:
    """Close and volume for the `CO` page's thumbnail chart. Tier 3, cached 15m."""
    sym = (symbol or "").strip().upper()
    if window not in HISTORY_WINDOWS:
        return {"error": f"window must be one of {', '.join(HISTORY_WINDOWS)}"}
    bucket = int(time.time() // _TTL_SEC)
    hit = _HISTORY_CACHE.get((sym, window))
    if hit and hit[0] == bucket:
        return hit[1]
    try:
        import yfinance
    except ImportError:
        return {"error": "yfinance is not installed"}
    period, interval = HISTORY_WINDOWS[window]
    try:
        frame = yfinance.Ticker(to_yahoo(sym)).history(
            period=period, interval=interval, auto_adjust=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    if frame is None or frame.empty:
        return {"error": f"no {window} history for {sym}"}
    frame = frame.dropna(subset=["Close"])
    payload = {
        "symbol": sym, "window": window, "interval": interval, "source": "yfinance",
        "points": [
            {"time": int(ts.timestamp()), "close": round(float(c), 4), "volume": int(v or 0)}
            for ts, c, v in zip(frame.index, frame["Close"], frame["Volume"])
        ],
    }
    _HISTORY_CACHE[(sym, window)] = (bucket, payload)
    return payload


if __name__ == "__main__":  # pragma: no cover - needs network
    import json

    print(json.dumps(day_quotes(["NVDA", "AAPL", "ZZZZNOTREAL"]), indent=2))
