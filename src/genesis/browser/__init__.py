# Spec: Genesis Markdown/10-Architecture/Web Access.md
"""The presentation plane: a real browser, painted into a Genesis panel."""

from genesis.browser.session import (
    BrowserUnavailable,
    KEYS,
    close,
    resolve_url,
    session,
)

__all__ = ["BrowserUnavailable", "KEYS", "close", "resolve_url", "session"]
