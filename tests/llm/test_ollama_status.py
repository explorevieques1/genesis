# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""The one tier that can look configured and be dead.

A hosted tier without a key says so on the settings panel. A local tier has no
key to be missing and no vendor to be down, so `ollama pull` never having been
run is invisible -- and a planner pointed at an unpulled model 404s every call
while the panel shows a green local chip.
"""

from __future__ import annotations

import pytest

from genesis.llm.backend import ollama_status


class Response:
    def __init__(self, models: list[str]) -> None:
        self._models = models

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"models": [{"name": name} for name in self._models]}


def test_a_pulled_model_has_no_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: Response(["qwen2.5:3b"]))
    assert ollama_status("qwen2.5:3b") is None
    # A config that omits the tag means `:latest`, which is what Ollama lists.
    monkeypatch.setattr("httpx.get", lambda *a, **k: Response(["qwen2.5:latest"]))
    assert ollama_status("qwen2.5") is None


def test_an_empty_ollama_says_what_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: Response([]))
    assert "ollama pull qwen2.5:3b" in (ollama_status("qwen2.5:3b") or "")


def test_a_missing_model_names_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("httpx.get", lambda *a, **k: Response(["llama3:8b"]))
    blocker = ollama_status("qwen2.5:3b") or ""
    assert "qwen2.5:3b" in blocker and "pull" in blocker


def test_a_dead_server_is_a_blocker_not_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr("httpx.get", boom)
    assert ollama_status("qwen2.5:3b") == "ollama is not running"
