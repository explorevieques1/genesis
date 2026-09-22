# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""Eval: directed vs. ambient vs. follow-up vs. stop.

Voice Stack and Voice UX state three criteria as *rates*, not as examples:

- wake word detected in **any sentence position**, ≥95% over a 100-utterance set
- **zero** actions triggered by ten minutes of ambient conversation
- **"stop" is never swallowed** — not by echo filtering, not by anything

The costly errors are asymmetric, so the thresholds are too. Acting on ambient
conversation is worse than missing a directed utterance — the first talks over
your meeting, the second costs you one repetition — and failing to hear "stop"
is worst of all. So ambient and stop are scored at 100% and only wake detection
gets the 95% allowance.

**Scope.** This grades the *text* classifier: wake-word position, reflex
precision, the follow-up window. It cannot grade acoustic wake detection, which
needs audio and a real microphone; that is measured by hand against the same
criterion and recorded in Voice Stack's latency table.

It lives in ``evals/`` rather than ``tests/`` because it is a graded rate over a
corpus, which is the line ``Conventions.md`` draws. Today the classifier is
deterministic, so the rates are stable — and if a judge is ever wired into the
residue path, this suite is already the thing that would catch it drifting.
"""

from __future__ import annotations

import pytest

from corpora import intent as corpus
from genesis.orchestrator.intent import Intent, IntentClassifier
from genesis.voice.reflex import Reflex


def classifier() -> IntentClassifier:
    return IntentClassifier(wake_word="genesis")


# -- the corpus itself ---------------------------------------------------------


def test_the_corpus_is_big_enough_to_mean_something() -> None:
    """The criterion says a 100-utterance set. A rate over twelve examples is
    not a rate."""
    assert corpus.TOTAL >= 95
    assert len(corpus.AMBIENT) >= 30


# -- wake anywhere -------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "utterances"),
    [
        ("leading", corpus.DIRECTED_LEADING),
        ("medial", corpus.DIRECTED_MEDIAL),
        ("trailing", corpus.DIRECTED_TRAILING),
    ],
)
def test_the_wake_word_is_heard_in_every_sentence_position(name: str, utterances: list[str]) -> None:
    """Voice Stack: *"Give me the semis setup, Genesis" must work.*"""
    c = classifier()
    missed = [u for u in utterances if not c.classify(u).actionable]
    assert not missed, f"{name}: missed {missed}"


def test_wake_detection_clears_the_ninety_five_percent_bar() -> None:
    c = classifier()
    hits = sum(1 for u in corpus.DIRECTED if c.classify(u).actionable)
    rate = hits / len(corpus.DIRECTED)
    assert rate >= 0.95, f"wake recall {rate:.0%} over {len(corpus.DIRECTED)} utterances"


# -- zero actions from the room ------------------------------------------------


def test_ambient_conversation_produces_no_actions_at_all() -> None:
    """Not a rate. Zero."""
    c = classifier()
    acted = [u for u in corpus.AMBIENT if c.classify(u).actionable]
    assert acted == [], f"{len(acted)} ambient utterance(s) would have been acted on: {acted}"


def test_no_ordinary_sentence_fires_a_reflex() -> None:
    """The expensive false positive. "What's the stop on that trade" is a
    question about a trade; halting the system over it would be the single
    most disruptive misclassification available."""
    c = classifier()
    fired = [
        (u, r.reflex.value)
        for u in corpus.AMBIENT_WITH_REFLEX_WORDS
        if (r := c.classify(u)).intent is Intent.STOP
    ]
    assert fired == [], f"reflexes fired on ordinary speech: {fired}"


# -- stop is never swallowed ---------------------------------------------------


def test_every_stop_phrase_fires_the_reflex() -> None:
    c = classifier()
    missed = [u for u in corpus.STOP if c.classify(u).intent is not Intent.STOP]
    assert missed == [], f"stop was swallowed on: {missed}"


def test_stop_fires_even_when_it_looks_exactly_like_our_own_voice() -> None:
    """The known failure from the reference implementation: "stop" arriving
    during playback, filtered as echo. Reflexes are checked before the echo
    filter for exactly this reason."""
    from genesis.voice.echo import EchoFilter

    echo = EchoFilter()
    echo.note_spoken("stop")
    c = IntentClassifier(wake_word="genesis", echo=echo)
    assert c.classify("stop").intent is Intent.STOP


def test_the_halt_phrases_reach_the_kill_switch_not_just_the_speaker() -> None:
    """"Stop" cuts speech; "halt" is a different and much larger action."""
    c = classifier()
    halts = [
        u for u in corpus.STOP
        if any(w in u.lower() for w in ("halt", "flatten", "kill", "shut it down"))
    ]
    assert halts, "the corpus lost its heavy reflexes"
    for utterance in halts:
        result = c.classify(utterance)
        assert result.reflex in (Reflex.HALT, Reflex.FLATTEN), utterance


def test_a_heavy_reflex_never_fires_without_the_wake_word() -> None:
    """The asymmetry that makes a bare-keyword kill switch safe at all.

    "Halt" and "flatten" are ordinary words in market talk. Requiring the wake
    word for them costs one repetition in an emergency; not requiring it costs
    a flat book because someone across the room mentioned a trading halt.
    """
    c = classifier()
    fired = [
        (u, r.reflex.value)
        for u in corpus.HEAVY_WITHOUT_WAKE
        if (r := c.classify(u)).reflex in (Reflex.HALT, Reflex.FLATTEN)
    ]
    assert fired == [], f"a heavy reflex fired on unaddressed speech: {fired}"


# -- the follow-up window ------------------------------------------------------


def test_short_continuations_land_inside_the_window() -> None:
    c = classifier()
    missed = []
    for utterance in corpus.FOLLOW_UP:
        c.open_follow_up()
        if not c.classify(utterance).actionable:
            missed.append(utterance)
    assert missed == [], f"follow-ups dropped: {missed}"


def test_the_window_does_not_swallow_the_room() -> None:
    """The bug the live test caught: Genesis answers, you turn to a colleague,
    and the next two sentences land inside the window and get answered."""
    c = classifier()
    acted = []
    for utterance in corpus.AMBIENT_CONVERSATION:
        c.open_follow_up()
        if c.classify(utterance).actionable:
            acted.append(utterance)
    rate = len(acted) / len(corpus.AMBIENT_CONVERSATION)
    # This is the adversarial case, not the realistic one: the window is
    # re-opened before *every* sentence, as if Genesis had just spoken each
    # time. Realistically it opens once and expires in four seconds.
    #
    # The residual risk is real and measured here rather than hidden: a short
    # remark made to a person within seconds of a reply can still be taken as
    # a follow-up. The mitigation is length, so what must never happen is a
    # *conversation* getting through -- and the long sentences, which is most
    # of them, do not.
    assert rate <= 0.25, f"{rate:.0%} of ambient speech was actioned inside the window: {acted}"
    long_ones = [u for u in acted if len(u.split()) > 6]
    assert long_ones == [], f"the length heuristic failed on: {long_ones}"


# -- the latency claim ---------------------------------------------------------


def test_classification_stays_far_inside_its_budget() -> None:
    """Voice Stack budgets 100 ms for intent. Deterministic classification
    should not be within an order of magnitude of that."""
    c = classifier()
    worst = max(c.classify(u).latency_ms for u in corpus.DIRECTED + corpus.AMBIENT)
    assert worst < 10.0, f"slowest classification was {worst:.1f} ms"
