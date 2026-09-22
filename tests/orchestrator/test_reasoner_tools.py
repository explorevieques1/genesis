# Spec: Genesis Markdown/10-Architecture/Orchestrator.md
"""The reasoner must not claim tools the backend cannot call.

`converse` -- the tool-use loop -- exists on the Anthropic backend and on no
other. Every hosted free tier reaches Genesis through `OpenAICompatBackend`,
which has no such method, so its answers are written without a single tool
call. What the prompt says about tools has to match that, or the model spends
its turn apologising for not looking something up.
"""

from __future__ import annotations

from typing import Any

from genesis.llm.backend import Completion
from genesis.orchestrator.reasoner import NO_TOOLS_RULE, TOOL_RULE, Reasoner


class Recorder:
    """A backend with no `converse` -- the shape of every non-Anthropic tier."""

    model = "stub"

    def __init__(self) -> None:
        self.system: str | None = None

    def complete(self, prompt: str, *, system: str | None = None, **_: Any) -> Completion:
        self.system = system
        return Completion(text="Apple was founded on April 1, 1976.", model=self.model,
                          latency_ms=1.0)


class Bridge:
    """A router that offers a fat tool surface, as the real one does."""

    @staticmethod
    def tools_for_utterance(_text: str) -> list[dict[str, Any]]:
        return [{"name": "market.quote"}, {"name": "company.profile"}]

    @staticmethod
    def execute(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("no tool should actually run in this test")


def test_a_backend_without_converse_is_told_it_has_no_tools() -> None:
    backend = Recorder()
    answer = Reasoner(backend, bridge=Bridge()).answer("when was apple founded")

    # The tools were selected; they simply cannot be called from here.
    assert TOOL_RULE not in (backend.system or "")
    assert NO_TOOLS_RULE in (backend.system or "")
    # Which is what lets the model answer at all. Told it had tools, Gemini
    # replied "I do not have access to company history tools" -- to a question
    # about a founding date.
    assert answer is not None and "1976" in answer.text


def test_a_backend_with_converse_still_takes_the_tool_path() -> None:
    """The fix must not cost the Anthropic path its tools."""
    seen: list[str] = []

    class Talker(Recorder):
        def converse(self, *_args: Any, **_kwargs: Any):
            seen.append("tool loop")

            class Turns:
                text = "NVDA last traded at 190.00."
                used_tools = ("market.quote",)
                model = "stub"
                truncated = False

            return Turns()

    Reasoner(Talker(), bridge=Bridge()).answer("what is NVDA trading at")
    assert seen == ["tool loop"]


def test_the_failure_reason_reaches_the_trader() -> None:
    """A dead chat and a spent quota must not read the same.

    `UNREACHED` alone is the sentence for a missing key, an exhausted free
    tier and a vendor having a bad minute — three problems with three
    different fixes, and no way to tell which one you have.
    """
    from genesis.errors import DegradedError
    from genesis.orchestrator.answer import UNREACHED, Ladder

    class Broke:
        model = "stub"

        def complete(self, *_a: Any, **_k: Any):
            raise DegradedError("gemini rate limited (free tier quota)")

    reasoner = Reasoner(Broke())
    rung = Ladder(reasoner=reasoner).answer("when was apple founded")

    assert rung.path == "unhandled"
    assert UNREACHED in rung.answer.text
    assert "free tier quota" in rung.answer.text
    assert "free tier quota" in rung.fields["reason"]
