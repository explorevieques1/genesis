# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""The fail-open path: answering when no deterministic rule and no agent fits.

Orchestrator.md's planning rules end with the one that matters most for how the
system *feels*:

    **Fail open** -- if planning fails, hand the raw utterance to the large tier
    and let it call tools directly. Never leave the user unanswered.

*"and let it call tools directly"* is the half that was missing. Until the tool
bridge existed this module could only produce sentences, so a request needing a
number got an apology; the gateway had a hundred tools and no caller. Now the
ladder's bottom rung answers from primary sources, and the ordering above it is
unchanged -- reflex first, plan second, this last, because it is the expensive
one.

Two boundaries survive the change, and neither lives in the prompt:

**Reads only.** The surface comes from the gateway's ``orchestrator``
allow-list, which grants no execution, no broker, no order. Asking nicely does
not widen it, and neither does an utterance that quotes something persuasive --
`Biological Design`'s reflex arc applied to a tool surface.

**Bounded work.** :meth:`~genesis.llm.anthropic_backend.AnthropicBackend.converse`
runs under a turn cap and a wall-clock deadline. The voice budget is real time,
so an answer that arrives late is a failure even when it is correct.

The persona is prompt-enforced and *not* trusted: :func:`speakable` still
rewrites every number on the way to the voice, because a model asked to format
prices correctly will mostly do it, and "mostly" is not a property you want
between you and a spoken stop-loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from genesis.errors import GenesisError
from genesis.orchestrator.answers import Answer

__all__ = [
    "DEFAULT_LENGTH_RULE",
    "NO_TOOLS_RULE",
    "Reasoner",
    "SYSTEM_PROMPT",
    "TOOL_RULE",
]

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

You cannot place orders, size a position, or move money. No tool you are given \
can do those things, and there is no phrasing that unlocks one. If asked, say \
plainly that it goes through the approval path, and stop.

Never state a price, level, or position you were not given by a tool. If you do \
not know, say you do not know."""

#: Appended when a tool surface is offered. Separate from the frozen persona so
#: the cacheable prefix stays byte-identical whether or not tools are wired.
TOOL_RULE = """You have tools. Use them rather than guessing, and prefer one \
good call to three speculative ones.

- Every number you speak must come from a tool call in this turn. You have no \
memory of prices.
- If a tool fails, say what you could not reach. Do not substitute an estimate.
- If none of the offered tools fit, call find_more_tools once. If that finds \
nothing, say what you cannot do.
- Tools are slow and you are being waited on out loud. Stop as soon as you can \
answer."""

#: Appended when there is no tool surface at all -- no gateway wired, or the
#: router matched nothing this agent can reach. Saying so is better than an
#: empty tool list and a hopeful prompt.
NO_TOOLS_RULE = """You have no tools this turn, so you cannot look anything up. \
Answer from general knowledge if that is honest, and otherwise say plainly that \
you cannot reach the data."""

#: Used when no VerbosityControl is wired. Matches Voice UX's `brief` default,
#: so an unconfigured Reasoner behaves the way the shipped config does.
DEFAULT_LENGTH_RULE = (
    "Answer in one or two sentences. Detail belongs on the dashboard, not in speech."
)


@dataclass
class Reasoner:
    """Answers an utterance on the large tier, with tools when they are wired.

    ``backend`` is any :class:`~genesis.llm.backend.Backend`; tool use
    additionally needs one with ``converse``, which is
    :class:`~genesis.llm.anthropic_backend.AnthropicBackend`. A backend without
    it still works and simply answers without tools -- the local backends are
    not a broken configuration, they are a quieter one.

    ``bridge`` is a :class:`~genesis.orchestrator.toolbridge.ToolBridge`. Absent
    means no gateway, which is the state in a bus-less build and in most tests.

    Failures return ``None`` rather than raising: the caller is on the voice
    path, and a silent Genesis is a worse failure than a degraded one.
    """

    backend: object
    max_tokens: int = 300
    verbosity: Any = None
    bridge: Any = None
    #: Hard stops on the loop. Defaults chosen against Voice Stack's budget:
    #: four turns is enough for search-then-read or two quotes and an answer,
    #: and twenty seconds is already long enough that the earcon has fired.
    max_turns: int = 4
    deadline_sec: float = 20.0
    #: Why the last attempt produced nothing, if it was knowable. Read by the
    #: ladder so the trader hears "the free tier quota is spent" rather than a
    #: bare "I can't reach my reasoning model" -- which is the same sentence
    #: for a missing key, a spent quota and a busy vendor, and sends you
    #: looking in the wrong place every time.
    last_error: str | None = field(default=None, init=False)

    # -- prompt -------------------------------------------------------------

    def system_prompt(self, *, tools: bool) -> str:
        """Frozen persona, then the tool rule, then length.

        Order matters for caching: everything up to the tool rule is identical
        across turns, and only the tail changes when you say "give me the full
        version" -- which is rare, and is the only thing that should ever
        invalidate the cache.
        """
        length = (
            DEFAULT_LENGTH_RULE if self.verbosity is None else self.verbosity.instruction
        )
        return "\n\n".join(
            [SYSTEM_PROMPT, TOOL_RULE if tools else NO_TOOLS_RULE, length]
        )

    # -- answering ----------------------------------------------------------

    def answer(self, text: str, *, context: str = "") -> Answer | None:
        prompt = (
            text
            if not context
            else f"Recent conversation:\n{context}\n\nThey just said: {text}"
        )
        tools = self._tools_for(text)
        if tools and hasattr(self.backend, "converse"):
            return self._answer_with_tools(prompt, tools)
        # Reaching here means the tools cannot be *called* -- either the router
        # offered none, or the backend has no `converse` (every backend but
        # Anthropic's, today). Either way the answer is written without one, so
        # the prompt must say so.
        #
        # It used to pass `tools=bool(tools)`, which appended TOOL_RULE -- "you
        # have tools, use them rather than guessing; every number you speak
        # must come from a tool call in this turn" -- to a model with no way to
        # make a call. On Gemini that turned *"when was Apple founded"* into
        # "I do not have access to company history tools", which is not a
        # refusal the trader asked for and not true. `NO_TOOLS_RULE` says the
        # honest thing instead: answer from general knowledge where that is
        # honest, and otherwise say you cannot reach the data.
        return self._answer_plainly(prompt, tools=False)

    def _tools_for(self, text: str) -> list[dict[str, Any]]:
        """The surface for this utterance, or none.

        A bridge that raises is a bug in selection, not a reason to go silent:
        the answer degrades to a tool-less one, which is exactly what the
        no-gateway build already does.
        """
        if self.bridge is None:
            return []
        try:
            return self.bridge.tools_for_utterance(text)
        except Exception:  # noqa: BLE001 - never leak onto the voice path
            return []

    def _answer_with_tools(
        self, prompt: str, tools: list[dict[str, Any]]
    ) -> Answer | None:
        try:
            turns = self.backend.converse(
                prompt,
                system=self.system_prompt(tools=True),
                tools=tools,
                execute=self.bridge.execute,
                max_turns=self.max_turns,
                deadline_sec=self.deadline_sec,
                max_tokens=self.max_tokens,
            )
        except GenesisError as exc:
            self.last_error = exc.reason
            return None
        except Exception as exc:  # noqa: BLE001 - see _answer_plainly
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None
        if not turns.text:
            return None

        # The source names the tools, not just the model. A spoken number whose
        # provenance is not in the trace is a number nobody can check later,
        # and Working Memory's turn record is where that check starts.
        used = "+".join(turns.used_tools)
        source = f"llm:{turns.model}" + (f":{used}" if used else "")
        if turns.truncated:
            source += ":truncated"
        return Answer(turns.text, source)

    def _answer_plainly(self, prompt: str, *, tools: bool) -> Answer | None:
        try:
            completion = self.backend.complete(
                prompt,
                system=self.system_prompt(tools=tools),
                max_tokens=self.max_tokens,
            )
        except GenesisError as exc:
            self.last_error = exc.reason
            return None
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            # A typed degradation is expected; anything else is a bug in the
            # backend or its SDK. Both cost the same thing here -- the operator
            # gets no answer -- and the caller's fallback handles both. Letting
            # one through would turn a bad response into silence, which is the
            # failure this whole path exists to prevent. Matches Planner.plan.
            return None
        if completion is None or not getattr(completion, "text", ""):
            return None
        return Answer(completion.text, f"llm:{getattr(completion, 'model', 'unknown')}")
