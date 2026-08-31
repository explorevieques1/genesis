# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""Model backends, one per tier.

LLM Model Tiers routes by cost: nano and small run locally on Ollama, large and
vision are hosted. The interface is deliberately thin -- one blocking
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


class Backend(Protocol):
    model: str

    def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 256, temperature: float = 0.0) -> Completion: ...


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
        return Completion(
            text=response.json().get("response", "").strip(),
            model=self.model,
            latency_ms=latency,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
