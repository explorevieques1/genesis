# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""The tool-use loop, and the two things that stop it.

An agentic loop on the voice path is the one place in Genesis where a model
decides how much work to do. Biological Design names *"a loop with no circuit
breaker"* as a way agent systems fail, so the turn cap and the wall-clock
deadline are tested as behaviour rather than trusted as parameters.
"""

from __future__ import annotations

import time

import pytest

from genesis.errors import DegradedError, FatalError
from genesis.llm.anthropic_backend import AnthropicBackend, ToolCall


class Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


def text(s):
    return Block("text", text=s)


def tool_use(id_, name, input_):
    return Block("tool_use", id=id_, name=name, input=input_)


class Reply:
    def __init__(self, content, stop_reason="end_turn", model="claude-opus-5"):
        self.content = content
        self.stop_reason = stop_reason
        self.model = model
        self.stop_details = None


class FakeMessages:
    def __init__(self, replies):
        self._replies = list(replies)
        self.requests: list[dict] = []

    def create(self, **kw):
        self.requests.append(kw)
        if not self._replies:
            return Reply([text("done")])
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeClient:
    def __init__(self, replies):
        self.messages = FakeMessages(replies)


def backend(replies, **kw):
    b = AnthropicBackend("claude-opus-5", api_key="k", **kw)
    b._client = FakeClient(replies)  # noqa: SLF001 - the injection point for tests
    return b


TOOLS = [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]


def never_called(call):  # noqa: ARG001
    raise AssertionError("no tool should have run")


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_a_plain_answer_costs_one_turn_and_runs_no_tools() -> None:
    b = backend([Reply([text("NVDA is up 2%.")])])
    out = b.converse("how's nvda", tools=TOOLS, execute=never_called)
    assert out.text == "NVDA is up 2%."
    assert out.turns == 1
    assert out.invocations == ()
    assert out.truncated == ""


def test_a_tool_call_is_executed_and_the_answer_uses_it() -> None:
    b = backend(
        [
            Reply([tool_use("u1", "quote", {"symbol": "NVDA"})], stop_reason="tool_use"),
            Reply([text("NVDA is 121.")]),
        ]
    )
    seen = []

    def execute(call: ToolCall):
        seen.append((call.name, call.arguments))
        return "121.00", False

    out = b.converse("quote nvda", tools=TOOLS, execute=execute)
    assert out.text == "NVDA is 121."
    assert seen == [("quote", {"symbol": "NVDA"})]
    assert out.used_tools == ("quote",)
    assert out.turns == 2


def test_parallel_calls_return_in_a_single_user_message() -> None:
    """Splitting results across messages silently trains the model to stop
    calling tools in parallel -- the documented failure mode."""
    b = backend(
        [
            Reply(
                [tool_use("u1", "a", {}), tool_use("u2", "b", {})],
                stop_reason="tool_use",
            ),
            Reply([text("both done")]),
        ]
    )
    out = b.converse("do both", tools=TOOLS, execute=lambda c: ("ok", False))
    assert len(out.invocations) == 2

    results = _tool_result_messages(b)
    assert len(results) == 1
    assert len(results[0]["content"]) == 2


# --------------------------------------------------------------------------
# Circuit breakers
# --------------------------------------------------------------------------


def test_the_turn_cap_stops_a_model_that_keeps_calling_tools() -> None:
    forever = [
        Reply([tool_use(f"u{i}", "t", {})], stop_reason="tool_use") for i in range(50)
    ]
    b = backend(forever)
    out = b.converse(
        "loop", tools=TOOLS, execute=lambda c: ("ok", False), max_turns=3
    )
    assert out.turns == 3
    assert "3-turn limit" in out.truncated


def test_the_deadline_stops_a_loop_that_is_merely_slow() -> None:
    """The turn cap does not help when each turn is slow; the voice budget is
    wall-clock, so the deadline has to be too."""
    forever = [
        Reply([tool_use(f"u{i}", "t", {})], stop_reason="tool_use") for i in range(50)
    ]
    b = backend(forever)

    def slow(call):  # noqa: ARG001
        time.sleep(0.05)
        return "ok", False

    out = b.converse(
        "loop", tools=TOOLS, execute=slow, max_turns=50, deadline_sec=0.15
    )
    assert out.turns < 50
    assert "budget" in out.truncated


def test_a_truncated_answer_is_marked_degraded() -> None:
    """Error Handling And Degradation forbids presenting a degraded answer as
    if it were normal, and half the tool calls the model wanted is degraded."""
    b = backend(
        [Reply([tool_use("u", "t", {})], stop_reason="tool_use")] * 5
    )
    out = b.converse("x", tools=TOOLS, execute=lambda c: ("ok", False), max_turns=1)
    assert out.as_completion().degraded


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


def test_a_raising_tool_becomes_an_error_result_not_a_dead_loop() -> None:
    b = backend(
        [
            Reply([tool_use("u1", "t", {})], stop_reason="tool_use"),
            Reply([text("I could not reach that.")]),
        ]
    )

    def boom(call):  # noqa: ARG001
        raise RuntimeError("socket exploded")

    out = b.converse("x", tools=TOOLS, execute=boom)
    assert out.text == "I could not reach that."
    assert out.failed and "socket exploded" in out.failed[0].detail

    result = _only_tool_result(b)
    assert result["is_error"] is True
    assert result["tool_use_id"] == "u1"


def test_a_failed_tool_marks_the_answer_degraded() -> None:
    b = backend(
        [
            Reply([tool_use("u1", "t", {})], stop_reason="tool_use"),
            Reply([text("partial")]),
        ]
    )
    out = b.converse("x", tools=TOOLS, execute=lambda c: ("nope", True))
    assert out.as_completion().degraded


def test_pause_turn_is_resumed_rather_than_treated_as_an_answer() -> None:
    b = backend(
        [
            Reply([text("")], stop_reason="pause_turn"),
            Reply([text("finished")]),
        ]
    )
    out = b.converse("x", tools=TOOLS, execute=never_called)
    assert out.text == "finished"
    assert out.turns == 2


def test_a_refusal_is_a_degradation_not_an_answer() -> None:
    b = backend([Reply([text("")], stop_reason="refusal")])
    with pytest.raises(DegradedError, match="declined"):
        b.converse("x", tools=TOOLS, execute=never_called)


def test_a_bad_key_is_fatal_because_retrying_burns_the_voice_budget() -> None:
    import anthropic

    err = anthropic.AuthenticationError(
        "bad key", response=_resp(401), body=None
    )
    b = backend([err])
    with pytest.raises(FatalError):
        b.converse("x", tools=TOOLS, execute=never_called)


def test_a_rate_limit_is_degraded_and_therefore_retryable_upstream() -> None:
    import anthropic

    err = anthropic.RateLimitError("slow down", response=_resp(429), body=None)
    b = backend([err])
    with pytest.raises(DegradedError):
        b.converse("x", tools=TOOLS, execute=never_called)


def _tool_result_messages(b) -> list[dict]:
    """Every user message carrying tool results.

    Read off the conversation the loop built rather than off a captured
    request: the loop passes its live ``messages`` list to the SDK, so a
    captured request aliases it and shows the state at the *end* of the run.
    """
    out = b._client.messages.requests[-1]["messages"]  # noqa: SLF001
    return [
        m
        for m in out
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and all(isinstance(c, dict) for c in m["content"])
    ]


def _only_tool_result(b) -> dict:
    messages = _tool_result_messages(b)
    assert len(messages) == 1
    assert len(messages[0]["content"]) == 1
    return messages[0]["content"][0]


def _resp(status: int):
    import httpx2 as httpx

    return httpx.Response(status, request=httpx.Request("POST", "https://x"))


# --------------------------------------------------------------------------
# Request shape
# --------------------------------------------------------------------------


def test_no_sampling_parameters_are_sent() -> None:
    """temperature/top_p/top_k were removed on the 4.6+ family and are a 400."""
    b = backend([Reply([text("ok")])])
    b.converse("x", tools=TOOLS, execute=never_called)
    sent = b._client.messages.requests[0]  # noqa: SLF001
    assert "temperature" not in sent
    assert "top_p" not in sent
    assert "budget_tokens" not in sent


def test_effort_rides_in_output_config() -> None:
    b = backend([Reply([text("ok")])])
    b.converse("x", tools=TOOLS, execute=never_called, effort="high")
    assert b._client.messages.requests[0]["output_config"] == {  # noqa: SLF001
        "effort": "high"
    }
