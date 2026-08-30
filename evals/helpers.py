# Spec: Genesis Markdown/00-Meta/Conventions.md
"""Shared machinery for Genesis evals.

Unit tests assert exact answers. Evals score a *distribution* of behaviour from a
model that is allowed to phrase things differently every run, so they need
different tools: a case/result pair, graded assertions, and a judge model that
may simply not be there.

Nothing here calls an LLM at import time. A judge that is unreachable produces a
**skip**, never a pass -- an eval suite that silently reports green because no
model answered is worse than no eval suite.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = [
    "EvalCase",
    "EvalResult",
    "JudgeVerdict",
    "ToolCallCapture",
    "JUDGE_BASE_URL",
    "JUDGE_MODEL",
    "assert_meets_criteria",
    "call_judge",
    "is_judge_available",
    "mentions_all",
    "mentions_any",
]

# The judge is configured by environment so a run can be pointed at a different
# model without editing code. Behaviour lives in config; this is test-harness
# wiring, not system behaviour.
JUDGE_BASE_URL = os.environ.get("GENESIS_EVAL_JUDGE_BASE_URL", "http://localhost:11434")
JUDGE_MODEL = os.environ.get("GENESIS_EVAL_JUDGE_MODEL", "")
JUDGE_TIMEOUT_SEC = float(os.environ.get("GENESIS_EVAL_JUDGE_TIMEOUT", "120"))


# --------------------------------------------------------------------------
# Cases and results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalCase:
    """One scenario put to the system, with what a good answer must contain.

    ``must_mention`` / ``must_not_mention`` are cheap deterministic gates. Reach
    for ``judge_criteria`` only when the quality in question genuinely cannot be
    expressed as a keyword -- a judge call is slow, costs tokens, and is itself
    non-deterministic.
    """

    name: str
    utterance: str
    expects: str
    must_mention: tuple[str, ...] = ()
    must_not_mention: tuple[str, ...] = ()
    expected_agent: str | None = None
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    judge_criteria: str | None = None


@dataclass
class EvalResult:
    """What the system actually did with an :class:`EvalCase`."""

    case: EvalCase
    response: str = ""
    agent: str | None = None
    tools_called: tuple[str, ...] = ()
    trace_id: str | None = None
    degraded: bool = False
    wall_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeVerdict:
    passed: bool
    reasoning: str
    score: float | None = None


# --------------------------------------------------------------------------
# Deterministic assertions -- prefer these
# --------------------------------------------------------------------------


def mentions_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(k.lower() in lowered for k in keywords)


def mentions_all(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return all(k.lower() in lowered for k in keywords)


def assert_meets_criteria(result: EvalResult) -> None:
    """Check a result against its case's deterministic expectations.

    Failure messages name the case and quote the response: an eval that fails
    without showing what the model said cannot be debugged.
    """
    case = result.case
    context = f"[{case.name}] expected: {case.expects}\n  got: {result.response!r}"

    for keyword in case.must_mention:
        assert keyword.lower() in result.response.lower(), (
            f"{context}\n  missing required mention: {keyword!r}"
        )
    for keyword in case.must_not_mention:
        assert keyword.lower() not in result.response.lower(), (
            f"{context}\n  contains forbidden mention: {keyword!r}"
        )
    if case.expected_agent is not None:
        assert result.agent == case.expected_agent, (
            f"{context}\n  routed to {result.agent!r}, expected {case.expected_agent!r}"
        )
    for tool in case.expected_tools:
        assert tool in result.tools_called, (
            f"{context}\n  did not call {tool!r}; called {result.tools_called}"
        )
    for tool in case.forbidden_tools:
        assert tool not in result.tools_called, (
            f"{context}\n  called forbidden tool {tool!r}"
        )


# --------------------------------------------------------------------------
# Tool capture
# --------------------------------------------------------------------------


@dataclass
class ToolCallCapture:
    """Records the tool calls an agent makes, for routing and selection evals."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def record(self, name: str, args: dict[str, Any]) -> None:
        self.calls.append((name, dict(args)))

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.calls)

    def args_for(self, name: str) -> dict[str, Any] | None:
        for called, args in self.calls:
            if called == name:
                return args
        return None

    def runner(self, responses: dict[str, Any]) -> Callable[..., Any]:
        """A stand-in tool runner that captures calls and returns canned results."""

        def run(name: str, **args: Any) -> Any:
            self.record(name, args)
            return responses.get(name, {"ok": True})

        return run


# --------------------------------------------------------------------------
# Judge -- optional, and honest about being absent
# --------------------------------------------------------------------------


def is_judge_available() -> bool:
    """True only if a judge model is configured *and* actually reachable."""
    if not JUDGE_MODEL:
        return False
    try:
        with urllib.request.urlopen(f"{JUDGE_BASE_URL}/api/tags", timeout=3) as fh:
            tags = json.load(fh)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return False
    available = {m.get("name", "") for m in tags.get("models", [])}
    return any(name.split(":")[0] == JUDGE_MODEL.split(":")[0] for name in available)


def call_judge(system_prompt: str, user_prompt: str) -> str | None:
    """Ask the judge model. Returns ``None`` if it could not be reached.

    Callers must treat ``None`` as *inconclusive* and skip -- never as a pass.
    """
    payload = json.dumps(
        {
            "model": JUDGE_MODEL,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
    ).encode()
    request = urllib.request.Request(
        f"{JUDGE_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=JUDGE_TIMEOUT_SEC) as fh:
            body = json.load(fh)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    return body.get("message", {}).get("content")
