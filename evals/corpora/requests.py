# Spec: Genesis Markdown/20-Agents/Agent Index.md
"""A hundred things the desk actually asks Genesis.

Companion to :mod:`intent` (*is this addressed to us?*) and :mod:`tool_selection`
(*which tool answers it?*). This corpus asks the question in between, and it is
the one the fleet is built against: **when this sentence arrives, who does the
work, and what does it need to touch?**

Written as a trader's requests rather than as prompts. Real asks are short,
elliptical, and assume context the sentence never states — *"is that a bull flag
or am I forcing it"* carries a symbol, a timeframe and a chart that were
established two turns ago. An agent designed against tidy paraphrases
(*"classify the chart pattern for ticker X on interval Y"*) will meet none of
them.

Each entry carries:

``text``    the utterance, wake word stripped — routing is tested here, not
            wake detection.
``agent``   the agent that **owns** the answer. One owner, always: fan-out is
            ``also``, and a request with two owners is a spec bug, not a corpus
            entry.
``also``    agents the owner must pull from for a complete answer. The
            orchestrator's decomposition target.
``caps``    capabilities, never tool ids — same rule as ``tool_selection``.
            Empty means the agent answers from its own state or memory, which
            is itself a claim worth testing.
``writes``  the request has an **efferent** limb: it changes broker or system
            state. Per `Biological Design` §afferent ≠ efferent these never
            share a path with reads, and per `Safety Invariants` #1 and #5 every
            one of them lands on ``propose_order`` → approval → ``place_approved``
            or on an explicit mode change. **No entry in this file may be
            satisfied by a tool called ``place_order``. There isn't one.**
``note``    what is hard about it. This is the field to read before writing an
            agent — most entries fail for the reason in the note, not for want
            of a model.

Coverage is deliberately weighted toward what gets asked all day (regime, news,
charts, P&L) rather than evenly across the fleet. Asset classes are mixed on
purpose: equities, options, futures, rates and credit, FX and crypto. An agent
that only parses ``NVDA`` breaks the first time someone says *"the ten year"*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["REQUESTS", "Request", "FAMILY", "by_agent", "by_family", "writes", "TOTAL"]


@dataclass(frozen=True)
class Request:
    text: str
    agent: str
    caps: tuple[str, ...] = ()
    also: tuple[str, ...] = ()
    writes: bool = False
    note: str = ""


#: Agent → family, from `20-Agents/Agent Index.md`. Families matter because
#: `Agent Index` §by-family-risk gates them differently: research and journal
#: cannot spend money, execution can.
FAMILY: dict[str, str] = {
    "market-analyst": "research",
    "news-and-catalyst": "research",
    "sentiment": "research",
    "fundamental": "research",
    "screener": "research",
    "idea-synthesizer": "research",
    "regime-and-correlation": "research",
    "chart-markup": "charting",
    "pattern-recognition": "charting",
    "multi-timeframe": "charting",
    "level-watcher": "charting",
    "strategy-author": "strategy",
    "backtest-runner": "strategy",
    "optimizer": "strategy",
    "risk-metrics": "strategy",
    "portfolio-and-allocation": "strategy",
    "ml-signal": "strategy",
    "prop-firm-guard": "strategy",
    "pre-trade-risk-engine": "execution",
    "order-manager": "execution",
    "position-and-pnl-accountant": "execution",
    "broker-adapter": "execution",
    "execution-quality": "execution",
    "kill-switch": "execution",
    "trade-journal": "journal",
    "performance-analyst": "journal",
    "insight-miner": "journal",
    "backtest-vs-live-drift": "journal",
    "watchdog": "journal",
    "digest": "journal",
}


# =============================================================================
# Top-down: what is the market doing            → Agent — Market Analyst
# =============================================================================

_REGIME: tuple[Request, ...] = (
    Request(
        "give me the pre-market brief",
        agent="digest",
        also=("market-analyst", "news-and-catalyst", "screener",
              "position-and-pnl-accountant"),
        caps=("market-data.overview", "news.headlines", "calendar.economic"),
        note="The widest fan-out in the corpus and the one users judge the "
             "system by. It must degrade: an unreachable news server yields a "
             "brief with a gap named in it, never a brief that quietly omits "
             "the reason the futures are down.",
    ),
    Request(
        "what's driving the tape this morning",
        agent="market-analyst",
        also=("news-and-catalyst",),
        caps=("market-data.overview", "news.headlines"),
        note="Causal, not descriptive. 'SPY is -0.6%' does not answer it. If no "
             "cause is identifiable the honest answer is 'nothing I can point "
             "at — it looks like positioning', and the agent must be allowed "
             "to say that instead of inventing a narrative.",
    ),
    Request(
        "is this risk-on or risk-off right now",
        agent="market-analyst",
        caps=("market-data.quote", "market-data.ohlcv"),
        note="A cross-asset read: equities vs. bonds vs. dollar vs. credit vs. "
             "gold. Answering it from the S&P alone is the failure mode.",
    ),
    Request(
        "how's breadth — is the index being carried by five names",
        agent="market-analyst",
        caps=("market-data.overview", "screen.gainers"),
        note="Needs advance/decline or equal-weight vs. cap-weight. If neither "
             "is available in the catalogue, say the metric is missing rather "
             "than substituting a proxy without labelling it as one.",
    ),
    Request(
        "rank the sectors by relative strength over one, three and six months",
        agent="market-analyst",
        caps=("market-data.ohlcv",),
        note="Relative to what? The benchmark is an unstated assumption — pick "
             "SPX, state it in the answer, and let it be overridden.",
    ),
    Request(
        "what's the two-year telling us about the next Fed meeting",
        agent="market-analyst",
        also=("news-and-catalyst",),
        caps=("macro.series", "market-data.quote"),
        note="Rates instrument named in prose, no ticker. Symbol resolution "
             "for 'the two-year', 'the long bond', 'the ten year' is a lookup "
             "table the research family shares, not per-agent parsing.",
    ),
    Request(
        "how did Asia and Europe close, and does it matter for our open",
        agent="market-analyst",
        caps=("market-data.quote", "time.now"),
        note="Two questions. The second is the one being asked; the first is "
             "context. Answering only the first is a complete miss.",
    ),
    Request(
        "what's the VIX term structure doing — are we in backwardation",
        agent="market-analyst",
        caps=("market-data.quote", "market-data.ohlcv"),
        note="Front/back VX futures. Contract-month roll logic is arithmetic, "
             "so it is `tier: none` code the agent calls, never something the "
             "model works out in prose.",
    ),
    Request(
        "compare this drawdown to the last five of similar depth",
        agent="regime-and-correlation",
        also=("market-analyst",),
        caps=("market-data.ohlcv",),
        note="Historical analogue search. Depth, duration and recovery path — "
             "and a loud caveat about sample size, because n=5 is a story, not "
             "a distribution.",
    ),
    Request(
        "give me your best three ideas for tomorrow, with thesis and invalidation",
        agent="idea-synthesizer",
        also=("market-analyst", "news-and-catalyst", "screener", "sentiment",
              "chart-markup"),
        caps=(),
        note="The request the whole research family exists to answer, and the "
             "one `Observability` measures the system by — idea → trade "
             "conversion, and outcome by confidence bucket. An `Idea Schema` "
             "object per idea: thesis, invalidation, confidence, sizing hint. "
             "**Invalidation is mandatory** — an idea that cannot be wrong is "
             "not an idea, and confidence must be calibrated against the "
             "journal rather than asserted. Three is a ceiling, not a quota: "
             "returning one good idea beats padding to three.",
    ),
)


# =============================================================================
# News, filings, catalysts                      → Agent — News And Catalyst
# =============================================================================

_NEWS: tuple[Request, ...] = (
    Request(
        "what are the catalysts this week for my watchlist",
        agent="news-and-catalyst",
        caps=("calendar.earnings", "calendar.economic"),
        note="Watchlist comes from memory, not the sentence. If the fabric is "
             "cold this returns a question, not an empty list.",
    ),
    Request(
        "why is CRWD down eight percent",
        agent="news-and-catalyst",
        also=("market-analyst", "sentiment"),
        caps=("news.headlines", "market-data.quote", "web.search"),
        note="The archetypal ask. Three real answers — a company event, a "
             "sector move, or nothing — and the third must be reachable. "
             "Verify the eight percent first; the premise is often wrong.",
    ),
    Request(
        "read the 8-K AVGO filed last night and tell me if it's material",
        agent="news-and-catalyst",
        caps=("filings.material-event", "filings.recent"),
        note="Primary source, not coverage of it. `forbid: news.headlines` — "
             "answering a filing question from a news summary is the "
             "defensible-but-wrong pick the gateway warns about.",
    ),
    Request(
        "summarize NVDA's call and flag anything that changed in the guidance",
        agent="news-and-catalyst",
        also=("fundamental",),
        caps=("filings.recent", "web.read", "web.search"),
        note="Guidance *delta* needs the prior quarter's number. A summary of "
             "one transcript cannot answer this and must not pretend to.",
    ),
    Request(
        "any insider buying in my names in the last ninety days",
        agent="fundamental",
        also=("news-and-catalyst",),
        caps=("filings.insider",),
        note="Buys and sells are not symmetric in signal. Automatic 10b5-1 "
             "sales are noise; an open-market purchase by an officer is not. "
             "If the source doesn't distinguish them, say so.",
    ),
    Request(
        "what's on the econ calendar tomorrow, and what's consensus",
        agent="news-and-catalyst",
        caps=("calendar.economic",),
        note="Timezone is a correctness issue, not a formatting one. Always "
             "resolve against the user's session clock via `time.now`.",
    ),
    Request(
        "watch for any headline about tariffs on semis and ping me",
        agent="news-and-catalyst",
        writes=True,
        caps=("news.headlines",),
        note="Not a question — a standing subscription. Creates durable state "
             "with a lifetime, a dedup rule and a way to cancel. The write "
             "here is to the system, not the broker, but it is still efferent "
             "and still needs an off switch the user can find.",
    ),
    Request(
        "did anyone upgrade or downgrade AMD this morning",
        agent="news-and-catalyst",
        also=("fundamental",),
        caps=("analyst.recommendations", "news.headlines"),
        note="Ratings actions, not forward estimates — the neighbouring "
             "capability `analyst.consensus` answers a different question and "
             "is the wrong pick here.",
    ),
    Request(
        "pull the FOMC statement and diff it against the last one",
        agent="news-and-catalyst",
        caps=("web.read", "web.search"),
        note="A literal text diff beats a model paraphrase and costs nothing. "
             "Deterministic where it can be; the model interprets the diff, it "
             "does not compute it.",
    ),
    Request(
        "is the move in TLT news-driven or flow-driven",
        agent="sentiment",
        also=("news-and-catalyst", "market-analyst"),
        caps=("news.headlines", "market-data.ohlcv"),
        note="Absence of news is evidence here, which makes a thin news source "
             "actively misleading. Confidence must reflect source coverage.",
    ),
)


# =============================================================================
# Fundamentals and valuation                    → Agent — Fundamental
# =============================================================================

_FUNDAMENTAL: tuple[Request, ...] = (
    Request(
        "walk me through NVDA's margins over the last eight quarters",
        agent="fundamental",
        caps=("fundamentals.income-statement", "fundamentals.metrics"),
        note="Gross, operating and net are three series. Give the trend and "
             "the inflection, not a table the user has to read for them.",
    ),
    Request(
        "is PLTR expensive relative to its own history",
        agent="fundamental",
        caps=("fundamentals.metrics", "market-data.ohlcv"),
        note="Self-relative, not peer-relative — a percentile of its own "
             "multiple. Watch the sample: three years of history for a recent "
             "listing makes the percentile meaningless.",
    ),
    Request(
        "screen the S&P for free cash flow yield over six percent with falling debt",
        agent="screener",
        also=("fundamental",),
        caps=("screen.custom", "fundamentals.metrics"),
        note="Two conditions, one of them a derivative over time. If the "
             "screening surface can't express 'falling', screen on the first "
             "and filter the second locally — and say which half was done "
             "where.",
    ),
    Request(
        "what does the street model for AMD next year, and how wide is the dispersion",
        agent="fundamental",
        caps=("analyst.consensus", "analyst.estimates"),
        note="Dispersion is the ask. A mean with no spread answers half the "
             "question and is the more dangerous half.",
    ),
    Request(
        "who are the biggest holders here, and did they add or trim",
        agent="fundamental",
        caps=("filings.institutional", "filings.recent"),
        note="13F data is 45 days stale by construction. Stamp the as-of date "
             "on the answer or it reads as current positioning.",
    ),
    Request(
        "compare AVGO and NVDA on growth-adjusted valuation",
        agent="fundamental",
        caps=("fundamentals.metrics", "analyst.estimates"),
        note="Two symbols, one verdict. The comparison must name the metric it "
             "used, because 'growth-adjusted' has at least four defensible "
             "definitions.",
    ),
    Request(
        "does this company have debt maturing in the next eighteen months",
        agent="fundamental",
        caps=("fundamentals.balance-sheet", "filings.recent"),
        note="'This company' is anaphora — resolved from conversation state, "
             "and if state is empty the agent asks rather than guessing at the "
             "last symbol it happened to see.",
    ),
    Request(
        "flag anything in the risk factors that changed from last year's 10-K",
        agent="fundamental",
        caps=("filings.recent", "web.read"),
        note="Two documents, section-scoped diff. Boilerplate churn dominates; "
             "the value is entirely in suppressing it.",
    ),
)


# =============================================================================
# Screening                                     → Agent — Screener
# =============================================================================

_SCREENER: tuple[Request, ...] = (
    Request(
        "run the semis long scan",
        agent="screener",
        caps=("screen.custom",),
        note="A *saved* scan by name. Fuzzy-match against stored scans and "
             "confirm which one ran — silently running an approximation of the "
             "user's scan is worse than not finding it.",
    ),
    Request(
        "find names up more than twenty percent off the fifty-day with rising volume",
        agent="screener",
        caps=("screen.custom", "ta.moving-average"),
        note="Ad-hoc criteria in prose → a structured screen object. That "
             "object should be offered for saving; this is how the saved-scan "
             "library actually gets built.",
    ),
    Request(
        "what are the biggest gainers and losers today",
        agent="screener",
        caps=("screen.gainers", "screen.losers"),
        note="Two capabilities, one answer. Needs a liquidity floor or it "
             "returns sub-dollar noise every single time.",
    ),
    Request(
        "anything gapping more than three percent pre-market with news",
        agent="screener",
        also=("news-and-catalyst",),
        caps=("screen.gainers", "news.headlines"),
        note="A join, not a screen: gap list ∩ news. Pre-market quality varies "
             "wildly by source — flag thin prints rather than ranking on them.",
    ),
    Request(
        "screen for tight consolidations near fifty-two week highs",
        agent="screener",
        also=("pattern-recognition",),
        caps=("screen.custom", "ta.volatility"),
        note="'Tight' is a parameter the user didn't give. Choose one (e.g. "
             "range as a fraction of ATR), state it, make it adjustable.",
    ),
    Request(
        "which of my saved scans fired overnight",
        agent="screener",
        caps=("screen.custom",),
        note="Reads scheduled-run results from memory rather than re-running "
             "anything. Re-running at query time gives a different answer than "
             "the one that actually fired, which is a subtle and expensive "
             "lie.",
    ),
    Request(
        "find liquid optionable names with IV rank above seventy",
        agent="screener",
        also=("sentiment",),
        caps=("screen.custom", "options.iv-rank"),
        note="IV rank is a percentile over a lookback, not a level. Name the "
             "lookback in the answer.",
    ),
    Request(
        "screen futures for the cleanest trend on the daily",
        agent="screener",
        also=("multi-timeframe",),
        caps=("screen.custom", "ta.adx", "market-data.ohlcv"),
        note="Continuous-contract stitching changes the answer. Say which "
             "adjustment was used.",
    ),
)


# =============================================================================
# Sentiment, flow, and the options book         → Agent — Sentiment
# =============================================================================

_FLOW: tuple[Request, ...] = (
    Request(
        "what's the put-call ratio on SPY versus the last month",
        agent="sentiment",
        caps=("options.put-call-ratio",),
        note="A level with no distribution is unreadable. Always answer with "
             "the percentile alongside it.",
    ),
    Request(
        "show me unusual options activity in semis today",
        agent="sentiment",
        caps=("options.flow", "options.volume-oi"),
        note="'Unusual' needs a baseline — volume vs. open interest vs. "
             "20-day average. And never infer direction from a single print: "
             "the other side of that sweep is invisible to you.",
    ),
    Request(
        "what does the skew on NVDA look like into earnings",
        agent="sentiment",
        also=("news-and-catalyst",),
        caps=("options.chain", "options.iv-surface", "calendar.earnings"),
        note="Needs the expiry that straddles the event, which needs the "
             "earnings date first. A two-hop dependency the planner must not "
             "flatten into parallel calls.",
    ),
    Request(
        "is thirty-day IV rich or cheap on TSLA against realized",
        agent="sentiment",
        caps=("options.iv-surface", "market-data.ohlcv"),
        note="IV/RV. Realized-vol estimator and window are choices that change "
             "the sign of the answer — state both.",
    ),
    Request(
        "price me a thirty-delta call spread on AMD expiring after earnings",
        agent="strategy-author",
        also=("sentiment", "portfolio-and-allocation"),
        caps=("options.chain", "calendar.earnings"),
        note="Reads as an order and is not one. It produces a *structure* — "
             "legs, debit, max loss, breakeven — that must then travel the "
             "normal propose→approve path if the user wants it on. The seam "
             "between 'price me' and 'do it' is exactly where a system gets "
             "this wrong once and never gets trusted again.",
    ),
    Request(
        "what are the greeks on my options book right now",
        agent="position-and-pnl-accountant",
        caps=("options.chain",),
        note="Portfolio greeks are arithmetic over live positions: `tier: "
             "none`. A model must never compute this, and aggregation across "
             "underlyings needs a stated convention (beta-weighted or not).",
    ),
    Request(
        "how short gamma am I if SPY drops two percent",
        agent="position-and-pnl-accountant",
        also=("portfolio-and-allocation",),
        caps=("options.chain",),
        note="A shock scenario, deterministic. Second-order by definition, so "
             "the linear approximation is the thing being asked about — don't "
             "answer it with a linear approximation.",
    ),
    Request(
        "when should I roll this — it's got nine days to expiry",
        agent="strategy-author",
        also=("position-and-pnl-accountant",),
        caps=("options.chain", "time.now"),
        note="Advisory, adjacent to a write. Present the roll as a proposal "
             "with its cost; never execute it because the user asked *when*.",
    ),
    Request(
        "is the crowd long or short the euro",
        agent="sentiment",
        caps=("positioning.cot", "web.search"),
        note="COT is weekly and lagged. An answer that reads as live "
             "positioning from Tuesday-stamped data is wrong even when the "
             "number is right.",
    ),
    Request(
        "what's funding doing in perps — is the long side crowded",
        agent="sentiment",
        caps=("crypto.funding-rate", "crypto.open-interest"),
        note="Venue matters and rates differ across them. Name the venue or "
             "aggregate explicitly.",
    ),
)


# =============================================================================
# Rates, credit, macro, FX                      → Agent — Market Analyst
# =============================================================================

_MACRO: tuple[Request, ...] = (
    Request(
        "show me the yield curve now versus three months ago",
        agent="market-analyst",
        also=("chart-markup",),
        caps=("macro.series", "chart.render"),
        note="A curve is a cross-section, not a time series — the shape "
             "across tenors at two dates. Fetching one tenor's history is the "
             "obvious wrong turn.",
    ),
    Request(
        "what's priced for cuts over the next twelve months",
        agent="market-analyst",
        caps=("market-data.quote", "web.search"),
        note="Market-implied, from fed funds futures. If the strip isn't in "
             "the catalogue, say the number is sourced from commentary rather "
             "than computed — the two are not interchangeable.",
    ),
    Request(
        "how did the ten-year auction go — was the tail ugly",
        agent="news-and-catalyst",
        also=("market-analyst",),
        caps=("web.search", "web.read"),
        note="Domain jargon with precise meaning: tail, bid-to-cover, "
             "indirects. Get the vocabulary wrong and the answer is worthless "
             "to the person asking.",
    ),
    Request(
        "what's the duration on my bond sleeve if yields move fifty basis points",
        agent="portfolio-and-allocation",
        also=("position-and-pnl-accountant",),
        caps=(),
        note="Deterministic, `tier: none`. Convexity matters at 50bp; a "
             "duration-only answer understates the move and must say it is "
             "first-order.",
    ),
    Request(
        "what does the model say about this name — and how much should I weight it",
        agent="ml-signal",
        also=("insight-miner",),
        caps=(),
        note="**Advisory only**, per `Agent Index` — an ML score never sizes "
             "anything and never reaches the order path on its own. The second "
             "half of the question is the trap: answer it with the model's "
             "out-of-sample hit rate and the age of the last retrain, not with "
             "a weight. A stale model that still answers confidently is the "
             "failure mode, so a score is invalid without its as-of date.",
    ),
    Request(
        "is the dollar confirming or contradicting the equity move",
        agent="regime-and-correlation",
        caps=("market-data.ohlcv",),
        note="Correlation regimes flip. The relationship must be measured over "
             "a stated window, not asserted from priors about how it 'usually' "
             "works.",
    ),
    Request(
        "what are credit spreads doing — is high yield warning about anything",
        agent="market-analyst",
        also=("regime-and-correlation",),
        caps=("macro.series", "market-data.ohlcv"),
        note="HY OAS. Credit leading equity is a claim with a poor recent "
             "record — present the level and the change, flag the "
             "interpretation as interpretation.",
    ),
)


# =============================================================================
# Charts                                        → Charting family
# =============================================================================

_CHARTING: tuple[Request, ...] = (
    Request(
        "show me NVDA on the daily and mark up support and resistance",
        agent="chart-markup",
        caps=("market-data.ohlcv", "chart.render"),
        note="The canonical charting request. Output is a `Markup Spec` "
             "object plus a render — never a prose list of levels, because "
             "the spec is what `level-watcher` later consumes.",
    ),
    Request(
        "what's the structure on ES across four-hour, daily and weekly",
        agent="multi-timeframe",
        also=("chart-markup",),
        caps=("market-data.ohlcv", "chart.render"),
        note="Three reads and one composite verdict, with an alignment score. "
             "Three separate answers stapled together is the failure.",
    ),
    Request(
        "is that a bull flag or am I forcing it",
        agent="pattern-recognition",
        caps=("chart.render", "market-data.ohlcv"),
        note="Invites disagreement, which is the point. Vision plus a rule "
             "cross-check, and 'you're forcing it' must be a reachable answer "
             "— an agent that always validates the user's pattern is worse "
             "than no agent.",
    ),
    Request(
        "draw the anchored VWAP from the earnings gap",
        agent="chart-markup",
        also=("news-and-catalyst",),
        caps=("ta.vwap", "calendar.earnings", "chart.render"),
        note="The anchor date must be *found* before the study can be drawn — "
             "a dependency, not a parameter.",
    ),
    Request(
        "where's the volume shelf — I want a level I can lean on",
        agent="chart-markup",
        caps=("ta.volume-profile", "chart.render"),
        note="'Lean on' means actionable: a level with a stop distance, not a "
             "region. Answer with a price and a tolerance.",
    ),
    Request(
        "watch 4,860 on ES and tell me if we lose it on a closing basis",
        agent="level-watcher",
        writes=True,
        caps=("market-data.quote",),
        note="`tier: none`, and a durable subscription. 'On a closing basis' "
             "is a real qualifier — which close, on which timeframe — and "
             "getting it wrong produces an alert storm on every intrabar poke.",
    ),
    Request(
        "mark up the levels I care about and save the spec",
        agent="chart-markup",
        writes=True,
        caps=("chart.render", "vault.create"),
        note="'The levels I care about' is memory recall, not analysis. Then a "
             "persisted spec — versioned, so tomorrow's markup doesn't silently "
             "overwrite today's reasoning.",
    ),
    Request(
        "how many times has this level been tested, and how did it resolve",
        agent="chart-markup",
        also=("pattern-recognition",),
        caps=("market-data.ohlcv",),
        note="Needs a definition of 'test' — touch, wick through, close "
             "through — before it needs any data. Counting is deterministic "
             "once defined; state the definition used.",
    ),
    Request(
        "give me a multi-timeframe alignment score for gold",
        agent="multi-timeframe",
        caps=("market-data.ohlcv",),
        note="A number the user will start trusting. Publish the rubric with "
             "it, and keep the rubric stable — a score that silently changes "
             "meaning across versions is a memory corruption bug.",
    ),
    Request(
        "chart the ratio of semis to the S&P",
        agent="chart-markup",
        caps=("market-data.ohlcv", "chart.render"),
        note="A synthetic series. Alignment on dates and a rebase decision — "
             "an unrebased ratio chart is unreadable across long windows.",
    ),
    Request(
        "overlay the last three post-earnings drifts on this name",
        agent="chart-markup",
        also=("news-and-catalyst", "pattern-recognition"),
        caps=("calendar.earnings", "market-data.ohlcv", "chart.render"),
        note="Event-anchored overlay: find three dates, window each, normalise "
             "to the event bar. The normalisation is the whole chart.",
    ),
    Request(
        "clean up the chart — drop the levels that are stale",
        agent="chart-markup",
        writes=True,
        caps=("chart.render",),
        note="Deletion of prior state. 'Stale' needs a rule (age, invalidated "
             "by price, superseded) and the removals should be listed, because "
             "silently deleting the user's reasoning is unrecoverable.",
    ),
)


# =============================================================================
# Strategy, backtest, optimisation              → Strategy family
# =============================================================================

_STRATEGY: tuple[Request, ...] = (
    Request(
        "write me a strategy: long when the fifty crosses the two hundred, "
        "out on a close below the twenty",
        agent="strategy-author",
        caps=("ta.moving-average",),
        note="Prose → a `Strategy Schema` object. Everything unstated — "
             "universe, sizing, costs, session — must surface as explicit "
             "defaults in the object, never as silent assumptions inside it.",
    ),
    Request(
        "backtest that over ten years on the Nasdaq 100 with realistic costs",
        agent="backtest-runner",
        caps=("market-data.ohlcv",),
        note="`tier: none` end to end. Survivorship bias on a current index "
             "membership list will flatter this by a wide margin — if the "
             "point-in-time constituents aren't available, the caveat goes in "
             "the result object, not in a footnote.",
    ),
    Request(
        "what's the Sharpe, Sortino and max drawdown on that curve",
        agent="risk-metrics",
        caps=(),
        note="Canonical definitions, one implementation, unit-tested. Two "
             "agents computing Sharpe differently is the bug this agent "
             "exists to prevent.",
    ),
    Request(
        "walk it forward and tell me if the edge survives out of sample",
        agent="optimizer",
        also=("backtest-runner", "risk-metrics"),
        caps=(),
        note="The answer 'no' must be as easy to produce as 'yes'. An "
             "optimizer that always finds a surviving edge has found nothing.",
    ),
    Request(
        "is this overfit — how many parameters did we search, over how many trades",
        agent="optimizer",
        caps=(),
        note="Trials, degrees of freedom, trade count. Deterministic and "
             "unflattering by design; this is the agent that argues with the "
             "user's favourite strategy.",
    ),
    Request(
        "convert that to PineScript so I can eyeball it on TradingView",
        agent="strategy-author",
        caps=(),
        note="Code generation from the strategy object. Anything not "
             "expressible in Pine must be named as a divergence, or the user "
             "will eyeball a different strategy than the one tested.",
    ),
    Request(
        "what happens to that edge in the first thirty minutes only",
        agent="backtest-runner",
        also=("risk-metrics",),
        caps=("market-data.ohlcv",),
        note="A session filter cuts the sample hard. Report the new trade "
             "count next to the new Sharpe or the comparison is meaningless.",
    ),
    Request(
        "how does it behave in high-vol regimes versus low",
        agent="backtest-runner",
        also=("regime-and-correlation", "risk-metrics"),
        caps=("market-data.ohlcv",),
        note="Regime labels must be computed with data available at the time. "
             "Labelling regimes with hindsight is lookahead bias wearing a "
             "convincing disguise.",
    ),
    Request(
        "run a Monte Carlo on the trade sequence, give me the fifth percentile",
        agent="risk-metrics",
        caps=(),
        note="Resampling choice — iid vs. block — matters when trades "
             "autocorrelate. State which, and seed it so the number is "
             "reproducible across runs.",
    ),
    Request(
        "compare the last three versions of this strategy side by side",
        agent="backtest-runner",
        also=("risk-metrics",),
        caps=(),
        note="Requires that versions were persisted with their results. If "
             "they weren't, the honest answer is that the history is missing.",
    ),
    Request(
        "what's the expectancy per trade in R, and how many trades a month",
        agent="risk-metrics",
        caps=(),
        note="R depends on the stop definition in the strategy object. If the "
             "strategy has no stop, R is undefined — say so rather than "
             "substituting average loss.",
    ),
    Request(
        "does a regime filter improve this, or just cut the sample",
        agent="optimizer",
        also=("backtest-runner",),
        caps=(),
        note="The user has pre-stated the trap, which makes the lazy 'yes, "
             "Sharpe improved' answer worse than useless. Must address both "
             "halves.",
    ),
)


# =============================================================================
# Sizing, exposure, prop rules                  → Strategy family (risk-facing)
# =============================================================================

_PORTFOLIO: tuple[Request, ...] = (
    Request(
        "how big should this be for one percent risk with a stop at 172",
        agent="portfolio-and-allocation",
        also=("pre-trade-risk-engine",),
        caps=("market-data.quote",),
        note="`tier: none`, no exceptions — `Safety Invariants` #3. Needs "
             "account equity, contract multiplier and rounding rules. Rounding "
             "is where sizing bugs actually live.",
    ),
    Request(
        "what's my correlated exposure — am I in one trade five times",
        agent="regime-and-correlation",
        also=("position-and-pnl-accountant", "portfolio-and-allocation"),
        caps=("market-data.ohlcv",),
        note="The question that saves accounts. Correlation over a stated "
             "window across current positions, clustered — not a matrix dumped "
             "at the user.",
    ),
    Request(
        "rebalance to risk parity and show me the trades that implies",
        agent="portfolio-and-allocation",
        writes=True,
        also=("pre-trade-risk-engine",),
        caps=(),
        note="'Show me' stops at proposal. Weights are deterministic; the "
             "resulting orders are proposals that each pass the gate "
             "individually, and the basket must not be a way to approve "
             "twenty orders with one nod.",
    ),
    Request(
        "how much room is left against the daily loss limit",
        agent="prop-firm-guard",
        also=("position-and-pnl-accountant",),
        caps=(),
        note="Realized-only or including open? Prop firms differ, and using "
             "the wrong one breaches an account. Read the configured rule set, "
             "never a general assumption.",
    ),
    Request(
        "will this trade breach any FTMO rule",
        agent="prop-firm-guard",
        caps=(),
        note="A hard constraint expressed as code, fail-closed. Unknown rule "
             "or missing input → block, per `Safety Invariants` #2.",
    ),
    Request(
        "what's my heat, and how does it compare to my average",
        agent="position-and-pnl-accountant",
        also=("performance-analyst",),
        caps=(),
        note="Open risk summed across positions, with stops. Positions with no "
             "stop have unbounded heat — that is the finding, not an edge case "
             "to skip.",
    ),
    Request(
        "if everything gapped down three percent overnight, what would I lose",
        agent="portfolio-and-allocation",
        also=("position-and-pnl-accountant",),
        caps=(),
        note="Scenario shock, deterministic. Stops do not protect against gaps "
             "— an answer that applies them is wrong in exactly the direction "
             "that hurts.",
    ),
)


# =============================================================================
# The efferent limb: orders, state, the switch  → Execution family
# =============================================================================
# Every request below either changes broker state or reads the state of record.
# `Safety Invariants` #1 governs the writes: propose → approve → place_approved,
# signed single-use order-bound tokens, no `place_order` tool anywhere.

_EXECUTION: tuple[Request, ...] = (
    Request(
        "propose a long in NVDA, half a position, stop under yesterday's low",
        agent="pre-trade-risk-engine",
        also=("portfolio-and-allocation", "order-manager"),
        writes=True,
        caps=("market-data.ohlcv", "market-data.quote"),
        note="The full efferent path in one sentence. 'Half a position' is "
             "sizing from memory; 'under yesterday's low' is a computed price "
             "with an unstated buffer. Both resolve to numbers *before* the "
             "gate sees them, and the gate re-checks rather than trusting.",
    ),
    Request(
        "move my stop to breakeven on the AMD trade",
        agent="order-manager",
        writes=True,
        caps=(),
        note="A modify, not a new order — still efferent, still audited. "
             "Breakeven means average entry including fees, which is not the "
             "fill price of the first lot.",
    ),
    Request(
        "cancel the working orders in energy",
        agent="order-manager",
        writes=True,
        caps=(),
        note="Bulk, filtered, destructive. Enumerate what will be cancelled "
             "and confirm the set; a sector filter that silently matches "
             "nothing must not report success.",
    ),
    Request(
        "flatten the book",
        agent="kill-switch",
        writes=True,
        caps=(),
        note="Heavy reflex, wake-word-required per :mod:`intent`. Cancel-all "
             "first, then flatten, then mode → halt. It must work when the "
             "orchestrator is down — separate process, `Safety Invariants` #4.",
    ),
    Request(
        "halt everything",
        agent="kill-switch",
        writes=True,
        caps=(),
        note="Halt is not flatten: stop *new* risk, leave positions. Users "
             "conflate them and the system must not. Confirm which happened, "
             "in words.",
    ),
    Request(
        "what's my P&L today, realized and unrealized",
        agent="position-and-pnl-accountant",
        caps=("market-data.quote",),
        note="Source of truth, `tier: none`. If broker and internal ledger "
             "disagree, report the discrepancy — never pick the friendlier "
             "number.",
    ),
    Request(
        "what am I actually holding — reconcile against the broker",
        agent="position-and-pnl-accountant",
        also=("broker-adapter", "watchdog"),
        caps=(),
        note="Proprioception, the third principle in `Biological Design`. "
             "Drift between believed and actual state is the failure that "
             "loses money quietly, so a mismatch is an alert, not a log line.",
    ),
    Request(
        "how bad was the slippage on that fill versus arrival",
        agent="execution-quality",
        caps=(),
        note="Arrival price must have been captured at decision time. If it "
             "wasn't, the metric cannot be reconstructed later — say the data "
             "is missing rather than back-filling from the fill.",
    ),
    Request(
        "put a trailing stop on the winner and leave the rest",
        agent="order-manager",
        writes=True,
        caps=(),
        note="'The winner' is a resolution step with a real chance of "
             "ambiguity. Two winners → ask. Never pick one and proceed.",
    ),
    Request(
        "switch me to paper until I say otherwise",
        agent="broker-adapter",
        writes=True,
        caps=(),
        note="Mode change, audited, and sticky across restarts. Paper and live "
             "share the code path by design, so the mode indicator is the only "
             "thing standing between the two — it must be impossible to "
             "misread.",
    ),
)


# =============================================================================
# Journal, review, and the system's own health  → Journal family
# =============================================================================

_JOURNAL: tuple[Request, ...] = (
    Request(
        "journal that trade with the chart and my thesis",
        agent="trade-journal",
        writes=True,
        also=("chart-markup",),
        caps=("vault.create", "chart.render"),
        note="'My thesis' is what the user said before entering — recall from "
             "the fabric, not a reconstruction after the outcome is known. "
             "Post-hoc thesis writing quietly destroys the journal's value.",
    ),
    Request(
        "why did I lose money last week",
        agent="performance-analyst",
        also=("insight-miner",),
        caps=("vault.search",),
        note="Attribution: which trades, which setups, which sessions. One bad "
             "trade and a broken process are different answers and must not "
             "be blended into a narrative.",
    ),
    Request(
        "which setup makes me money, and which one am I lying to myself about",
        agent="insight-miner",
        also=("performance-analyst",),
        caps=("vault.search",),
        note="The eval that matters, per `Observability`. It is *invited* "
             "criticism — an agent that softens this is failing the request as "
             "asked. Sample sizes per setup are usually too small to be "
             "conclusive; say so and still answer.",
    ),
    Request(
        "does my live performance still match the backtest",
        agent="backtest-vs-live-drift",
        also=("risk-metrics",),
        caps=(),
        note="Like-for-like comparison — same costs, same session, same "
             "universe — or the divergence is measuring the comparison rather "
             "than the strategy.",
    ),
    Request(
        "give me the evening recap",
        agent="digest",
        also=("position-and-pnl-accountant", "performance-analyst",
              "news-and-catalyst"),
        caps=("vault.create",),
        note="Scheduled and on-demand share one implementation. Written to the "
             "vault so tomorrow's brief can reference it — this is how "
             "continuity is manufactured in a system with no memory of its "
             "own.",
    ),
    Request(
        "is anything broken — feeds, brokers, agents",
        agent="watchdog",
        caps=("git.status",),
        note="Heartbeats across the fleet. Degraded is a distinct state from "
             "down, and a component that has never reported is not the same as "
             "one that is healthy — the empty-set bug that makes a watchdog "
             "report green while blind.",
    ),
)


REQUESTS: tuple[Request, ...] = (
    _REGIME
    + _NEWS
    + _FUNDAMENTAL
    + _SCREENER
    + _FLOW
    + _MACRO
    + _CHARTING
    + _STRATEGY
    + _PORTFOLIO
    + _EXECUTION
    + _JOURNAL
)

TOTAL = len(REQUESTS)


def by_agent(agent: str) -> tuple[Request, ...]:
    """Every request whose primary owner is ``agent``.

    The list to read before building that agent — it is the surface area the
    agent is accountable for, in the words it will actually receive.
    """
    return tuple(r for r in REQUESTS if r.agent == agent)


def by_family(family: str) -> tuple[Request, ...]:
    """Every request owned by an agent in ``family``."""
    return tuple(r for r in REQUESTS if FAMILY[r.agent] == family)


def writes() -> tuple[Request, ...]:
    """The efferent subset — the requests that change state.

    Twenty percent of the corpus and all of the risk. Any agent that appears
    here needs an audit trail, an idempotency key and a way to be told no.
    """
    return tuple(r for r in REQUESTS if r.writes)
