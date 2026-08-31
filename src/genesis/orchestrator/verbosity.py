# Spec: Genesis Markdown/60-UI/Voice UX.md
"""How much Genesis says, and how you change it mid-sentence.

Voice UX gives three levels and one requirement that is easy to miss:
*"Configurable, and switchable mid-conversation ('give me the full version')."*
A level that can only be set in a YAML file is not switchable mid-conversation,
so this module is both halves -- the level itself, and the deterministic
recogniser that changes it when you say so.

Deterministic on purpose. *"Be brief"* is a command, not a question, and
routing it through a model would make the cheapest possible request into the
most expensive rung of the answer ladder. It belongs with the other reflexes
in :mod:`genesis.orchestrator.answers`: pattern in, sentence out, no network.

The level reaches speech as an instruction on the large tier's system prompt.
It is deliberately *not* enforced by truncating the model's reply: cutting a
sentence in half mid-number is a worse failure than a reply that ran long, and
this system speaks prices aloud.
"""

from __future__ import annotations

import re
from enum import IntEnum

from genesis.orchestrator.answers import Answer

__all__ = ["Verbosity", "VerbosityControl"]


class Verbosity(IntEnum):
    """The three levels, ordered shortest to longest."""

    TERSE = 0
    BRIEF = 1
    FULL = 2

    @property
    def wire_name(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: str | Verbosity) -> Verbosity:
        if isinstance(value, Verbosity):
            return value
        try:
            return cls[value.upper()]
        except KeyError:
            raise ValueError(f"unknown verbosity {value!r}") from None


#: The length instruction each level puts on the prompt. Written as sentence
#: counts because that is what a model reliably honours -- word budgets are
#: approximated, sentence counts are obeyed.
INSTRUCTIONS: dict[Verbosity, str] = {
    Verbosity.TERSE: (
        "Answer in one short sentence. Numbers and the conclusion only, no "
        "reasoning, no preamble."
    ),
    Verbosity.BRIEF: (
        "Answer in one or two sentences. Detail belongs on the dashboard, not "
        "in speech."
    ),
    Verbosity.FULL: (
        "Answer in up to five sentences. Include the reasoning, the catalyst, "
        "and anything that would change your mind. Still speech, so no lists "
        "and no markdown."
    ),
}

# Ordered most specific first. "give me the full version" also matches a bare
# "full", so a single pass over an unordered table would resolve it by luck.
_PHRASES: tuple[tuple[Verbosity, str], ...] = (
    (Verbosity.FULL, r"\b(the )?(full|long|whole) (version|thing|story|detail)\b"),
    (Verbosity.FULL, r"\b(tell|give) me (everything|more|the details?)\b"),
    (Verbosity.FULL, r"\b(be |go |talk )?(more )?(verbose|detailed|thorough)\b"),
    (Verbosity.TERSE, r"\b(be |keep it |just )?(terse|short|brief and|minimal)\b"),
    (Verbosity.TERSE, r"\b(shorter|less detail|cut it down|headlines? only)\b"),
    (Verbosity.BRIEF, r"\b(be |keep it )?brief\b"),
    (Verbosity.BRIEF, r"\bnormal (length|verbosity)\b"),
)

_CONFIRMATION: dict[Verbosity, str] = {
    Verbosity.TERSE: "Terse it is.",
    Verbosity.BRIEF: "Back to brief.",
    Verbosity.FULL: "Full detail from now on.",
}


class VerbosityControl:
    """Holds the current level and recognises requests to change it.

    Lives for the session. Voice UX calls a spoken change *mid-conversation*,
    which is a runtime thing -- persisting it would mean a passing remark
    silently rewriting config, and [[Config And Secrets]] keeps behaviour in
    the file and out of the model's reach.
    """

    def __init__(self, default: str | Verbosity = Verbosity.BRIEF) -> None:
        self._default = Verbosity.parse(default)
        self._level = self._default

    @property
    def level(self) -> Verbosity:
        return self._level

    def set(self, level: str | Verbosity) -> Verbosity:
        self._level = Verbosity.parse(level)
        return self._level

    def reset(self) -> Verbosity:
        self._level = self._default
        return self._level

    @property
    def instruction(self) -> str:
        return INSTRUCTIONS[self._level]

    def answer(self, text: str) -> Answer | None:
        """Handle *"give me the full version"*, or decline.

        Returns ``None`` for anything that is not a verbosity command, which is
        almost everything -- the same contract as
        :class:`~genesis.orchestrator.answers.TrivialAnswerer`, so the two
        chain without either knowing about the other.
        """
        requested = self.detect(text)
        if requested is None:
            return None
        changed = requested is not self._level
        self._level = requested
        return Answer(
            _CONFIRMATION[requested] if changed else f"Already {requested.wire_name}.",
            "verbosity",
        )

    @staticmethod
    def detect(text: str) -> Verbosity | None:
        """The level ``text`` asks for, or ``None``.

        Requires an imperative framing. Without it *"give me the full picture
        on NVDA"* -- a real request about a ticker -- would be swallowed as a
        settings change and answered with "Full detail from now on", which is
        the kind of failure that makes people stop talking to a system.
        """
        q = " ".join(text.lower().split())
        if not q:
            return None
        if not re.search(
            r"\b(be|keep|give me|tell me|make it|go|talk|say|answer|from now on|"
            r"i want|switch to|use)\b",
            q,
        ):
            return None
        # A verbosity command is about *how* to answer. If it also names a
        # subject, it is a request about that subject.
        if re.search(r"\b(on|about|for|of)\s+[a-z]{2,}\b", q) and not re.search(
            r"\b(from now on|for now)\b", q
        ):
            return None
        for level, pattern in _PHRASES:
            if re.search(pattern, q):
                return level
        return None
