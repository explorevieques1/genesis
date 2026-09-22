# Spec: Genesis Markdown/60-UI/Voice UX.md
"""When Genesis speaks unprompted — Voice UX's table, as assertions."""

from __future__ import annotations

import pytest

from genesis.voice.policy import REQUESTED, Presence, SpeechPolicy, Urgency


@pytest.fixture
def clock():
    now = {"t": 1000.0}
    return now


def policy_at(clock, *, window: float = 300.0) -> SpeechPolicy:
    return SpeechPolicy(Presence(window_sec=window, _clock=lambda: clock["t"]))


# -- always -------------------------------------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        "position.invalidated",
        "risk.breach",
        "risk.approaching_limit",
        "order.filled",
        "propfirm.warning",
        "reconciliation.failed",
        "system.halt",
        "execution.component_down",
    ],
)
def test_money_and_safety_speak_even_to_an_empty_room(clock, event: str) -> None:
    policy = policy_at(clock)  # no voice activity has ever been recorded
    assert policy.presence.present is False
    assert policy.should_speak(event) is True


@pytest.mark.parametrize("event", ["risk.breach", "position.invalidated", "system.halt"])
def test_muting_cannot_silence_a_safety_event(clock, event: str) -> None:
    """Otherwise "be quiet" becomes a safety control by accident."""
    policy = policy_at(clock)
    policy.muted = True
    assert policy.should_speak(event) is True


# -- if present ---------------------------------------------------------------


@pytest.mark.parametrize("event", ["idea.high_confidence", "level.touched", "brief.ready"])
def test_the_useful_but_not_urgent_wait_for_you_to_be_there(clock, event: str) -> None:
    policy = policy_at(clock)
    assert policy.should_speak(event) is False

    policy.presence.heard_something()
    assert policy.should_speak(event) is True


def test_presence_decays(clock) -> None:
    policy = policy_at(clock, window=300.0)
    policy.presence.heard_something()
    clock["t"] += 299
    assert policy.presence.present is True
    clock["t"] += 2
    assert policy.presence.present is False


def test_muting_holds_the_merely_useful(clock) -> None:
    policy = policy_at(clock)
    policy.presence.heard_something()
    policy.muted = True
    assert policy.should_speak("idea.high_confidence") is False


# -- never --------------------------------------------------------------------


@pytest.mark.parametrize(
    "event",
    ["task.done", "agent.completed", "level.approaching", "agent.degraded", "research.finding"],
)
def test_routine_completions_stay_on_the_dashboard(clock, event: str) -> None:
    policy = policy_at(clock)
    policy.presence.heard_something()  # you are right here, and it still stays quiet
    assert policy.should_speak(event) is False


def test_an_unknown_event_is_silent_by_default(clock) -> None:
    """A new event kind must not be able to start talking by existing."""
    policy = policy_at(clock)
    policy.presence.heard_something()
    assert policy.should_speak("some.new.event") is False
    assert policy.urgency("some.new.event") is Urgency.NEVER


# -- the one that is not an unprompted event ----------------------------------


def test_work_you_asked_for_is_always_spoken(clock) -> None:
    """A four-minute backtest you requested is not a "routine agent
    completion" — you asked, so an answer is owed."""
    policy = policy_at(clock)
    assert policy.should_speak(REQUESTED) is True


def test_the_decision_can_explain_itself(clock) -> None:
    policy = policy_at(clock)
    assert "dashboard only" in policy.explain("task.done")
    assert "always" in policy.explain("risk.breach")
    assert "no recent voice activity" in policy.explain("idea.high_confidence")
    policy.presence.heard_something()
    assert "you're here" in policy.explain("idea.high_confidence")
