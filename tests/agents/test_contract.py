# Spec: Genesis Markdown/10-Architecture/Agent Contract.md
"""The interface every agent implements, and the rules it cannot break."""

from __future__ import annotations

import pytest

from genesis.agents import (
    SPINAL_AGENTS,
    AgentDeclaration,
    AgentState,
    TaskFailure,
    TaskResult,
)
from genesis.errors import DegradedError, FatalError, TransientError

from helpers import EchoAgent, echo_declaration


class FakeTask:
    def __init__(self, id: str = "t_1", type: str = "echo.run", args=None) -> None:
        self.id = id
        self.type = type
        self.args = args or {}


# --------------------------------------------------------------------------
# Declaration
# --------------------------------------------------------------------------


def test_agent_id_must_be_kebab_case() -> None:
    """Conventions: agent ids are kebab-case."""
    with pytest.raises(ValueError):
        echo_declaration(id="Echo_Agent")


def test_unknown_declaration_key_is_rejected() -> None:
    """A typo'd key would silently widen or narrow a tool allow-list."""
    with pytest.raises(ValueError):
        echo_declaration(tolls=["market-data.ohlcv"])


def test_execution_family_must_be_model_tier_none() -> None:
    """Safety Invariants: a language model never sizes a position."""
    with pytest.raises(ValueError, match="Safety Invariants"):
        echo_declaration(id="order-manager", family="execution", model_tier="large")


def test_execution_family_with_tier_none_is_fine() -> None:
    assert echo_declaration(id="order-manager", family="execution").model_tier == "none"


@pytest.mark.parametrize("agent_id", sorted(SPINAL_AGENTS))
def test_named_reflexes_may_not_acquire_a_model(agent_id: str) -> None:
    """Biological Design §1: a reflex with a model is not a reflex.

    The guard covered the execution family only, so `level-watcher` -- family
    `charting` -- could have been given a model by an edit with nothing
    objecting.
    """
    with pytest.raises(ValueError, match="Safety Invariants"):
        echo_declaration(id=agent_id, family="charting", model_tier="small")


def test_a_thinking_agent_in_a_thinking_family_is_untouched() -> None:
    assert echo_declaration(id="market-analyst", family="research", model_tier="large")


@pytest.mark.parametrize(
    "cadence",
    [
        {"type": "market-open"},               # missing interval
        {"type": "cron"},                      # missing at
        {"type": "event"},                     # missing on
    ],
)
def test_cadence_that_could_never_fire_is_rejected(cadence: dict) -> None:
    """A silent no-op agent is worse than a config error at boot."""
    with pytest.raises(ValueError):
        echo_declaration(cadence=[cadence])


def test_tool_allowlist_is_a_closed_set() -> None:
    decl = echo_declaration(tools=["market-data.ohlcv"])
    assert decl.may_use_tool("market-data.ohlcv")
    assert not decl.may_use_tool("genesis-execution.place_approved")


def test_namespace_write_is_restricted_read_of_shared_is_not() -> None:
    decl = echo_declaration(memory={"read": ["shared"], "write": ["echo"]})
    assert decl.may_write("echo")
    assert not decl.may_write("ledger")
    assert decl.may_read("shared")
    assert not decl.may_read("screener")


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------


def test_agent_starts_down(echo: EchoAgent) -> None:
    assert echo.status().state is AgentState.DOWN
    assert not echo.health().alive


def test_start_and_stop_are_idempotent(echo: EchoAgent) -> None:
    """The supervisor depends on this: a restart racing a shutdown must not raise."""
    echo.start()
    echo.start()
    assert echo.starts == 1
    assert echo.status().state is AgentState.IDLE

    echo.stop()
    echo.stop()
    assert echo.stops == 1
    assert echo.status().state is AgentState.DOWN


def test_start_failure_leaves_the_agent_down(echo: EchoAgent) -> None:
    def boom() -> None:
        raise RuntimeError("no resources")

    echo.on_start = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        echo.start()
    assert echo.status().state is AgentState.DOWN


# --------------------------------------------------------------------------
# run_task
# --------------------------------------------------------------------------


def test_run_task_returns_a_typed_result(echo: EchoAgent) -> None:
    echo.start()
    result = echo.run_task(FakeTask(args={"symbol": "NVDA"}))
    assert isinstance(result, TaskResult)
    assert result.status == "ok"
    assert result.data == {"echoed": {"symbol": "NVDA"}}


def test_run_task_on_a_stopped_agent_fails_rather_than_raising(echo: EchoAgent) -> None:
    outcome = echo.run_task(FakeTask())
    assert isinstance(outcome, TaskFailure)
    assert outcome.failure_class == "fatal"
    assert "not started" in outcome.reason


@pytest.mark.parametrize(
    ("error", "expected_class", "retryable"),
    [
        (TransientError("blip"), "transient", True),
        (DegradedError("stale"), "degraded", False),
        (FatalError("bad config"), "fatal", False),
    ],
)
def test_typed_errors_become_typed_failures(
    echo: EchoAgent, error: Exception, expected_class: str, retryable: bool
) -> None:
    echo.start()
    echo.fail_with = error
    outcome = echo.run_task(FakeTask())
    assert isinstance(outcome, TaskFailure)
    assert outcome.failure_class == expected_class
    assert outcome.retryable is retryable


def test_an_unhandled_exception_is_fatal_not_transient(echo: EchoAgent) -> None:
    """Retrying code that raised KeyError raises KeyError again — that is a loop."""
    echo.start()
    echo.fail_with = KeyError("symbol")
    outcome = echo.run_task(FakeTask())
    assert outcome.failure_class == "fatal"
    assert outcome.retryable is False
    assert "KeyError" in outcome.reason


def test_run_task_never_raises(echo: EchoAgent) -> None:
    echo.start()
    echo.fail_with = BaseException("even this")
    assert isinstance(echo.run_task(FakeTask()), TaskFailure)


def test_agent_returns_to_idle_after_work(echo: EchoAgent) -> None:
    echo.start()
    echo.run_task(FakeTask())
    assert echo.status().state is AgentState.IDLE


def test_a_degraded_agent_stays_degraded_after_a_good_run(echo: EchoAgent) -> None:
    """Finishing one task is not evidence of recovery."""
    echo.start()
    echo.mark_degraded("feed stale")
    echo.run_task(FakeTask())
    assert echo.status().state is AgentState.DEGRADED


# --------------------------------------------------------------------------
# Observation
# --------------------------------------------------------------------------


def test_status_reports_last_action(echo: EchoAgent) -> None:
    echo.start()
    echo.run_task(FakeTask(type="echo.run"))
    status = echo.status()
    assert status.last_action == "echo.run"
    assert status.last_action_at is not None


def test_health_is_cheap_and_reflects_liveness(echo: EchoAgent) -> None:
    assert not echo.health().alive
    echo.start()
    assert echo.health().alive


def test_result_serialises_to_the_note_shape(echo: EchoAgent) -> None:
    echo.start()
    payload = echo.run_task(FakeTask()).to_dict()
    assert set(payload) == {
        "task_id", "agent", "status", "degraded", "data", "wrote",
        "spoken_summary", "cost",
    }


def test_failure_serialises_to_the_note_shape(echo: EchoAgent) -> None:
    echo.start()
    echo.fail_with = TransientError("blip", spoken_summary="Feed's down.")
    payload = echo.run_task(FakeTask()).to_dict()
    assert payload["status"] == "failed"
    assert payload["class"] == "transient"
    assert payload["spoken_summary"] == "Feed's down."


def test_no_agent_can_reach_another_agent(echo: EchoAgent) -> None:
    """The rule that keeps the system legible, enforced by absence of an API."""
    for name in dir(echo):
        assert "agent" not in name.lower() or name in {
            "declaration", "mark_degraded",
        }, f"{name} may expose another agent"
