# Spec: Genesis Markdown/10-Architecture/Biological Design.md
"""Reflexes fire without a model, and cannot be talked out of firing."""

from __future__ import annotations

import pytest

from genesis.voice.echo import EchoFilter
from genesis.voice.reflex import Reflex, match_reflex


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("Genesis, halt", Reflex.HALT),
        ("genesis halt now", Reflex.HALT),
        ("Genesis, flatten everything", Reflex.FLATTEN),
        ("flatten everything, Genesis", Reflex.FLATTEN),  # wake word anywhere
        ("Genesis, pause", Reflex.PAUSE),
        ("Genesis, mute", Reflex.MUTE),
        ("stop", Reflex.STOP),  # no wake word needed
    ],
)
def test_reflexes_fire(utterance, expected):
    hit = match_reflex(utterance)
    assert hit is not None and hit.reflex is expected


@pytest.mark.parametrize(
    "utterance",
    [
        "the halt was lifted this morning",  # market chatter, not a command
        "he stopped trading last year",      # whole-word matching
        "what do you think about NVDA",
        "",
    ],
)
def test_conversation_does_not_fire_reflexes(utterance):
    assert match_reflex(utterance) is None


def test_halt_needs_the_wake_word_but_stop_does_not():
    """Asymmetric on purpose: 'halt' occurs in ordinary market talk, so a kill
    switch firing on overheard speech would be worse than one needing a name.
    'stop' must work bare, because you say it while being talked over."""
    assert match_reflex("halt") is None
    assert match_reflex("stop") is not None


def test_reflex_precedence_is_most_specific_first():
    hit = match_reflex("Genesis, flatten everything and stop")
    assert hit is not None and hit.reflex is Reflex.FLATTEN


def test_stop_is_never_swallowed_as_echo():
    """Voice Stack records this exact bug from the reference implementation:
    'stop' during speech filtered as echo. It must be impossible here."""
    echo = EchoFilter()
    echo.note_spoken("stop one eighteen forty, risk three hundred twelve dollars")
    assert echo.is_echo("stop") is False
    assert echo.is_echo("stop one eighteen forty") is False


def test_echo_filter_catches_our_own_voice():
    echo = EchoFilter()
    echo.note_spoken("N-V-D-A long from one twenty-one oh six")
    assert echo.is_echo("N V D A long from one twenty one oh six") is True
    assert echo.is_echo("what about SPY") is False


# -- regressions found by the live end-to-end test -------------------------


def test_halt_fires_on_whisper_homophones():
    """Observed in testing: "Genesis, halt" came back from Whisper as
    "Genesis Holt" and the kill switch did not fire. A reflex that needs
    perfect transcription is not a reflex."""
    for heard in ("Genesis Holt", "Genesis, hault", "Genesis hold it", "genesis alt"):
        hit = match_reflex(heard)
        assert hit is not None and hit.reflex is Reflex.HALT, heard


def test_homophones_still_need_the_wake_word():
    """The generosity above is only safe because the wake word gates it."""
    assert match_reflex("the holt was lifted this morning") is None
    assert match_reflex("hold it right there") is None


def test_stop_as_a_noun_is_not_a_command():
    """"What's the stop?" asks for a stop-loss price and appears in the notes'
    own list of legitimate follow-ups. It must not cut speech."""
    assert match_reflex("what's the stop") is None
    assert match_reflex("what is the stop on NVDA") is None
    # ...while the command itself still works bare.
    assert match_reflex("stop") is not None
    assert match_reflex("stop it") is not None
