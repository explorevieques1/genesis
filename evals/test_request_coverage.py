# Spec: Genesis Markdown/20-Agents/Agent Index.md
"""Can Genesis reach what the desk actually asks for?

:mod:`corpora.requests` holds a hundred real utterances, each declaring the
capabilities its answer needs. This suite points that corpus at the *live*
gateway and reports the gap. It is a build tracker with a test runner attached:
the number that matters is how many of the hundred are answerable today, and it
should go up as servers are wired.

Deliberately **not** a pass/fail gate on coverage. Most of the corpus needs
agents that Phase 4 has not built, and a suite that fails for a hundred known
reasons is a suite people stop reading. What *does* fail here is regression: a
capability that was reachable and stopped being reachable, which is the failure
that otherwise goes unnoticed until someone asks out loud and gets an apology.

Two real findings this suite exists to keep visible:

* ``chart.render`` is the single most-wanted missing capability -- eleven of the
  hundred requests need it, and [[genesis-tradingview-mcp]] is spec'd, spiked
  YES, and not built.
* ``maverick`` registers zero screening and zero research tools unless its
  extras are installed, which silently costs ``screen.custom`` and most of the
  ``ta.*`` family. The server is *up*, so nothing errors.

Building the gateway spawns every configured server, so this is slow by nature
and lives in ``evals`` rather than ``tests``.
"""

from __future__ import annotations

from collections import Counter

import pytest

from corpora.requests import FAMILY, REQUESTS, TOTAL

#: Capabilities that are reachable today and must stay reachable. A name here
#: is a promise: it was verified live, and losing it is a regression rather
#: than an unbuilt feature. Add to this list when a server is wired, never
#: remove from it to make the suite pass.
LOCKED: frozenset[str] = frozenset(
    {
        "time.now",
        "web.search",
        "web.read",
        "news.headlines",
        "filings.recent",
        "macro.series",
        "market-data.quote",
        "market-data.ohlcv",
        "vault.search",
        "vault.create",
    }
)


@pytest.fixture(scope="module")
def live_capabilities() -> frozenset[str]:
    """Every capability the running gateway can actually serve."""
    from genesis.mcp.build import build_gateway

    build = build_gateway()
    return frozenset(spec.capability for spec in build.gateway.registry)


@pytest.fixture(scope="module")
def orchestrator_capabilities(live_capabilities) -> frozenset[str]:
    """What the *voice* can reach, which is narrower than the catalogue."""
    from genesis.mcp.build import ALLOW_LISTS
    from genesis.mcp.allowlist import matches

    patterns = ALLOW_LISTS["orchestrator"]
    return frozenset(
        cap for cap in live_capabilities if any(matches(p, cap) for p in patterns)
    )


def test_the_corpus_is_the_size_it_claims() -> None:
    assert len(REQUESTS) == TOTAL == 100


def test_every_owner_has_a_family() -> None:
    """An agent with no family cannot be risk-gated, and Agent Index gates by
    family. A missing entry is a spec bug, not a corpus typo."""
    orphans = sorted({r.agent for r in REQUESTS if r.agent not in FAMILY})
    assert not orphans, f"agents missing from FAMILY: {orphans}"


def test_no_request_is_satisfied_by_an_order_tool() -> None:
    """Safety Invariants §1, asserted against the corpus itself. Every write
    goes through propose_order -> approval -> place_approved. There is no
    place_order, and a corpus entry naming one would be a design leak."""
    for request in REQUESTS:
        for cap in request.caps:
            assert "place_order" not in cap, f"{request.text!r} names {cap}"


def test_locked_capabilities_are_still_reachable(live_capabilities) -> None:
    """The regression gate. Everything else here reports; this one fails."""
    lost = sorted(LOCKED - live_capabilities)
    assert not lost, (
        f"{len(lost)} capability(ies) that used to work are gone: {lost}. "
        f"A server is down, renamed a tool, or lost an extra."
    )


def test_the_orchestrator_can_reach_what_it_is_granted(
    orchestrator_capabilities,
) -> None:
    """A grant that resolves to nothing is the failure that looks like success:
    the allow-list is generous, the catalogue is full, and the two do not
    overlap."""
    assert orchestrator_capabilities, "the orchestrator's allow-list matches no tool"


def test_report_coverage(live_capabilities, orchestrator_capabilities) -> None:
    """Not an assertion -- the scoreboard. Run with `-s` to read it."""
    wanted = Counter(c for r in REQUESTS for c in r.caps)
    missing = {c: n for c, n in wanted.items() if c not in live_capabilities}

    served, partial, unserved, stateful = [], [], [], []
    for request in REQUESTS:
        if not request.caps:
            stateful.append(request)
        elif all(c in live_capabilities for c in request.caps):
            served.append(request)
        elif any(c in live_capabilities for c in request.caps):
            partial.append(request)
        else:
            unserved.append(request)

    answerable = len(served) + len(stateful)
    print(f"\n{'=' * 66}")
    print(f"  ANSWERABLE TODAY          {answerable:3d} / {TOTAL}")
    print(f"{'=' * 66}")
    print(f"  fully served by tools     {len(served):3d}")
    print(f"  need no tool at all       {len(stateful):3d}")
    print(f"  partially served          {len(partial):3d}")
    print(f"  no live tool              {len(unserved):3d}")
    print(f"\n  catalogue capabilities    {len(live_capabilities):3d}")
    print(f"  reachable by the voice    {len(orchestrator_capabilities):3d}")

    if missing:
        print(f"\n  MISSING, by how often the desk asks:")
        for cap, n in sorted(missing.items(), key=lambda kv: -kv[1]):
            print(f"    {n:3d} refs  {cap}")

    print(f"\n  fully-served requests by family:")
    for family, n in Counter(FAMILY[r.agent] for r in served).most_common():
        print(f"    {n:3d}  {family}")
    print()


@pytest.mark.skip(reason="Phase 4 — no agent is registered to route to yet")
def test_requests_route_to_their_owning_agent() -> None:
    """The real routing eval: does the planner name the agent the corpus says
    owns each request? Misrouting is quiet -- the wrong agent usually produces
    a plausible answer rather than an error -- which is why this is an eval and
    not a unit test."""
    raise AssertionError("not implemented")
