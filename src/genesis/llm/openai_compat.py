# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""One backend for every provider that speaks the OpenAI chat-completions shape.

Gemini, Groq and OpenRouter all expose that endpoint, so this is one class
instead of three SDKs. The differences between them are a base URL, an
environment variable and a model string -- which is data, and lives in
:data:`PROVIDERS` rather than in code.

**These are development brains, and the distinction is structural.** Google's
free tier trains on the prompts it receives. That is acceptable for a loop that
sends ``"Reply: ok"`` and fake symbols, and disqualifying for one that sends a
live thesis, a position, or a P&L. So :func:`is_dev_only` marks the providers
that must never serve a live-broker run, and the tier factory refuses to build
one when the broker is live. A comment saying "dev only" is not that -- it is
an instruction, and an instruction cannot stop anything.

Failures map onto the same typed pair the rest of the tier layer uses: a
misconfiguration is :class:`FatalError`, an upstream that is merely unwell is
:class:`DegradedError`. Free tiers rate-limit constantly, and a 429 that killed
the daemon would make the free tier useless for the thing it is for.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from genesis.errors import DegradedError, FatalError
from genesis.llm.backend import Completion

__all__ = ["PROVIDERS", "OpenAICompatBackend", "Provider", "is_dev_only"]

#: Retries for a 503, and the pause before each. Small on purpose: a person is
#: waiting, and three seconds of quiet retrying beats an answer that says the
#: model is unreachable when it is merely busy.
RETRIES_503 = 2
BACKOFF_503 = 1.5


@dataclass(frozen=True)
class Provider:
    base_url: str
    env_var: str
    #: True when the provider's free tier trains on submitted prompts, or is
    #: otherwise unfit to see real trading data. Enforced, not documented.
    dev_only: bool
    #: Where to go when the key is missing. A backend that fails without
    #: saying how to fix it costs more time than it saves.
    signup: str
    #: Sent as `reasoning_effort` when set. `"none"` turns *off* a model that
    #: thinks by default -- see the note on the gemini entry below.
    reasoning_effort: str | None = None


PROVIDERS: dict[str, Provider] = {
    "gemini": Provider(
        # Google's OpenAI-compatible surface. The native SDK buys nothing here:
        # this layer sends one prompt and reads one string.
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        env_var="GEMINI_API_KEY",
        dev_only=True,  # free tier is trained on
        signup="https://aistudio.google.com/apikey",
        # Thinking OFF, and this is not a preference.
        #
        # `gemini-flash-latest` reasons before it writes, and the reasoning is
        # spent out of the SAME `max_tokens` budget as the answer -- but is not
        # returned. Measured against the live API at the Reasoner's own default
        # of 300: plain, the reply stops at `finish_reason=length` after 11
        # visible tokens, mid-sentence; with `reasoning_effort: "none"` the
        # same prompt answers completely in 64. At smaller budgets it returns
        # an empty string with a 200.
        #
        # So the default silently truncates every answer on this tier. A tier
        # that wants deliberation can raise this; nothing does yet.
        reasoning_effort="none",
    ),
    "groq": Provider(
        base_url="https://api.groq.com/openai/v1/",
        env_var="GROQ_API_KEY",
        dev_only=True,
        signup="https://console.groq.com/keys",
    ),
    "openrouter": Provider(
        base_url="https://openrouter.ai/api/v1/",
        env_var="OPENROUTER_API_KEY",
        dev_only=True,
        signup="https://openrouter.ai/keys",
    ),
}


def is_dev_only(backend: str) -> bool:
    provider = PROVIDERS.get(backend)
    return provider is not None and provider.dev_only


class OpenAICompatBackend:
    """A hosted tier reached over the OpenAI chat-completions endpoint."""

    def __init__(
        self,
        model: str,
        *,
        provider: str = "gemini",
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        try:
            spec = PROVIDERS[provider]
        except KeyError:
            known = ", ".join(sorted(PROVIDERS))
            raise FatalError(f"unknown LLM backend {provider!r}; known: {known}") from None

        key = api_key or os.environ.get(spec.env_var)
        if not key:
            raise DegradedError(
                f"{spec.env_var} is not set; the {provider} tier is offline. "
                f"Get a key at {spec.signup} and put it in ~/.genesis/.env."
            )
        self.model = model
        self.provider = provider
        self.dev_only = spec.dev_only
        self._spec = spec
        self._key = key
        self._timeout = timeout
        self._client = None
        #: Cleared permanently the first time the model refuses it -- see
        #: `complete`. Per instance, because it is a fact about the *model*
        #: and the provider table only knows about the provider.
        self._reasoning_effort = spec.reasoning_effort

    def _http(self):
        import httpx

        if self._client is None:
            # One client, kept alive. A fresh TLS handshake per call is a
            # self-inflicted cold start on a latency budget.
            self._client = httpx.Client(
                base_url=self._spec.base_url,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=self._timeout,
            )
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ) -> Completion:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort

        start = time.monotonic()
        # A short retry on 503, and only on 503.
        #
        # Google's free tier answers "this model is currently experiencing high
        # demand" constantly -- measured at two failures in three calls on an
        # idle key. It is transient by definition and the endpoint says so, but
        # one attempt turns it into "I can't reach my reasoning model right
        # now", which reads like a broken key. Deterministic, bounded, and
        # nowhere near a safety path: this is a reflex, not a judgement.
        #
        # 429 keeps failing fast: a quota is not busy, it is spent, and
        # retrying spends it faster.
        response = None
        for attempt in range(RETRIES_503 + 1):
            try:
                response = self._http().post("chat/completions", json=payload)
            except Exception as exc:  # noqa: BLE001 - httpx raises a family
                raise DegradedError(f"{self.provider} unreachable: {exc}") from exc
            if response.status_code != 503 or attempt == RETRIES_503:
                break
            time.sleep(BACKOFF_503 * (attempt + 1))

        # `reasoning_effort` is a per-MODEL capability, and the provider table
        # only knows the provider. `gemini-flash-latest` requires it (without
        # it the answer is truncated by its own thinking); `gemini-flash-lite-
        # latest` rejects it with a 400 "invalid argument" and cannot run at
        # all. Rather than maintain a model list that goes stale every time
        # Google ships a name, ask once and remember the answer.
        if (
            response.status_code == 400
            and self._reasoning_effort is not None
            and "reasoning_effort" in payload
        ):
            self._reasoning_effort = None
            payload.pop("reasoning_effort")
            try:
                response = self._http().post("chat/completions", json=payload)
            except Exception as exc:  # noqa: BLE001 - httpx raises a family
                raise DegradedError(f"{self.provider} unreachable: {exc}") from exc

        if response.status_code == 429:
            # The normal state of a free tier, not an emergency.
            raise DegradedError(f"{self.provider} rate limited (free tier quota)")
        if response.status_code in (401, 403):
            raise FatalError(
                f"{self.provider} rejected {self._spec.env_var}: {response.text[:200]}"
            )
        if response.status_code != 200:
            raise DegradedError(
                f"{self.provider} returned {response.status_code}: {response.text[:200]}"
            )

        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise DegradedError(f"{self.provider} returned no choices")
        text = (choices[0].get("message", {}).get("content") or "").strip()
        finish = choices[0].get("finish_reason")

        # An empty answer that arrived with a 200 is the one failure this
        # endpoint returns silently, and Gemini's reasoning models make it
        # routine: `gemini-flash-latest` spends the budget thinking, stops at
        # `length`, and hands back `content: ""` with a healthy status. A
        # caller then gets an empty string that looks like a real answer --
        # Conventions §Errors, fail honestly rather than confabulate, and an
        # empty string IS a confabulation when the model never spoke.
        #
        # Measured: "Reply with the single word: online" at max_tokens=64
        # returns "" with completion_tokens=0; at 512 it returns "online".
        if not text:
            raise DegradedError(
                f"{self.provider} returned an empty completion"
                + (
                    f" (finish_reason={finish}); a reasoning model spends "
                    f"max_tokens on thinking before it writes, so raise the "
                    f"budget -- {max_tokens} was not enough for this prompt"
                    if finish == "length"
                    else f" (finish_reason={finish})"
                )
            )

        usage = body.get("usage") or {}
        return Completion(
            text=text,
            model=body.get("model", self.model),
            latency_ms=(time.monotonic() - start) * 1000,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
