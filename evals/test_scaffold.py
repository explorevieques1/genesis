# Spec: Genesis Markdown/00-Meta/Conventions.md
"""Self-checks for the eval harness itself.

These are *not* LLM evals — there are none yet, and there should be none until
Phase 2 gives them something to evaluate. They exist so that `pytest evals`
proves the scaffold works rather than passing because it collected nothing.
"""

from __future__ import annotations

import pytest
from helpers import EvalCase, EvalResult, assert_meets_criteria


def test_deterministic_gates_pass_a_good_response() -> None:
    case = EvalCase(
        name="market-open-time",
        utterance="Genesis, what time does the market open?",
        expects="states the US equities cash open",
        must_mention=("9:30",),
        expected_agent="orchestrator",
        forbidden_tools=("place_approved",),
    )
    assert_meets_criteria(
        EvalResult(case=case, response="The market opens at 9:30 ET.", agent="orchestrator")
    )


def test_failure_message_quotes_the_response() -> None:
    """An eval that fails without showing what was said cannot be debugged."""
    case = EvalCase(
        name="market-open-time",
        utterance="Genesis, what time does the market open?",
        expects="states the US equities cash open",
        must_mention=("9:30",),
    )
    with pytest.raises(AssertionError) as exc:
        assert_meets_criteria(EvalResult(case=case, response="Sometime this morning."))

    message = str(exc.value)
    assert "market-open-time" in message
    assert "Sometime this morning." in message
    assert "9:30" in message


def test_forbidden_tool_is_caught() -> None:
    """Structural, but worth an eval too: no path may reach an order tool."""
    case = EvalCase(
        name="no-order-path",
        utterance="Genesis, what's NVDA doing?",
        expects="answers without touching the order path",
        forbidden_tools=("place_approved", "propose_order"),
    )
    with pytest.raises(AssertionError, match="forbidden tool"):
        assert_meets_criteria(
            EvalResult(case=case, response="Up 2%.", tools_called=("place_approved",))
        )


def test_tool_capture_records_calls(tools) -> None:
    run = tools.runner({"quote": {"last": "121.00"}})
    assert run("quote", symbol="NVDA") == {"last": "121.00"}
    assert tools.names == ("quote",)
    assert tools.args_for("quote") == {"symbol": "NVDA"}


def test_config_fixture_is_the_shipped_defaults(config) -> None:
    assert config.approval.mode == "confirm"
