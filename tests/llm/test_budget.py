# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md §Cost control
"""The metabolic ceiling: what happens when the day's tokens are spent."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from genesis.errors import DegradedError
from genesis.llm.backend import Completion
from genesis.llm.usage import Budget, MeteredBackend, UsageLog


class FakeBackend:
    model = "claude-haiku-4-5"

    def __init__(self, tokens: int = 400) -> None:
        self.tokens = tokens
        self.calls = 0

    def complete(self, prompt: str, **kwargs: object) -> Completion:
        self.calls += 1
        return Completion(
            text="ok",
            input_tokens=self.tokens // 2,
            output_tokens=self.tokens // 2,
            latency_ms=1.0,
            model=self.model,
        )


def _metered(tmp_path: Path, *, daily: int) -> tuple[MeteredBackend, FakeBackend, Budget]:
    log = UsageLog(tmp_path / "usage.db")
    b = Budget(log, daily_tokens=daily)
    inner = FakeBackend()
    return MeteredBackend(inner, tier="small", backend="anthropic", log=log, budget=b), inner, b


def test_under_budget_the_call_goes_through(tmp_path: Path) -> None:
    metered, inner, b = _metered(tmp_path, daily=10_000)
    metered.complete("hello")
    assert inner.calls == 1
    assert b.spent == 400


def test_a_spent_budget_refuses_and_says_the_numbers(tmp_path: Path) -> None:
    metered, inner, _ = _metered(tmp_path, daily=1_000)
    for _ in range(3):  # 1200 tokens: past the ceiling
        metered.complete("hello")
    with pytest.raises(DegradedError, match="token budget is spent"):
        metered.complete("hello")
    assert inner.calls == 3, "the refusal happens before the provider is called"


def test_refusal_is_degraded_not_fatal(tmp_path: Path) -> None:
    """Every tier-none path keeps working, so a spent budget is never a halt."""
    _, _, b = _metered(tmp_path, daily=1)
    b.add(10)
    with pytest.raises(DegradedError) as exc:
        b.check("large")
    assert exc.value.failure_class == "degraded"
    assert exc.value.spoken_summary


def test_zero_budget_means_no_ceiling(tmp_path: Path) -> None:
    metered, inner, b = _metered(tmp_path, daily=0)
    for _ in range(5):
        metered.complete("hello")
    assert inner.calls == 5
    assert not b.exhausted


def test_the_ceiling_resets_at_midnight(tmp_path: Path) -> None:
    day = [dt.datetime(2026, 9, 17, 23, 0, tzinfo=dt.UTC)]
    log = UsageLog(tmp_path / "usage.db")
    b = Budget(log, daily_tokens=1_000, clock=lambda: day[0])
    b.add(2_000)
    assert b.exhausted
    day[0] = dt.datetime(2026, 9, 18, 0, 1, tzinfo=dt.UTC)
    assert not b.exhausted, "a new day re-reads the meter, which holds nothing for it"


def test_an_unreadable_meter_does_not_close_the_tier(tmp_path: Path) -> None:
    """Refusing every call because the *counter* broke is the wrong trade."""

    class Broken(UsageLog):
        def tokens_today(self) -> int:
            raise RuntimeError("database is locked")

    b = Budget(Broken(tmp_path / "usage.db"), daily_tokens=1_000)
    assert not b.exhausted
