# Spec: Genesis Markdown/60-UI/Voice UX.md
"""Verbosity: the level, and changing it mid-conversation."""

from __future__ import annotations

import pytest

from genesis.orchestrator.reasoner import Reasoner
from genesis.orchestrator.verbosity import Verbosity, VerbosityControl


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("give me the full version", Verbosity.FULL),
        ("tell me everything", Verbosity.FULL),
        ("be more detailed from now on", Verbosity.FULL),
        ("be terse", Verbosity.TERSE),
        ("keep it short", Verbosity.TERSE),
        ("give me the headlines only", Verbosity.TERSE),
        ("be brief", Verbosity.BRIEF),
        ("keep it brief", Verbosity.BRIEF),
    ],
)
def test_a_spoken_verbosity_change_is_recognised(said: str, expected: Verbosity) -> None:
    assert VerbosityControl.detect(said) is expected


@pytest.mark.parametrize(
    "said",
    [
        "give me the full picture on NVDA",   # a request about a ticker
        "what's the full size of my position",
        "how did semis close",
        "what time does the market open",
        "",
        "short interest on TSLA",
    ],
)
def test_a_real_request_is_not_swallowed_as_a_settings_change(said: str) -> None:
    """The failure this guards against is the worst kind: a question answered
    with "Full detail from now on", which teaches you to stop asking."""
    assert VerbosityControl.detect(said) is None


def test_changing_the_level_is_confirmed_out_loud() -> None:
    control = VerbosityControl("brief")
    answer = control.answer("give me the full version")
    assert answer is not None
    assert answer.source == "verbosity"
    assert control.level is Verbosity.FULL


def test_asking_for_the_level_you_already_have_says_so() -> None:
    control = VerbosityControl("brief")
    assert "Already brief" in control.answer("be brief").text


def test_anything_else_is_declined_so_the_next_rung_gets_it() -> None:
    assert VerbosityControl("brief").answer("what time does the market open") is None


def test_the_level_survives_until_changed_and_never_touches_config() -> None:
    control = VerbosityControl("brief")
    control.answer("be terse")
    assert control.level is Verbosity.TERSE
    control.reset()
    assert control.level is Verbosity.BRIEF, "reset returns to the configured default"


def test_the_level_reaches_the_model_as_a_length_rule() -> None:
    control = VerbosityControl("terse")
    reasoner = Reasoner(None, verbosity=control)
    assert "one short sentence" in reasoner.system_prompt(tools=False)

    control.set(Verbosity.FULL)
    assert "up to five sentences" in reasoner.system_prompt(tools=False)


def test_the_cacheable_persona_prefix_does_not_move_when_the_level_changes() -> None:
    """Prompt caching is a prefix match, so the instruction goes at the end.
    A level change must invalidate the tail, not the persona."""
    control = VerbosityControl("brief")
    reasoner = Reasoner(None, verbosity=control)
    before = reasoner.system_prompt(tools=False)
    control.set(Verbosity.FULL)
    after = reasoner.system_prompt(tools=False)

    shared = before[: min(len(before), len(after))]
    common = len(_common_prefix(before, after))
    assert common > 0.8 * len(shared.split("\n\n")[0])


def test_an_unwired_control_still_gets_the_shipped_default() -> None:
    assert "one or two sentences" in Reasoner(None).system_prompt(tools=False)


def _common_prefix(a: str, b: str) -> str:
    out = []
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        out.append(x)
    return "".join(out)
