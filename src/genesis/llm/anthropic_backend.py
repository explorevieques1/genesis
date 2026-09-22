# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""The hosted tiers -- Claude via the official Anthropic SDK.

LLM Model Tiers fixes the assignment: ``large`` and ``vision`` are
``claude-opus-5``, ``small`` is ``claude-haiku-4-5``, and nothing generative
runs local because the build machine has no GPU ([[Open Questions]] §4). This
module is those tiers.

Three API details that are easy to get wrong on Opus 5, each of which is a 400
rather than a warning:

* **No sampling parameters.** ``temperature``, ``top_p`` and ``top_k`` were
  removed on the 4.6+ family. The :class:`~genesis.llm.backend.Backend`
  protocol still carries ``temperature`` because the local backends honour it,
  so this class accepts and *drops* it rather than forwarding it into a
  rejection.
* **No ``budget_tokens``.** Thinking is adaptive; depth is controlled by
  ``output_config.effort``, not by a token ceiling.
* **Thinking is on by default.** Omitting the parameter runs adaptive thinking
  -- unlike Opus 4.8/4.7, where omitting it meant no thinking at all.

**Nothing safety-critical may call this.** LLM Model Tiers' `tier: none` row
covers the risk engine, the kill switch, sizing and P&L, and the whole point of
the tier table is that a language model never appears in those paths. This
module is for the orchestrator's judgement calls and for the research family.
"""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from genesis.errors import DegradedError, FatalError
from genesis.llm.backend import Completion

__all__ = [
    "AnthropicBackend",
    "Effort",
    "ToolCall",
    "ToolInvocation",
    "Turns",
]

Effort = Literal["low", "medium", "high", "xhigh", "max"]


def _usage(response: Any) -> tuple[int, int]:
    """Input and output tokens as the provider counted them, or (0, 0).

    Defensive because ``usage`` is absent on some error-shaped responses and a
    missing field must not turn a good answer into a traceback.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    return int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)



def _bad_request(exc: Exception) -> Exception:
    """Classify a 400 by cause, because they are not all the same failure.

    Anthropic returns 400 both for a request we built wrong and for an account
    the operator has to go fix. Only the first is fatal. Billing and workspace
    scoping are *account state*: the code is correct, retrying will not help
    this second, but the tier is not permanently broken and the orchestrator
    should degrade around it rather than die -- LLM Model Tiers is explicit
    that the system stays safe with no LLM at all.

    The message matters as much as the class. The raw SDK error reads like a
    malformed body, which sends you to read the request builder instead of
    the billing page.
    """
    detail = str(exc)
    if "credit balance is too low" in detail:
        return DegradedError(
            "Anthropic credit balance is too low; hosted tiers are offline. "
            "Add credits at console.anthropic.com -> Plans & Billing."
        )
    if "anthropic-workspace-id" in detail:
        return DegradedError(
            "Anthropic key is not scoped to a workspace and no workspace id is "
            "set; hosted tiers are offline. Set ANTHROPIC_WORKSPACE_ID in "
            "~/.genesis/.env."
        )
    return FatalError(f"Anthropic rejected the request: {exc}")


class AnthropicBackend:
    """A hosted Claude tier.

    ``effort`` defaults to ``low`` for a reason specific to this system: the
    orchestrator's budget is *"wake -> first spoken word in under 1.5 s"*, and
    for voice the cost of thinking longer is paid in silence the operator
    hears. Research agents that are not on the voice path should raise it --
    Idea Synthesizer and Strategy Author want ``high`` or better.
    """

    def __init__(
        self,
        model: str = "claude-opus-5",
        *,
        api_key: str | None = None,
        workspace_id: str | None = None,
        effort: Effort = "low",
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise DegradedError("ANTHROPIC_API_KEY is not set; hosted tiers unavailable")
        self.model = model
        self.effort: Effort = effort
        self.max_tokens = max_tokens
        self._key = key
        # Identity-linked keys must name the workspace they act in; without it
        # every request is a 400 that reads like a malformed body rather than a
        # missing header. Optional because ordinary keys must not send it.
        self._workspace_id = workspace_id or os.environ.get("ANTHROPIC_WORKSPACE_ID")
        self._timeout = timeout
        self._client = None

    def _sdk(self):
        import anthropic

        if self._client is None:
            headers = {}
            if self._workspace_id:
                headers["anthropic-workspace-id"] = self._workspace_id
            self._client = anthropic.Anthropic(
                api_key=self._key,
                timeout=self._timeout,
                default_headers=headers or None,
            )
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,  # noqa: ARG002 - see module docstring
        effort: Effort | None = None,
    ) -> Completion:
        """One request, one response. Raises typed failures, never bare errors."""
        import anthropic

        client = self._sdk()
        start = time.monotonic()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                system=system or anthropic.NOT_GIVEN,
                output_config={"effort": effort or self.effort},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as exc:
            # A bad key will not fix itself on retry, and retrying it burns the
            # voice budget on every utterance. Fatal, not transient.
            raise FatalError(f"Anthropic rejected the API key: {exc}") from exc
        except anthropic.BadRequestError as exc:
            raise _bad_request(exc) from exc
        except anthropic.RateLimitError as exc:
            raise DegradedError(f"Anthropic rate limited: {exc}") from exc
        except anthropic.APIError as exc:
            raise DegradedError(f"Anthropic unavailable: {exc}") from exc

        if response.stop_reason == "refusal":
            # HTTP 200 with a refusal. Never present this as an answer.
            detail = getattr(response.stop_details, "category", None)
            raise DegradedError(f"Claude declined the request ({detail})")

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        sent, received = _usage(response)
        return Completion(
            text=text,
            model=response.model,
            latency_ms=(time.monotonic() - start) * 1000,
            input_tokens=sent,
            output_tokens=received,
        )

    # ------------------------------------------------------------------
    # Vision
    # ------------------------------------------------------------------

    def see(
        self,
        prompt: str,
        images: Sequence[bytes],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        effort: Effort | None = None,
        media_type: str = "image/png",
    ) -> Completion:
        """One request carrying images. The ``vision`` tier's entry point.

        A separate method rather than an ``images=`` argument on
        :meth:`complete`, because LLM Model Tiers treats vision as its own tier
        with its own cost and its own routing -- and Agent — Pattern
        Recognition's cost control (*"render once, ask once"*) only works if
        every vision call is visibly a vision call at the call site.

        Images are sent inline as base64. They are charts this system rendered
        moments ago, so there is no fetch, no URL and nothing for the SSRF guard
        to have an opinion about.
        """
        import anthropic

        if not images:
            raise DegradedError("see() needs at least one image")

        client = self._sdk()
        start = time.monotonic()
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.b64encode(png).decode(),
                },
            }
            for png in images
        ]
        content.append({"type": "text", "text": prompt})

        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                system=system or anthropic.NOT_GIVEN,
                output_config={"effort": effort or self.effort},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError as exc:
            raise FatalError(f"Anthropic rejected the API key: {exc}") from exc
        except anthropic.BadRequestError as exc:
            raise _bad_request(exc) from exc
        except anthropic.RateLimitError as exc:
            raise DegradedError(f"Anthropic rate limited: {exc}") from exc
        except anthropic.APIError as exc:
            raise DegradedError(f"Anthropic unavailable: {exc}") from exc

        if response.stop_reason == "refusal":
            raise DegradedError("Claude declined to read the chart")

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        sent, received = _usage(response)
        return Completion(
            text=text, model=response.model,
            latency_ms=(time.monotonic() - start) * 1000,
            input_tokens=sent,
            output_tokens=received,
        )

    # ------------------------------------------------------------------
    # Tool use -- the agentic loop
    # ------------------------------------------------------------------

    def converse(
        self,
        prompt: str,
        *,
        system: str | None = None,
        tools: Sequence[dict[str, Any]],
        execute: Callable[[ToolCall], tuple[str, bool]],
        max_turns: int = 6,
        deadline_sec: float = 25.0,
        max_tokens: int | None = None,
        effort: Effort | None = None,
        history: Sequence[dict[str, Any]] | None = None,
    ) -> Turns:
        """Run a tool-use loop until Claude stops calling tools.

        A hand-written loop rather than the SDK's ``tool_runner`` for three
        reasons specific to Genesis, in descending order of importance:

        1. **The loop needs a circuit breaker.** ``max_turns`` and
           ``deadline_sec`` are hard stops, checked before every request.
           Biological Design names *"a loop with no circuit breaker"* as one of
           the four ways agent systems actually fail, and this loop sits on the
           voice path where an unbounded one is heard as Genesis going silent.
        2. **Tools are chosen per turn, from a live catalogue.** ``tool_runner``
           builds schemas from Python signatures at import time; ours come from
           MCP :class:`~genesis.mcp.spec.ToolSpec` objects the router selects
           for *this* utterance. The set is different every turn by design.
        3. **Execution is not ours to do.** ``execute`` routes through the
           gateway, which is where the allow-list, the SSRF guard, the cache
           and the rate limiter live. The model never reaches a server, and
           nothing here may become a second path that does.

        Every tool result is returned, including failures -- a failed call
        comes back with ``is_error`` set rather than being dropped, because a
        model that receives no result for a call it made will usually invent
        one. Parallel calls come back in a single user message, which is the
        documented shape; splitting them across messages teaches the model to
        stop calling tools in parallel.
        """
        import anthropic

        client = self._sdk()
        started = time.monotonic()
        messages: list[dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": prompt})

        invocations: list[ToolInvocation] = []
        turns = 0
        truncated = ""
        response = None
        sent = received = 0

        while True:
            if turns >= max_turns:
                truncated = f"hit the {max_turns}-turn limit"
                break
            elapsed = time.monotonic() - started
            if elapsed > deadline_sec:
                truncated = f"ran past the {deadline_sec:.0f}s budget"
                break

            turns += 1
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.max_tokens,
                    system=system or anthropic.NOT_GIVEN,
                    output_config={"effort": effort or self.effort},
                    tools=list(tools) or anthropic.NOT_GIVEN,
                    messages=messages,
                )
            except anthropic.AuthenticationError as exc:
                raise FatalError(f"Anthropic rejected the API key: {exc}") from exc
            except anthropic.BadRequestError as exc:
                raise _bad_request(exc) from exc
            except anthropic.RateLimitError as exc:
                raise DegradedError(f"Anthropic rate limited: {exc}") from exc
            except anthropic.APIError as exc:
                raise DegradedError(f"Anthropic unavailable: {exc}") from exc

            # Bill every turn, not just the last. The whole conversation is
            # re-sent each round trip, so a five-turn loop costs far more than
            # its final response reports.
            turn_sent, turn_received = _usage(response)
            sent += turn_sent
            received += turn_received

            if response.stop_reason == "refusal":
                detail = getattr(response.stop_details, "category", None)
                raise DegradedError(f"Claude declined the request ({detail})")

            messages.append({"role": "assistant", "content": response.content})

            # A server-side tool hit its own iteration limit. Nothing for us to
            # execute -- re-send so the model can carry on. Costs a turn from
            # the budget deliberately: a paused turn that never resolves would
            # otherwise loop until the deadline.
            if response.stop_reason == "pause_turn":
                continue

            calls = [b for b in response.content if b.type == "tool_use"]
            if not calls:
                break

            results: list[dict[str, Any]] = []
            for block in calls:
                call = ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                t0 = time.monotonic()
                try:
                    content, is_error = execute(call)
                except Exception as exc:  # noqa: BLE001 - a tool bug is a tool result
                    # The loop is the wrong place to die. Handing the failure
                    # back as a result lets the model try another route, which
                    # is what a person would do, and keeps one broken server
                    # from taking down the answer.
                    content, is_error = f"{type(exc).__name__}: {exc}", True
                invocations.append(
                    ToolInvocation(
                        name=call.name,
                        arguments=call.arguments,
                        ok=not is_error,
                        detail=content[:200],
                        latency_ms=(time.monotonic() - t0) * 1000,
                    )
                )
                result: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": content,
                }
                if is_error:
                    result["is_error"] = True
                results.append(result)

            # One user message carrying every result, per the API contract.
            messages.append({"role": "user", "content": results})

        text = ""
        if response is not None:
            text = "".join(b.text for b in response.content if b.type == "text").strip()

        return Turns(
            text=text,
            model=getattr(response, "model", self.model) if response else self.model,
            latency_ms=(time.monotonic() - started) * 1000,
            turns=turns,
            invocations=tuple(invocations),
            truncated=truncated,
            input_tokens=sent,
            output_tokens=received,
            messages=tuple(messages),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# --------------------------------------------------------------------------
# Tool-use value types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """One tool the model asked for, before anything has been run."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolInvocation:
    """One tool that was actually run. The audit record, not the payload.

    ``detail`` is truncated on purpose: this ends up in the Episodic Log and a
    full tool payload there would make the trace unreadable and duplicate what
    the memory fabric already holds.
    """

    name: str
    arguments: dict[str, Any]
    ok: bool
    detail: str = ""
    latency_ms: float = 0.0


@dataclass(frozen=True)
class Turns:
    """The outcome of a tool-use loop.

    ``truncated`` is empty on a clean finish and otherwise says which stop
    fired. It is never silently dropped: an answer assembled from half the
    tool calls the model wanted is a *degraded* answer, and Error Handling And
    Degradation forbids presenting one as if it were normal.
    """

    text: str
    model: str
    latency_ms: float = 0.0
    turns: int = 0
    invocations: tuple[ToolInvocation, ...] = ()
    truncated: str = ""
    #: Summed across every turn of the loop -- a tool loop bills for each
    #: round trip, so the last response's usage is not the cost of the answer.
    input_tokens: int = 0
    output_tokens: int = 0
    messages: tuple[dict[str, Any], ...] = field(default=(), repr=False)

    @property
    def used_tools(self) -> tuple[str, ...]:
        return tuple(i.name for i in self.invocations)

    @property
    def failed(self) -> tuple[ToolInvocation, ...]:
        return tuple(i for i in self.invocations if not i.ok)

    def as_completion(self) -> Completion:
        """The plain shape, for callers that only want the words."""
        return Completion(
            text=self.text,
            model=self.model,
            latency_ms=self.latency_ms,
            degraded=bool(self.truncated) or bool(self.failed),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )
