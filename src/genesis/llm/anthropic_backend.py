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

import os
import time
from typing import Literal

from genesis.errors import DegradedError, FatalError
from genesis.llm.backend import Completion

__all__ = ["AnthropicBackend", "Effort"]

Effort = Literal["low", "medium", "high", "xhigh", "max"]


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
            raise FatalError(f"Anthropic rejected the request: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise DegradedError(f"Anthropic rate limited: {exc}") from exc
        except anthropic.APIError as exc:
            raise DegradedError(f"Anthropic unavailable: {exc}") from exc

        if response.stop_reason == "refusal":
            # HTTP 200 with a refusal. Never present this as an answer.
            detail = getattr(response.stop_details, "category", None)
            raise DegradedError(f"Claude declined the request ({detail})")

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return Completion(
            text=text,
            model=response.model,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
