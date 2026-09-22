# Spec: Genesis Markdown/60-UI/News.md
"""News: collect headlines (reflex), read articles, and hand them to the analyst."""

from __future__ import annotations

from pathlib import Path

__all__ = ["open_store"]


def open_store():  # noqa: ANN201
    """``news.db`` beside the other stores -- the path comes from config, never a literal."""
    from genesis.config import load_config
    from genesis.news.store import NewsStore

    return NewsStore(Path(load_config().memory.db_path).expanduser().parent / "news.db")
