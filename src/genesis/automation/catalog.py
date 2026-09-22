# Spec: Genesis Markdown/60-UI/Automation.md §Node library
"""The palette: every node a person can drop on the canvas, grouped by category.

Four sources, one list:

- **Tool nodes** — curated read capabilities from the gateway catalogue. Each
  compiles to a ``gather`` step with its capability fixed; its settings form is
  built from the tool's own JSON Schema at edit time, so no argument name is
  guessed here.
- **Built-in nodes** — :data:`genesis.automation.actions.ACTIONS`.
- **Classic nodes** — the four original step kinds (check, refresh, call any
  tool, run any agent), kept as the escape hatch for anything uncurated.
- **Processes** — your own workflows with an *on-demand* trigger, callable as
  one step from any other workflow. This is how a custom process is made: build
  it once, then use it like a node.

Every tool node must sit inside :data:`WORKFLOW_GRANT`; a test holds that, so
the palette can never offer a node the runtime would refuse.
"""

from __future__ import annotations

from typing import Any

from genesis.automation.actions import ACTIONS, CATEGORIES

__all__ = ["TOOL_NODES", "nodes"]

#: (capability, category, label, description)
TOOL_NODES: tuple[tuple[str, str, str, str], ...] = (
    # market data
    ("market-data.quote", "market", "Live quote", "Real-time quote from the market data server."),
    ("market-data.quotes", "market", "Quotes (several)", "Quotes for a list of symbols in one call."),
    ("market-data.snapshot", "market", "Market snapshot", "Price, volume and day stats for a symbol."),
    ("market-data.ohlcv", "market", "OHLCV bars", "Raw price bars for a symbol and interval."),
    ("market-data.ohlcv-batch", "market", "OHLCV bars (batch)", "Bars for many symbols at once."),
    ("market-data.overview", "market", "Market overview", "Indexes, breadth and sector moves."),
    ("market-data.search", "market", "Symbol search", "Find tickers by name."),
    # news & sentiment
    ("news.company", "news", "Company news", "Recent headlines for one company."),
    ("news.market", "news", "Market news", "Broad market headlines."),
    ("news.headlines", "news", "Financial headlines", "Headlines from TradingView's news feed."),
    ("ta.sentiment", "news", "Market sentiment", "Sentiment read for a symbol."),
    # fundamentals & analysts
    ("fundamentals.snapshot", "fundamentals", "Fundamentals snapshot", "Valuation, margins and growth at a glance."),
    ("fundamentals.metrics", "fundamentals", "Key metrics", "Ratios and per-share metrics."),
    ("fundamentals.statements", "fundamentals", "Financial statements", "Income, balance and cash flow."),
    ("fundamentals.income", "fundamentals", "Income statement", "Revenue, margins, EPS by period."),
    ("fundamentals.balance", "fundamentals", "Balance sheet", "Assets, liabilities, equity."),
    ("fundamentals.cashflow", "fundamentals", "Cash flow", "Operating, investing, financing flows."),
    ("fundamentals.earnings", "fundamentals", "Earnings history", "Reported vs expected EPS."),
    ("fundamentals.eps-history", "fundamentals", "EPS history", "Per-share earnings over time."),
    ("analyst.recommendations", "fundamentals", "Analyst ratings", "Buy / hold / sell counts over time."),
    ("analyst.consensus", "fundamentals", "Analyst consensus", "Consensus rating and estimates."),
    ("analyst.price-target", "fundamentals", "Price targets", "Analyst price targets."),
    ("analyst.forward-eps", "fundamentals", "Forward EPS", "Forward earnings estimates."),
    ("corporate.dividends", "fundamentals", "Dividends", "Dividend history for a company."),
    ("corporate.splits", "fundamentals", "Splits", "Stock split history."),
    # SEC filings
    ("filings.recent", "filings", "Recent filings", "Latest SEC filings for a company."),
    ("filings.material-event", "filings", "Material events (8-K)", "Current reports: deals, departures, guidance."),
    ("filings.insider", "filings", "Insider trades", "Form 4 insider transactions."),
    ("filings.insider-summary", "filings", "Insider summary", "Net insider buying and selling."),
    ("filings.financials", "filings", "Reported financials", "Financials as filed with the SEC."),
    ("filings.metrics", "filings", "Filing metrics", "Key metrics from XBRL facts."),
    ("filings.compare", "filings", "Compare companies", "Side-by-side filing metrics."),
    ("filings.sections", "filings", "Filing sections", "Pull sections (risk factors, MD&A) from a filing."),
    # calendars & macro
    ("calendar.earnings", "calendar", "Earnings calendar", "Upcoming earnings reports."),
    ("calendar.economic", "calendar", "Economic calendar", "CPI, jobs, GDP and other releases."),
    ("calendar.events", "calendar", "Corporate events", "Investor days, conferences, AGMs."),
    ("calendar.dividends", "calendar", "Dividend calendar", "Upcoming ex-dividend dates."),
    ("calendar.splits", "calendar", "Split calendar", "Upcoming stock splits."),
    ("calendar.ipo", "calendar", "IPO calendar", "Upcoming listings."),
    ("macro.series", "calendar", "FRED series", "Any FRED economic series."),
    ("macro.search", "calendar", "Search FRED", "Find an economic series by keyword."),
    ("macro.release-calendar", "calendar", "Data release calendar", "When economic data is published."),
    ("macro.interest-rates", "calendar", "Interest rates", "Policy and market rates."),
    ("macro.fomc", "calendar", "FOMC", "Fed meeting dates and decisions."),
    ("macro.indicators", "calendar", "Macro indicators", "Headline macro indicators by country."),
    # screeners
    ("screen.gainers", "screeners", "Top gainers", "Biggest percentage gainers today."),
    ("screen.losers", "screeners", "Top losers", "Biggest percentage losers today."),
    ("screen.most-active", "screeners", "Most active", "Highest volume names today."),
    ("screen.undervalued", "screeners", "Undervalued", "Value screen."),
    ("screen.growth-tech", "screeners", "Growth tech", "Growth technology screen."),
    ("screen.latest-reports", "screeners", "Just reported", "Companies that recently reported."),
    ("screen.bullish", "screeners", "Bullish setups", "Momentum / trend-following candidates."),
    ("screen.bearish", "screeners", "Bearish setups", "Weakening trend candidates."),
    ("screen.supply-demand", "screeners", "Supply / demand breakouts", "Accumulation breakouts."),
    ("screen.criteria", "screeners", "Custom screen", "Screen by your own criteria."),
    # technicals
    ("ta.rsi", "technicals", "RSI (server)", "RSI from the analysis server."),
    ("ta.macd", "technicals", "MACD", "MACD line, signal and histogram."),
    ("ta.full", "technicals", "Full technical analysis", "Trend, momentum, volatility summary."),
    ("ta.multi-timeframe", "technicals", "Multi-timeframe analysis", "Trend alignment across timeframes."),
    ("ta.pattern", "technicals", "Chart patterns", "Recognised chart patterns."),
    ("ta.anomaly", "technicals", "Market anomalies", "Unusual price or volume behaviour."),
    ("analytics.correlation", "technicals", "Correlation", "How symbols move together."),
    ("genesis-charting.compute_levels", "technicals", "Key levels", "Support, resistance and confluence levels."),
    ("genesis-charting.structure", "technicals", "Market structure", "Swings, trend and structure breaks."),
    # research sources
    ("web.search", "research", "Web search", "Search the web for a query."),
    ("web.read", "research", "Read a web page", "Fetch and read a page as text."),
    ("papers.search", "research", "Search papers (arXiv)", "Academic papers on a topic."),
    ("papers.abstract", "research", "Paper abstract", "One paper's abstract."),
)

CLASSIC_NODES: tuple[dict[str, Any], ...] = (
    {"id": "classic.check", "kind": "check", "category": "logic", "label": "Check data",
     "description": "Not empty, at least N items, or a field compared to a value.", "branches": True,
     "preset": {"kind": "check", "predicate": "non_empty"}},
    {"id": "classic.vault-map", "kind": "refresh", "category": "maintenance", "label": "Rebuild vault map",
     "description": "Regenerate the spec vault's map.", "writes": True,
     "preset": {"kind": "refresh", "target": "vault-map"}},
    {"id": "classic.corpus-index", "kind": "refresh", "category": "maintenance", "label": "Re-index trading corpus",
     "description": "Regenerate INDEX.auto.md from the corpus.", "writes": True,
     "preset": {"kind": "refresh", "target": "corpus-index"}},
    {"id": "classic.gather", "kind": "gather", "category": "custom", "label": "Call any tool",
     "description": "Any read tool inside the workflow grant, with your own arguments.",
     "preset": {"kind": "gather"}},
    {"id": "classic.run", "kind": "run", "category": "custom", "label": "Run any agent",
     "description": "Dispatch any non-execution agent with custom arguments.",
     "preset": {"kind": "run"}},
)


def nodes(*, connected: set[str] | None = None, processes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The whole palette. ``connected`` is the set of live capabilities, if known."""
    out: list[dict[str, Any]] = []
    for capability, category, label, description in TOOL_NODES:
        out.append({
            "id": f"tool.{capability}", "kind": "gather", "category": category, "label": label,
            "description": description, "capability": capability,
            "available": None if connected is None else capability in connected,
            "preset": {"kind": "gather", "capability": capability},
        })
    for action in ACTIONS.values():
        out.append({**action.to_dict(), "id": action.id, "kind": "action", "available": True,
                    "preset": {"kind": "action", "action": action.id}})
    out.extend({**n, "available": True} for n in CLASSIC_NODES)
    for proc in processes or []:
        out.append({
            "id": f"process.{proc['id']}", "kind": "action", "category": "custom",
            "label": proc["name"], "description": "Your process — runs as one step.",
            "available": True, "process": proc["id"],
            "preset": {"kind": "action", "action": "flow.process", "params": {"workflow": proc["id"]}},
        })
    return {"categories": [{"id": c, "label": label} for c, label in CATEGORIES], "nodes": out}
