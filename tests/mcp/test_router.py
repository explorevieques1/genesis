# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The router: does the right handful surface, and does it stay deterministic?"""

from __future__ import annotations

import pytest

from genesis.mcp.fence import TrustLedger
from genesis.mcp.registry import ToolRegistry
from genesis.mcp.router import (
    SearchBudget,
    SearchBudgetExhausted,
    ToolRouter,
    tokenize,
)
from genesis.mcp.spec import ToolSpec, Trust


def tool(
    tool_id: str,
    capability: str,
    *,
    description: str = "",
    tier: int = 1,
    trust: Trust = Trust.TRUSTED,
) -> ToolSpec:
    server, _, name = tool_id.partition(".")
    return ToolSpec(
        id=tool_id,
        server=server,
        name=name,
        capability=capability,
        description=description,
        trust=trust,
        mutating=False,
        tier=tier,
    )


CATALOGUE = [
    tool("obsidian.obsidian_create_note", "vault.create", description="Create a note in the vault"),
    tool("obsidian.obsidian_search_vault", "vault.search", description="Search notes by text"),
    tool("exa.web_search_exa", "web.search", description="Neural web search over the internet"),
    tool("exa.web_fetch_exa", "web.read", description="Fetch a page and return clean text"),
    tool("fred.get_series", "macro.series", description="Federal Reserve economic time series"),
    tool("sec-edgar.get_filing", "filings.filing", description="Retrieve an SEC filing document"),
    tool("time.get_current_time", "time.now", description="The current time in a timezone"),
    tool("git.git_status", "git.status", description="Working tree status of a repository"),
]


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry(allow_writes=True)
    reg.register_all(CATALOGUE)
    return reg


# --------------------------------------------------------------------------
# Tokenizing
# --------------------------------------------------------------------------


def test_stopwords_and_plurals_are_folded() -> None:
    assert tokenize("Search the vault for my notes about filings") == (
        "search", "vault", "note", "filing",
    )


def test_news_does_not_become_new() -> None:
    """The one plural rule that must not fire: `news` is a namespace."""
    assert "news" in tokenize("scan the news")


# --------------------------------------------------------------------------
# Selecting
# --------------------------------------------------------------------------


def test_the_obvious_task_gets_the_obvious_tool(registry: ToolRegistry) -> None:
    router = ToolRouter(registry)
    chosen = router.select("search the web for NVDA guidance", CATALOGUE, limit=3)
    assert chosen.ids[0] == "exa.web_search_exa"
    assert chosen.matched


def test_capability_outranks_a_description_that_merely_mentions_it(
    registry: ToolRegistry,
) -> None:
    """A tool named after the job beats one whose blurb happens to say the word.

    The failure this prevents is the specific one MCP Server Catalog warns
    about: a defensible-but-wrong pick that nobody notices because the shape of
    the answer is right.
    """
    catalogue = [
        tool("a.get_filing", "filings.filing", description="documents"),
        tool("b.summarize", "web.summarize", description="summarize a filing or any filing text"),
    ]
    reg = ToolRegistry(allow_writes=True)
    reg.register_all(catalogue)
    chosen = ToolRouter(reg).select("get the latest filing", catalogue, limit=1)
    assert chosen.ids == ("a.get_filing",)


def test_a_namespace_named_in_the_task_lifts_its_whole_family(
    registry: ToolRegistry,
) -> None:
    router = ToolRouter(registry)
    chosen = router.select("check macro conditions", CATALOGUE, limit=2)
    assert "fred.get_series" in chosen.ids


def test_selection_is_capped(registry: ToolRegistry) -> None:
    router = ToolRouter(registry, limit=3)
    chosen = router.select("search vault web time git filing macro note", CATALOGUE)
    assert len(chosen) == 3


def test_ranking_is_deterministic(registry: ToolRegistry) -> None:
    """Same catalogue, same task, same eight tools — every run.

    Without this the selection eval scores a coin flip, and a regression in
    ranking would show up as flakiness rather than as a failure.
    """
    router = ToolRouter(registry)
    task = "write a note about the filing"
    first = router.select(task, CATALOGUE).ids
    for _ in range(20):
        assert router.select(task, list(reversed(CATALOGUE))).ids == first


def test_no_signal_is_reported_as_no_signal(registry: ToolRegistry) -> None:
    """A shrug must not be presented as a decision."""
    chosen = ToolRouter(registry).select("hmm", CATALOGUE, limit=3)
    assert not chosen.matched
    assert len(chosen) == 3  # still usable, still capped


def test_selection_never_leaves_the_candidate_set(registry: ToolRegistry) -> None:
    """The allow-list is the pool, not a filter applied afterwards."""
    allowed = [t for t in CATALOGUE if t.capability.startswith("vault.")]
    chosen = ToolRouter(registry).select("search the web", allowed)
    assert set(chosen.ids) <= {t.id for t in allowed}


def test_task_type_is_weighted(registry: ToolRegistry) -> None:
    generic = "look at what changed"
    without = ToolRouter(registry).select(generic, CATALOGUE, limit=1)
    with_type = ToolRouter(registry).select(generic, CATALOGUE, task_type="git", limit=1)
    assert with_type.ids == ("git.git_status",)
    assert without.ids != with_type.ids or not without.matched


# --------------------------------------------------------------------------
# Trust
# --------------------------------------------------------------------------


def test_an_injecting_source_is_buried_but_not_deleted(registry: ToolRegistry) -> None:
    """Rule 4 made operative — and its limit.

    A source that keeps serving injections ranks below its competitors. It does
    not vanish: a capability that disappears after one injection is a
    capability an attacker can amputate by quoting one in an article.
    """
    catalogue = [
        tool("exa.web_search_exa", "web.search", description="search the web"),
        tool("fetch.fetch", "web.read", description="search and read a web page"),
    ]
    reg = ToolRegistry(allow_writes=True)
    reg.register_all(catalogue)
    ledger = TrustLedger()
    router = ToolRouter(reg, trust=ledger)

    before = router.select("search the web", catalogue).ids
    assert before[0] == "exa.web_search_exa"

    for _ in range(4):
        ledger.penalise("exa", ("instruction-override",))

    after = router.select("search the web", catalogue).ids
    assert after[0] == "fetch.fetch"
    assert "exa.web_search_exa" in after, "a buried tool must still be reachable"


# --------------------------------------------------------------------------
# The escape hatch
# --------------------------------------------------------------------------


def test_tool_search_is_capped_per_reply(registry: ToolRegistry) -> None:
    router = ToolRouter(registry)
    budget = SearchBudget(limit=2)
    router.search("vault", CATALOGUE, budget=budget)
    router.search("web", CATALOGUE, budget=budget)
    with pytest.raises(SearchBudgetExhausted):
        router.search("time", CATALOGUE, budget=budget)


def test_a_search_that_finds_nothing_still_spends_budget(registry: ToolRegistry) -> None:
    """The loop this cap breaks is made of failures, so failures must cost."""
    budget = SearchBudget(limit=1)
    ToolRouter(registry).search("zzzzz", CATALOGUE, budget=budget)
    assert budget.remaining == 0


# --------------------------------------------------------------------------
# The acceptance criterion
# --------------------------------------------------------------------------


def test_fifty_more_tools_do_not_change_the_choice(registry: ToolRegistry) -> None:
    """*"Adding 50 tools does not degrade tool choice."*

    The unrelated servers are plausible rather than nonsense — random strings
    would pass this trivially. These have real words in their descriptions,
    which is how a naive ranker actually gets confused.
    """
    noise = [
        tool(
            f"noise{i}.list_records",
            f"noise{i}.list",
            description=f"List and read records, documents and data for system {i}",
            tier=5,
        )
        for i in range(50)
    ]
    reg = ToolRegistry(allow_writes=True)
    reg.register_all(CATALOGUE + noise)
    router = ToolRouter(reg)

    for task, expected in [
        ("search the web for NVDA guidance", "exa.web_search_exa"),
        ("what time is it in Tokyo", "time.get_current_time"),
        ("pull the latest 10-K filing", "sec-edgar.get_filing"),
        ("create a note in the vault", "obsidian.obsidian_create_note"),
    ]:
        assert router.select(task, CATALOGUE + noise).ids[0] == expected, task
