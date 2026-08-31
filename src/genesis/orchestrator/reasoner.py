# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""The fail-open path: answering when no deterministic rule and no agent fits.

Orchestrator.md's planning rules end with the one that matters most for how the
system *feels*:

    **Fail open** -- if planning fails, hand the raw utterance to the large tier
    and let it call tools directly. Never leave the user unanswered.

Until Phase 4 there are no agents to plan for, so this is the whole of the
non-trivial answer path: the calendar reflex handles what it can, and anything
else reaches Claude. That ordering is not a stopgap -- it is the tier table's
"default down" rule, and it survives into Phase 4 unchanged. What changes later
is that the planner gets a chance in between.

The prompt is the interesting part. Voice UX specifies a persona and a length,
and both are cheaper and more reliable to enforce in the prompt than to repair
afterwards -- but neither is trusted: :func:`~genesis.voice.speech.speakable`
still rewrites every number on the way to the voice, because a model asked to
format prices correctly will mostly do it, and "mostly" is not a property you
want between you and a spoken stop-loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from genesis.errors import GenesisError
from genesis.orchestrator.answers import Answer

__all__ = ["DEFAULT_LENGTH_RULE", "Reasoner", "SYSTEM_PROMPT"]

# Persona and constraints straight from Voice UX. Kept as one frozen string
# because prompt caching is a prefix match: any byte that changes between turns
# invalidates the cache for everything after it, so nothing volatile (no
# timestamp, no session id) may appear here.
SYSTEM_PROMPT = """You are Genesis, a voice-driven trading assistant speaking aloud to one trader.

Persona: calm, concise, precise. A capable colleague, not an assistant and not a \
hype machine.
- Never hype a setup. "NVDA long, confidence 0.72" -- not "great setup on NVDA!"
- Never reassure after a loss. Report it and move on.
- Volunteer the uncomfortable thing.
- Speak numbers exactly. Round only where precision is meaningless.

You are being spoken, not read. Never read out JSON, lists, markdown, or code.

You cannot see market data, place orders, or run analysis -- those agents are not \
built yet. If a request needs one, say so plainly in one sentence rather than \
guessing or inventing a number. Never state a price, level, or position you were \
not given.

If you do not know, say you do not know."""

#: Used when no VerbosityControl is wired. Matches Voice UX's `brief` default,
#: so an unconfigured Reasoner behaves the way the shipped config does.
DEFAULT_LENGTH_RULE = (
    "Answer in one or two sentences. Detail belongs on the dashboard, not in speech."
)


@dataclass
class Reasoner:
    """Answers an utterance on the large tier.

    ``backend`` is any :class:`~genesis.llm.backend.Backend`. Failures return
    ``None`` rather than raising: the caller is on the voice path, and a
    silent Genesis is a worse failure than a degraded one.

    ``verbosity`` is a
    :class:`~genesis.orchestrator.verbosity.VerbosityControl`. Its instruction
    is appended *after* the frozen persona rather than woven into it, so the
    cacheable prefix stays byte-identical and only the tail changes when you
    say "give me the full version" -- which is rare, and is the only thing that
    should ever invalidate the cache.
    """

    backend: object
    max_tokens: int = 300
    verbosity: Any = None

    @property
    def system_prompt(self) -> str:
        if self.verbosity is None:
            return f"{SYSTEM_PROMPT}\n\n{DEFAULT_LENGTH_RULE}"
        return f"{SYSTEM_PROMPT}\n\n{self.verbosity.instruction}"

    def answer(self, text: str, *, context: str = "") -> Answer | None:
        prompt = text if not context else f"Recent conversation:\n{context}\n\nThey just said: {text}"
        try:
            completion = self.backend.complete(
                prompt,
                system=self.system_prompt,
                max_tokens=self.max_tokens,
            )
        except GenesisError:
            return None
        if not completion.text:
            return None
        return Answer(completion.text, f"llm:{completion.model}")
