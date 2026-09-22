# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The tool-selection corpus: tasks, and the tool that should top the list.

Written against **capabilities**, never tool ids. Which server owns
``web.search`` is the registry's decision and is re-decided by tier; an eval
pinned to ``exa.web_search_exa`` would fail the day that contest is re-run,
which is a change the design says agents must not notice.

Cases are drawn from what the desk is actually asked. The distractor catalogue
in the harness is the other half of the eval: precision at k=1 over eight tools
is not a measurement, it is a formality.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CASES", "SelectionCase"]


@dataclass(frozen=True)
class SelectionCase:
    name: str
    task: str
    #: The capability that must rank first.
    expect: str
    #: Capabilities that must not appear anywhere in the selection. Used for
    #: the cases where the wrong pick is *defensible*, which is the failure
    #: mode the registry warning is about.
    forbid: tuple[str, ...] = ()
    task_type: str = ""


CASES: tuple[SelectionCase, ...] = (
    # -- unambiguous, but must survive fifty distractors ------------------
    SelectionCase(
        name="what time is it",
        task="what time is it in Tokyo right now",
        expect="time.now",
    ),
    SelectionCase(
        name="web search",
        task="search the web for what analysts are saying about NVDA",
        expect="web.search",
    ),
    SelectionCase(
        name="fetch a known url",
        task="read the page at https://example.com/report and summarise it",
        expect="web.read",
    ),
    SelectionCase(
        name="write a note",
        task="write a note in the vault about today's session",
        expect="vault.create",
    ),
    SelectionCase(
        name="search the vault",
        task="search my notes for what I wrote about gap fills",
        expect="vault.search",
    ),
    SelectionCase(
        name="repo status",
        task="what is the git status of the repository",
        expect="git.status",
        task_type="watchdog",
    ),
    # -- the newly wired servers -----------------------------------------
    SelectionCase(
        name="a filing",
        task="pull the latest 10-K filing for Apple",
        expect="filings.recent",
    ),
    SelectionCase(
        name="insider transactions",
        task="show me recent insider transactions",
        expect="filings.insider",
    ),
    SelectionCase(
        name="macro series",
        task="what has CPI done over the last year",
        expect="macro.series",
    ),
    # Phrased without naming the source, which is the harder case: every tool
    # on a server shares that server's keywords, so "papers" alone leaves
    # `search`, `download` and `list` tied. What separates them is the
    # capability-specificity tie-break — the plainer capability wins unless a
    # word in the task named the specialisation.
    SelectionCase(
        name="a paper",
        task="find papers on volatility forecasting with transformers",
        expect="papers.search",
    ),
    SelectionCase(
        name="and the specialisation, when it is named",
        task="download the full text of that paper",
        expect="papers.download",
    ),
    SelectionCase(
        name="convert a pdf",
        task="convert this research pdf to markdown so I can keep it",
        expect="convert.to-markdown",
    ),
    # -- the router must not confuse neighbours ---------------------------
    SelectionCase(
        name="filings not news",
        task="what did the company say in its own 8-K filing",
        expect="filings.material-event",
        forbid=("news.headlines",),
    ),
    SelectionCase(
        name="macro not market data",
        task="pull the unemployment rate series from the Fed",
        expect="macro.series",
    ),
    SelectionCase(
        name="vault write not filesystem read",
        task="create a note recording this decision",
        expect="vault.create",
        forbid=("fs.read",),
    ),
    # `chart.*` is deliberately absent from this corpus: genesis-tradingview
    # is disabled by default — it needs the desktop app running — so it is not
    # in the catalogue this eval is built from. A case that can only pass on a
    # developer's desk is a case that fails in CI for the wrong reason.

    # -- the free market-data surface, wired 2026-09-03 --------------------
    # Every one of these was checked against the live 103-tool catalogue
    # before being written down, so a failure here is a regression rather
    # than an aspiration.
    SelectionCase(
        name="a quote",
        task="what is NVDA trading at",
        expect="market-data.quote",
    ),
    SelectionCase(
        name="deep history, not a quote",
        task="pull me twenty years of daily bars for SPY",
        expect="market-data.ohlcv",
    ),
    SelectionCase(
        name="an earnings date is a calendar, not an earnings figure",
        task="when does Apple report earnings",
        expect="calendar.earnings",
    ),
    SelectionCase(
        name="a screen",
        task="show me the bullish screens",
        expect="screen.bullish",
    ),
    SelectionCase(
        name="movers",
        task="what are the biggest gainers today",
        expect="screen.gainers",
    ),
    SelectionCase(
        name="forward estimates, not past recommendations",
        task="what is the analyst consensus on AMD",
        expect="analyst.consensus",
    ),
    SelectionCase(
        name="a corporate action",
        # The case that caught a bad keyword: `last` on FRED's observations
        # tool was pulling this into macro, because a generic word on a tier-1
        # server beats a specific word on a tier-3 one at the tie-break.
        task="did they pay a dividend last quarter",
        expect="corporate.dividends",
        forbid=("macro.series",),
    ),
    SelectionCase(
        name="the market, not one ticker",
        task="how does the market look right now",
        expect="market-data.overview",
    ),
    SelectionCase(
        name="an indicator",
        task="what is the RSI on TSLA",
        expect="ta.rsi",
    ),

    # -- write verbs must not be interchangeable --------------------------
    # All three obsidian note tools share the name token `note`. Without
    # keywords they tie, and the capability-specificity tie-break then makes
    # "write a note" mean `edit`. The expensive misread is the other one:
    # `update that note` reaching `create` makes a duplicate instead of an
    # amendment.
    SelectionCase(
        name="write means create",
        task="write a note in the vault about today's session",
        expect="vault.create",
    ),
    SelectionCase(
        name="update means edit",
        task="update that note with the new numbers",
        expect="vault.edit",
    ),
)
