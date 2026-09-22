# Spec: Genesis Markdown/60-UI/News.md
"""The news store, parser and analyst self-checks, run under pytest. No network, fake model."""

from genesis.agents.research import news_catalyst
from genesis.news import collect, econ, store


def test_news_store():
    store.demo()


def test_news_parse():
    collect.demo()


def test_econ_calendar():
    """Parsing, the all-day rule, the forward window and the staleness guard. No network."""
    econ.demo()


def test_news_analyst_fences_cites_and_refuses_without_a_model():
    news_catalyst.demo()
