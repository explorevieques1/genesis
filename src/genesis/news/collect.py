# Spec: Genesis Markdown/20-Agents/Research/Agent — News Collector.md
"""Gathering headlines and reading articles. Deterministic, tier none.

**Afferent only.** This reaches out to yfinance and to article pages, and writes
nothing but ``news.db``. No model is anywhere in this file: deciding what a
story *means* is [[Agent — News And Catalyst]]'s job, and a collector that
summarised would be a reflex with an opinion.

**Tier 4, untrusted text.** Titles and summaries are stored as they arrived and
fenced at the moment they meet a prompt (``mcp.fence.wrap``), not here -- the
reader shows the trader the original words.

yfinance is the only source because it is the only news feed already
integrated that needs no key. ``Ticker(sym).news`` gives ~10 stories per
symbol; ``Search(q).news`` covers subjects with no ticker ("federal reserve").
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.parse import urljoin

from genesis.news.econ import refresh as refresh_events
from genesis.news.store import NewsStore

__all__ = ["MARKET_SYMBOLS", "collect", "default_symbols", "parse", "read_article"]

log = logging.getLogger(__name__)

#: Broad-market proxies: their yfinance news is the market's news, not one company's.
MARKET_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ", "DIA", "IWM", "TLT", "GLD", "USO", "^VIX")
#: Subjects no ticker covers.
MARKET_QUERIES: tuple[str, ...] = ("stock market", "federal reserve", "economy")
#: ponytail: watchlist symbols capped at 40 per run; widen when rate limits allow.
MAX_WATCHLIST = 40

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def _iso(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC).isoformat(timespec="seconds")
    except ValueError:
        return ""


def parse(entry: Any, symbol: str | None = None) -> dict[str, Any] | None:
    """One yfinance story, either shape (``Ticker.news`` wraps in ``content``; ``Search`` is flat)."""
    if not isinstance(entry, dict):
        return None
    c = entry.get("content") if isinstance(entry.get("content"), dict) else entry
    title = str(c.get("title") or "").strip()
    canonical = (c.get("canonicalUrl") or {}).get("url") or ""
    click = (c.get("clickThroughUrl") or {}).get("url") or c.get("link") or ""
    url = canonical or click
    published = _iso(c.get("pubDate") or c.get("providerPublishTime") or "")
    if not title or not url or not published:
        return None
    thumbs = ((c.get("thumbnail") or {}).get("resolutions") or [])
    related = [str(t).upper() for t in (entry.get("relatedTickers") or []) if t]
    return {
        "url": url,
        "alt_url": click if click != url else "",
        "title": title[:300],
        "publisher": str((c.get("provider") or {}).get("displayName") or c.get("publisher") or "unknown"),
        "published": published,
        "summary": str(c.get("summary") or c.get("description") or "")[:1500],
        "symbols": sorted({*([symbol.upper()] if symbol else []), *related}),
        "thumbnail": str(thumbs[-1].get("url") or "") if thumbs else "",
        "source": "yfinance",
    }


def default_symbols() -> list[str]:
    """Market proxies, then every watchlist symbol."""
    symbols = list(MARKET_SYMBOLS)
    try:
        from pathlib import Path

        from genesis.config import load_config
        from genesis.watchlist.store import WatchlistStore

        path = Path(load_config().memory.db_path).expanduser().parent / "watchlists.db"
        for wl in WatchlistStore(path=path).lists():
            for m in wl["members"]:
                if m["symbol"] not in symbols:
                    symbols.append(m["symbol"])
    except Exception as exc:  # noqa: BLE001 - no watchlists is market news only, not a failure
        log.debug("watchlists unavailable for news: %s", exc)
    return symbols[: len(MARKET_SYMBOLS) + MAX_WATCHLIST]


def collect(
    store: NewsStore,
    symbols: Iterable[str] | None = None,
    queries: Iterable[str] | None = None,
    *,
    per_source: int = 10,
) -> dict[str, Any]:
    """Fetch every source, store what is new, log the run. Never raises on a source."""
    import yfinance as yf

    symbols = [s.strip().upper() for s in (default_symbols() if symbols is None else symbols) if s.strip()]
    queries = [q.strip() for q in (MARKET_QUERIES if queries is None else queries) if q.strip()]

    def by_symbol(sym: str) -> list[dict[str, Any]]:
        return [p for p in (parse(e, sym) for e in (yf.Ticker(sym).news or [])[:per_source]) if p]

    def by_query(q: str) -> list[dict[str, Any]]:
        return [p for p in (parse(e) for e in (yf.Search(q, news_count=per_source).news or [])) if p]

    jobs = [(s, by_symbol) for s in symbols] + [(q, by_query) for q in queries]
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [(name, pool.submit(fn, name)) for name, fn in jobs]
        for name, future in futures:
            try:
                items.extend(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {type(exc).__name__}: {exc}"[:200])

    new = store.add(items)
    # The red-folder calendar rides the same run rather than carrying its own
    # cron: one afferent pass, one log line. It is rate-limited to once every
    # `econ.STALE_HOURS` inside `refresh`, so the 15-minute cadence does not
    # become a 15-minute poll of somebody else's server, and it never raises --
    # a calendar the vendor would not serve must not fail the headlines.
    econ = refresh_events(store)

    # A run where most sources failed is a failed run, even if a few answered.
    # The calendar is not one of those sources: it is visible in the detail, but
    # a 404 from it does not make the headlines a failed collection.
    ok = bool(jobs) and len(errors) <= len(jobs) // 2
    errors = errors + econ["errors"]
    detail = "; ".join(errors[:5]) + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else "")
    store.log_collection(ok=ok, sources=len(jobs), fetched=len(items), new=new, detail=detail)
    return {"ok": ok, "sources": len(jobs), "fetched": len(items), "new": new,
            "errors": errors, "econ": econ}


def read_article(url: str, *, max_redirects: int = 5, timeout: float = 15.0) -> str:
    """The readable text of one article page, or ``""``.

    Redirects are followed by hand so every hop passes ``check_url`` -- a page
    that redirects to 127.0.0.1 is the whole SSRF attack, and httpx's own
    follow would not ask.
    """
    import httpx
    from bs4 import BeautifulSoup

    from genesis.mcp.fence import check_url

    for _ in range(max_redirects + 1):
        check_url(url)
        response = httpx.get(url, headers=_UA, timeout=timeout, follow_redirects=False)
        if response.is_redirect and response.headers.get("location"):
            url = urljoin(url, response.headers["location"])
            continue
        response.raise_for_status()
        break
    else:
        raise ValueError(f"too many redirects for {url}")

    # ponytail: paragraph scrape; add trafilatura if pages come back as boilerplate.
    soup = BeautifulSoup(response.text, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        tag.decompose()
    root = soup.find("article") or soup.body or soup
    paragraphs = [" ".join(p.get_text(" ", strip=True).split()) for p in root.find_all("p")]
    return "\n\n".join(p for p in paragraphs if len(p) > 40)[:40000]


def demo() -> None:
    wrapped = {"content": {"title": "AI drives earnings", "pubDate": "2026-09-13T18:00:24Z",
                           "provider": {"displayName": "24/7 Wall St."},
                           "canonicalUrl": {"url": "https://247wallst.com/x"},
                           "clickThroughUrl": {"url": "https://finance.yahoo.com/x"},
                           "summary": "s"}}
    item = parse(wrapped, "spy")
    assert item and item["symbols"] == ["SPY"] and item["published"] == "2026-09-13T18:00:24+00:00"
    assert item["url"] == "https://247wallst.com/x" and item["alt_url"] == "https://finance.yahoo.com/x"
    flat = {"title": "Fed", "publisher": "IBD", "link": "https://finance.yahoo.com/m/1",
            "providerPublishTime": 1789315899, "relatedTickers": ["tlt"]}
    item = parse(flat)
    assert item and item["symbols"] == ["TLT"] and item["alt_url"] == ""
    assert parse({"content": {"title": "no url"}}) is None
    print("news collect: ok")


if __name__ == "__main__":
    demo()
