# Spec: Genesis Markdown/60-UI/UI Stack.md §9 What the UI never does
"""Every read route answers in the envelope the UI reads.

`Envelope<T>` is `{available: true} & T` or `{available: false, reason}`, and
`useRead` discriminates on that one key: a body without it is treated as
**absent**, with `data: null`. A route that answers `{"ok": true, ...}` instead
therefore renders as "this thing does not exist" — or, if the panel narrows
with a cast rather than the union, crashes reading a field off null. Both
happened to `TI` on its first run.

The three routes here are the ones added most recently; the rule is the
server's, not theirs, and a new read route belongs in this list.
"""

from __future__ import annotations

import pytest
from starlette import testclient

from genesis.server.app import EventBus, build_app

READ_ROUTES = ("/v1/trade-ideas", "/v1/dna", "/v1/biology")


@pytest.fixture()
def client():
    with testclient.TestClient(build_app(EventBus())) as c:
        yield c


@pytest.mark.parametrize("route", READ_ROUTES)
def test_a_read_route_answers_in_the_envelope(client, route: str) -> None:  # noqa: ANN001
    body = client.get(route).json()
    assert "available" in body, (
        f"{route} has no `available` key, so every panel reading it renders "
        f"absent with null data — see UI Stack §9 and `useRead`"
    )
    assert body["available"] in (True, False)
    if body["available"] is False:
        assert body.get("reason"), "an absent answer must say why"


def test_the_trade_ideas_body_carries_what_the_panel_renders(client) -> None:  # noqa: ANN001
    """The fields `TI` reads without guarding, which must therefore exist."""
    body = client.get("/v1/trade-ideas").json()
    if not body["available"]:
        pytest.skip(f"ideas unavailable here: {body.get('reason')}")
    for key in ("actionable", "ideas", "watching", "desk", "degraded"):
        assert key in body, key
    for idea in body["ideas"]:
        # Rendered unconditionally on every card.
        for key in ("rank", "symbol", "direction", "author", "thesis",
                    "invalidation", "conflicts", "blocked"):
            assert key in idea, f"{idea.get('symbol')} is missing {key}"
