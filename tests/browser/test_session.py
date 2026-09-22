# Spec: Genesis Markdown/10-Architecture/Web Access.md §The presentation surface
"""The address bar, which is the only branch here that can be silently wrong.

Everything else in `browser/session.py` is a CDP round trip and can only be
tested against a running Chromium. This can be tested against nothing, so it is.
"""

from __future__ import annotations

import pytest

from genesis.browser.session import SEARCH, BrowserSession, resolve_url


@pytest.mark.parametrize(
    ("typed", "want"),
    [
        ("tradingview.com", "https://tradingview.com"),
        ("  https://x.com/home ", "https://x.com/home"),
        ("example.co.uk/a/b", "https://example.co.uk/a/b"),
        ("about:blank", "about:blank"),
        ("", "about:blank"),
        # Loopback is http, because nothing on this machine serves TLS.
        ("localhost:5273", "http://localhost:5273"),
        ("127.0.0.1:8765/v1/health", "http://127.0.0.1:8765/v1/health"),
        # Not a host. Guessing `https://` here is a 404 where an answer was wanted.
        ("what is gann theory", SEARCH.format("what+is+gann+theory")),
        ("gann", SEARCH.format("gann")),
    ],
)
def test_address_bar(typed: str, want: str) -> None:
    assert resolve_url(typed) == want


@pytest.mark.parametrize("hostile", ["javascript:alert(1)", "data:text/html,<b>x", "chrome://settings"])
def test_only_followable_schemes_are_followed(hostile: str) -> None:
    """An address bar is where a person pastes what a stranger sent them.

    `javascript:` and `data:` turn a typed string into code running in whatever
    origin is loaded. They must come out the other side as a search, not as a
    navigation.
    """
    resolved = resolve_url(hostile)
    assert resolved.startswith("https://")
    assert not resolved.startswith(("javascript:", "data:", "chrome:"))


def test_unknown_events_are_refused_before_the_socket() -> None:
    """A bad event name must not reach CDP as a malformed command."""
    session = BrowserSession()
    with pytest.raises(ValueError):
        session.mouse("teleport", 1, 1)
    with pytest.raises(ValueError):
        session.key("a")  # printable text goes through `text()`, not the key table
