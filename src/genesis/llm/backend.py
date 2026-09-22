# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""Model backends, one per tier.

LLM Model Tiers routes by cost. The shipped assignment (Open Questions §4, no
GPU on the build machine) is: **nano is not a model at all** -- intent
classification is deterministic code -- while small, large and vision are
hosted, and only embeddings run local. The Ollama backend below stays for
installs that do have a GPU. The interface is deliberately thin -- one blocking
:meth:`complete`, one streaming variant -- because the orchestrator's use of a
model is a classification or a short summary, not a conversation.

**Failure is typed and never silent.** A model that is down raises
:class:`~genesis.errors.DegradedError`, which the tier router turns into a
fallback rather than an exception. LLM Model Tiers' degradation table is
explicit that the system stays safe with no LLM at all -- so nothing here may
be on a path that a deterministic component depends on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from genesis.errors import DegradedError

__all__ = ["Backend", "OllamaBackend", "Completion"]

_OLLAMA_ROOT = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    latency_ms: float
    #: True when the answer came from a fallback rather than the requested
    #: tier. Callers that speak the result must label it -- Error Handling And
    #: Degradation forbids presenting degraded output as if it were normal.
    degraded: bool = False
    #: Tokens billed, as the provider counted them. Never estimated here: a
    #: budget enforced against our own guess is a budget that disagrees with
    #: the invoice, and the provider is the only authority on the number. Zero
    #: means the provider did not say, not that the call was free.
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class Backend(Protocol):
    model: str

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 256, temperature: float = 0.0) -> Completion: ...


def ollama_status(model: str, *, root: str = _OLLAMA_ROOT, timeout: float = 0.8) -> str | None:
    """``None`` when the model is ready to answer, else why it is not.

    A local, free, instant question -- which is what makes it safe to ask on a
    settings render, where probing a *hosted* tier would bill the operator for
    opening a panel.

    It exists because a local backend is the one tier that can look perfectly
    configured and be completely dead: no key to be missing, no vendor to be
    down, and `ollama pull` never run. That is not hypothetical -- a tier
    pointed at `qwen2.5:3b` on a machine with no models pulled answered every
    planning request with a 404 for days, and nothing on the surface said so.
    """
    import httpx

    try:
        response = httpx.get(f"{root.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
        installed = [m.get("name", "") for m in response.json().get("models", [])]
    except Exception:  # noqa: BLE001 - a probe that raises tells nobody anything
        return "ollama is not running"
    if not installed:
        return f"ollama has no models pulled — run `ollama pull {model}`"
    # Ollama reports `qwen2.5:3b`; a config may say `qwen2.5` and mean `:latest`.
    if model in installed or f"{model}:latest" in installed:
        return None
    return f"`{model}` is not pulled — run `ollama pull {model}`"


class OllamaBackend:
    """Local inference via Ollama's HTTP API.

    Keeps one client alive: LLM Model Tiers requires the small chain stay warm
    because *"cold-start latency destroys the Voice Stack budget"*, and a fresh
    connection per call is a self-inflicted cold start.
    """

    def __init__(self, model: str, *, root: str = _OLLAMA_ROOT, timeout: float = 30.0) -> None:
        self.model = model
        self._root = root.rstrip("/")
        self._timeout = timeout
        self._client = None

    def _http(self):
        import httpx

        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def warm(self) -> None:
        """Load the model into memory before it is on a latency path."""
        try:
            self._http().post(
                f"{self._root}/api/generate",
                json={"model": self.model, "prompt": "ok", "stream": False, "options": {"num_predict": 1}},
                timeout=120.0,
            )
        except Exception:  # noqa: BLE001 - warming is best-effort
            pass

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ) -> Completion:
        import time

        body: dict[str, object] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if system:
            body["system"] = system
        start = time.monotonic()
        try:
            response = self._http().post(f"{self._root}/api/generate", json=body)
        except Exception as exc:  # noqa: BLE001
            raise DegradedError(f"Ollama unreachable at {self._root}: {exc}") from exc
        if response.status_code != 200:
            raise DegradedError(f"Ollama returned {response.status_code}: {response.text[:200]}")
        latency = (time.monotonic() - start) * 1000
        body = response.json()
        # Ollama's names for the same two numbers. Counted even though nothing
        # is billed: the usage panel's job is to show where the work went, and
        # "local tiers are free" is only visible if local tiers are measured.
        return Completion(
            text=body.get("response", "").strip(),
            model=self.model,
            latency_ms=latency,
            input_tokens=int(body.get("prompt_eval_count") or 0),
            output_tokens=int(body.get("eval_count") or 0),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
