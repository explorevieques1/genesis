# Spec: Genesis Markdown/10-Architecture/Biological Design.md
"""The spinal phrase table -- what Genesis obeys before it thinks.

Voice UX states the requirement plainly:

    "Genesis, halt" triggers Kill Switch and is recognized **before** intent
    classification -- it never waits for an LLM.

Biological Design says why this is structural rather than an optimisation: a
reflex arc does not route through the brain, and **a reflex cannot be talked
out of firing by a persuasive prompt**. If halting depended on a model
classifying the utterance, then halting would be as reliable as that model --
which is to say, not reliable enough for the thing you say when money is
leaving and you want it to stop.

So this module is a table and a normaliser. No imports beyond the standard
library, no network, no model, no configuration that could disable an entry.
It is checked first on every transcript, including partial ones, and including
while Genesis is speaking.

The set is deliberately tiny. Every phrase here is one the orchestrator can
never reinterpret, so adding a phrase permanently removes it from the space of
things you can say conversationally.
"""

from __future__ import annotations

import re
from enum import Enum

__all__ = ["Reflex", "ReflexMatch", "match_reflex", "STOP_WORDS"]


class Reflex(str, Enum):
    """The five actions that bypass intent classification."""

    HALT = "halt"
    """Kill Switch: cancel working orders, mode -> halt. The heaviest reflex."""

    FLATTEN = "flatten"
    """Kill Switch with flatten: close open positions as well."""

    STOP = "stop"
    """Cut TTS mid-word. Does not touch trading."""

    PAUSE = "pause"
    """Suspend agent cadence. Positions and orders are untouched."""

    MUTE = "mute"
    """Stop unprompted speech. The system keeps working, silently."""


class ReflexMatch(tuple):
    """A matched reflex and the phrase that fired it, for the audit log."""

    __slots__ = ()

    def __new__(cls, reflex: Reflex, phrase: str) -> ReflexMatch:
        return super().__new__(cls, (reflex, phrase))

    @property
    def reflex(self) -> Reflex:
        return self[0]

    @property
    def phrase(self) -> str:
        return self[1]


#: Bare words that cut speech even without the wake word. Voice UX: *"'Stop'
#: cuts speech in under 300 ms and is never filtered as echo."* Kept separate
#: from the table below because :mod:`genesis.voice.echo` needs to consult it
#: to honour that second clause.
STOP_WORDS: frozenset[str] = frozenset({"stop", "quiet", "shut up", "cancel"})

# Ordered most-specific first: "flatten everything" must win over "halt" in a
# sentence containing both, and both must win over a bare "stop".
#
# Several entries are homophones rather than words anyone would say. They are
# here because the transcript is what a speech model *heard*, not what was
# said, and a reflex that needs perfect transcription is not a reflex. Observed
# in testing: "Genesis, halt" came back from Whisper as "Genesis Holt", and the
# kill switch did not fire. A missed halt is the expensive direction of this
# error; a false halt costs a flat book and an apology, which is recoverable.
# So the homophones are deliberately generous, and are safe *because* every
# entry in this group still requires the wake word.
_TABLE: tuple[tuple[Reflex, tuple[str, ...]], ...] = (
    (
        Reflex.FLATTEN,
        (
            "flatten everything", "flatten all", "flatten the book",
            "close everything", "flat and everything", "flatten every thing",
        ),
    ),
    (
        Reflex.HALT,
        (
            "halt", "kill switch", "emergency stop", "shut it down",
            # Whisper's observed renderings of "halt":
            "holt", "hault", "halte", "hold it", "alt",
        ),
    ),
    (
        Reflex.PAUSE,
        ("pause", "stop scanning", "hold off"),
    ),
    (
        Reflex.MUTE,
        ("mute", "be quiet", "stop talking"),
    ),
    (
        Reflex.STOP,
        tuple(sorted(STOP_WORDS)),
    ),
)

_PUNCT = re.compile(r"[^a-z0-9\s]+")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    STT output is unpunctuated and inconsistently cased, and the difference
    between ``"Genesis, halt."`` and ``"genesis halt"`` must never be the
    reason a kill switch did not fire.
    """
    return _SPACE.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


def match_reflex(text: str, *, wake_word: str = "genesis") -> ReflexMatch | None:
    """Return the reflex this utterance fires, or ``None``.

    Two matching rules, and the asymmetry between them is the safety argument:

    * :attr:`Reflex.STOP` fires with or without the wake word -- you will say
      "stop" while it is talking over you, and requiring "Genesis, stop" there
      would make the barge-in useless -- but **always** as a bare command, never
      as a word inside a sentence. Addressing Genesis does not change that:
      *"Genesis, what's the stop on NVDA"* and *"Genesis, cancel my three
      o'clock"* are requests, and answering them is the correct behaviour.
      Treating them as an interrupt swallows the request entirely and the
      operator gets silence.
    * Everything else requires the **wake word in the utterance**. "Halt" is a
      word that occurs in ordinary speech about markets ("the halt was
      lifted"), and a kill switch that fires on overheard conversation is worse
      than one that occasionally needs repeating. These match anywhere in the
      sentence, because "Genesis, halt everything" and "flatten everything,
      Genesis" must both work.

    Matching is substring-on-word-boundary, so wake position does not matter --
    Voice Stack requires *"Give me the semis setup, Genesis"* to work, and the
    same must hold for *"flatten everything, Genesis"*.
    """
    if not text:
        return None
    norm = normalise(text)
    if not norm:
        return None
    wake = normalise(wake_word)
    addressed = _contains_phrase(norm, wake) if wake else False

    words = norm.split()
    # The stop family is judged on the utterance with the wake word removed, so
    # that "Genesis, stop" is still a bare command while "Genesis, what's the
    # stop on NVDA" is not.
    bare_words = [w for w in words if w != wake] if wake else words

    for reflex, phrases in _TABLE:
        for phrase in phrases:
            if not _contains_phrase(norm, phrase):
                continue
            if reflex is Reflex.STOP:
                # Bare-command only, addressed or not. See the docstring.
                if _is_bare_command(bare_words, phrase):
                    return ReflexMatch(reflex, phrase)
                continue
            if addressed:
                return ReflexMatch(reflex, phrase)
    return None


def _is_bare_command(words: list[str], phrase: str) -> bool:
    """True when the utterance *is* the stop command, not a sentence about it.

    "stop" and "stop it" cut speech. "what's the stop?" is a question about a
    stop-loss price and must not -- it appears in the notes' own list of
    legitimate follow-ups, right alongside the requirement that a bare "stop"
    always works.

    The discriminator is that a command is short and leads with the word. You
    do not preface an interrupt; you say it. Anything longer is speech *about*
    stopping, which is a thing traders say all day.

    Repetition is the exception, and it is the opposite of an edge case: "stop
    stop stop" is what people actually say when something will not shut up, and
    it is *more* emphatic than a single "stop", not less. Under the length rule
    alone it failed, which is the worst possible place for this function to be
    strict.
    """
    phrase_words = phrase.split()
    if words[: len(phrase_words)] != phrase_words:
        return False
    if len(words) <= len(phrase_words) + 1:
        return True
    # "stop stop stop" -- the same command, said harder.
    return all(
        words[i : i + len(phrase_words)] == phrase_words
        for i in range(0, len(words) - len(phrase_words) + 1, len(phrase_words))
    ) and len(words) % len(phrase_words) == 0


def _contains_phrase(haystack: str, needle: str) -> bool:
    """Whole-word containment. ``stop`` must not match ``stopped``."""
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None
