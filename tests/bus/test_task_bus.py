# Spec: Genesis Markdown/10-Architecture/Task Bus.md
"""The bus's acceptance criteria, as tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from genesis.bus import Lane, TaskBus, TaskState


@pytest.fixture
def bus(tmp_path: Path) -> TaskBus:
    b = TaskBus(tmp_path / "genesis.db")
    yield b
    b.close()


def drain_to_done(bus: TaskBus, task_id: str) -> None:
    bus.start(task_id)
    bus.complete(task_id, {"ok": True})


# --------------------------------------------------------------------------
# Lanes
# --------------------------------------------------------------------------


def test_lane_priority_order() -> None:
    assert list(Lane) == [
        Lane.EXECUTION, Lane.RISK, Lane.USER,
        Lane.EVENT, Lane.RESEARCH, Lane.MAINTENANCE,
    ]


def test_protected_lanes_are_never_sheddable() -> None:
    """Structural: nothing in the shedding path can reach these."""
    for lane in (Lane.EXECUTION, Lane.RISK, Lane.USER):
        assert not lane.sheddable
        assert lane.critical
    for lane in (Lane.EVENT, Lane.RESEARCH, Lane.MAINTENANCE):
        assert lane.sheddable


def test_higher_lane_drains_first(bus: TaskBus) -> None:
    bus.submit(type="scan", agent="screener", lane=Lane.RESEARCH)
    bus.submit(type="order.place", agent="order-manager", lane=Lane.EXECUTION)
    bus.submit(type="ask", agent="orchestrator", lane=Lane.USER)

    assert bus.claim().lane is Lane.EXECUTION
    assert bus.claim().lane is Lane.USER
    assert bus.claim().lane is Lane.RESEARCH


def test_unknown_lane_names_the_valid_ones(bus: TaskBus) -> None:
    with pytest.raises(ValueError, match="execution, risk, user"):
        bus.submit(type="x", agent="a", lane="urgent")


def test_execution_starts_fast_behind_a_deep_research_backlog(bus: TaskBus) -> None:
    """Acceptance criterion: <50 ms behind 1000 queued research tasks."""
    for i in range(1000):
        bus.submit(type="scan", agent="screener", lane=Lane.RESEARCH,
                   idempotency_key=f"scan-{i}")
    bus.submit(type="order.place", agent="order-manager", lane=Lane.EXECUTION)

    start = time.perf_counter()
    claimed = bus.claim(lanes=[Lane.EXECUTION, Lane.RISK, Lane.USER])
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert claimed.lane is Lane.EXECUTION
    assert elapsed_ms < 50, f"took {elapsed_ms:.1f} ms"


def test_worker_pools_are_separable_by_lane(bus: TaskBus) -> None:
    """The critical pool must not be able to pick up research work."""
    bus.submit(type="scan", agent="screener", lane=Lane.RESEARCH)
    assert bus.claim(lanes=[Lane.EXECUTION, Lane.RISK, Lane.USER]) is None
    assert bus.claim(lanes=[Lane.RESEARCH]) is not None


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_reenqueue_of_live_key_is_a_noop(bus: TaskBus) -> None:
    first = bus.submit(type="scan", agent="screener", idempotency_key="scan:NVDA:1m")
    second = bus.submit(type="scan", agent="screener", idempotency_key="scan:NVDA:1m")
    assert first is not None
    assert second is None
    assert len(bus.by_idempotency_key("scan:NVDA:1m")) == 1


def test_key_is_reusable_once_the_task_is_terminal(bus: TaskBus) -> None:
    first = bus.submit(type="scan", agent="screener", idempotency_key="k")
    claimed = bus.claim()
    drain_to_done(bus, claimed.id)

    second = bus.submit(type="scan", agent="screener", idempotency_key="k")
    assert second is not None and second.id != first.id


def test_tasks_without_a_key_are_never_deduplicated(bus: TaskBus) -> None:
    a = bus.submit(type="scan", agent="screener")
    b = bus.submit(type="scan", agent="screener")
    assert a is not None and b is not None and a.id != b.id


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------


def test_dependent_waits_until_parent_is_done(bus: TaskBus) -> None:
    parent = bus.submit(type="fetch", agent="a", lane=Lane.RESEARCH)
    bus.submit(type="use", agent="b", lane=Lane.RESEARCH, depends_on=[parent.id])

    assert bus.claim().id == parent.id
    assert bus.claim() is None, "dependent must not be claimable yet"

    drain_to_done(bus, parent.id)
    assert bus.claim().type == "use"


def test_failed_parent_cancels_dependents_with_the_reason(bus: TaskBus) -> None:
    """Cancelled, not silently dropped — the orchestrator must speak honestly."""
    parent = bus.submit(type="fetch", agent="a")
    child = bus.submit(type="use", agent="b", depends_on=[parent.id])

    claimed = bus.claim()
    bus.fail(claimed.id, {"class": "fatal", "reason": "feed down", "retryable": False})

    child = bus.get(child.id)
    assert child.state is TaskState.CANCELLED
    assert "feed down" in child.failure["reason"]


def test_cancellation_cascades_through_the_dag(bus: TaskBus) -> None:
    a = bus.submit(type="a", agent="x")
    b = bus.submit(type="b", agent="x", depends_on=[a.id])
    c = bus.submit(type="c", agent="x", depends_on=[b.id])

    bus.cancel(a.id, "user stopped it")

    assert bus.get(b.id).state is TaskState.CANCELLED
    assert bus.get(c.id).state is TaskState.CANCELLED


def test_missing_dependency_cancels_rather_than_hanging(bus: TaskBus) -> None:
    task = bus.submit(type="use", agent="b", depends_on=["t_does_not_exist"])
    assert bus.claim() is None
    assert bus.get(task.id).state is TaskState.CANCELLED


# --------------------------------------------------------------------------
# Retry and claim expiry — how work survives a killed worker
# --------------------------------------------------------------------------


def test_retryable_failure_returns_to_pending(bus: TaskBus) -> None:
    bus.submit(type="scan", agent="screener", max_attempts=3)
    claimed = bus.claim()
    bus.fail(claimed.id, {"class": "transient", "reason": "blip", "retryable": True})
    assert bus.get(claimed.id).state is TaskState.PENDING


def test_non_retryable_failure_does_not_retry(bus: TaskBus) -> None:
    """Retrying a fatal turns a bug into a loop instead of an alert."""
    bus.submit(type="scan", agent="screener", max_attempts=5)
    claimed = bus.claim()
    bus.fail(claimed.id, {"class": "fatal", "reason": "bug", "retryable": False})
    assert bus.get(claimed.id).state is TaskState.FAILED


def test_a_retried_task_is_not_immediately_reclaimable(bus: TaskBus) -> None:
    """Backoff, not a busy loop.

    Without this the drain loop re-claims the task on its very next iteration
    and burns every attempt in microseconds — which is not a retry policy, it is
    a fast way to exhaust one.
    """
    bus.submit(type="scan", agent="screener")
    claimed = bus.claim()
    bus.fail(claimed.id, {"class": "transient", "reason": "blip", "retryable": True})

    assert bus.get(claimed.id).state is TaskState.PENDING
    assert bus.claim() is None, "must wait out the backoff"
    assert bus.get(claimed.id).not_before is not None


def test_backoff_grows_with_attempts() -> None:
    from genesis.bus.bus import retry_delay

    delays = [retry_delay(n, base_sec=1.0) for n in range(1, 6)]
    assert delays[0] < delays[1] < delays[2] < delays[3] < delays[4]
    assert delays[0] >= 1.0
    assert retry_delay(100, base_sec=1.0) <= 60.0 * 1.25, "capped at 60s plus jitter"


def test_attempts_are_exhausted_then_the_task_fails(tmp_path: Path) -> None:
    bus = TaskBus(tmp_path / "genesis.db", retry_backoff_base_sec=0.0)
    bus.submit(type="scan", agent="screener", max_attempts=2)
    for _ in range(2):
        claimed = bus.claim()
        bus.fail(claimed.id, {"class": "transient", "reason": "blip", "retryable": True})
    assert bus.get(claimed.id).state is TaskState.FAILED
    bus.close()


def test_expired_claim_requeues_the_task(bus: TaskBus) -> None:
    """A SIGKILLed worker cannot release its claim; the TTL does it."""
    bus.submit(type="scan", agent="screener")
    claimed = bus.claim(ttl_sec=0.01)
    bus.start(claimed.id)
    time.sleep(0.05)

    reclaimed = bus.claim()
    assert reclaimed.id == claimed.id
    assert reclaimed.attempts == 2


def test_claim_expiry_is_logged_as_degraded(bus: TaskBus) -> None:
    task = bus.submit(type="scan", agent="screener")
    bus.claim(ttl_sec=0.01)
    time.sleep(0.05)
    bus.claim()

    kinds = [e.kind for e in bus.log.by_trace(task.trace_id)]
    assert "task.claim_expired" in kinds
    expired = next(e for e in bus.log.by_trace(task.trace_id)
                   if e.kind == "task.claim_expired")
    assert expired.degraded is True


def test_exhausted_claim_expiry_fails_rather_than_looping(bus: TaskBus) -> None:
    bus.submit(type="scan", agent="screener", max_attempts=1)
    claimed = bus.claim(ttl_sec=0.01)
    time.sleep(0.05)
    assert bus.claim() is None
    assert bus.get(claimed.id).state is TaskState.FAILED


# --------------------------------------------------------------------------
# Persistence and recovery
# --------------------------------------------------------------------------


def test_queue_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "genesis.db"
    bus = TaskBus(path)
    task = bus.submit(type="scan", agent="screener", lane=Lane.RESEARCH)
    bus.close()

    reopened = TaskBus(path)
    assert reopened.get(task.id).state is TaskState.PENDING
    reopened.close()


def test_recover_requeues_claims_orphaned_by_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "genesis.db"
    bus = TaskBus(path)
    task = bus.submit(type="scan", agent="screener")
    bus.claim(ttl_sec=0.01)
    bus.close()
    time.sleep(0.05)

    reopened = TaskBus(path)
    counts = reopened.recover()
    assert counts["requeued"] == 1
    assert reopened.get(task.id).state is TaskState.PENDING
    reopened.close()


def test_recover_sheds_tasks_whose_deadline_passed_while_down(tmp_path: Path) -> None:
    path = tmp_path / "genesis.db"
    bus = TaskBus(path)
    task = bus.submit(type="scan", agent="screener",
                      deadline="2020-01-01T00:00:00.000Z")
    bus.close()

    reopened = TaskBus(path)
    counts = reopened.recover()
    assert counts["expired"] == 1
    assert reopened.get(task.id).state is TaskState.SHED
    reopened.close()


# --------------------------------------------------------------------------
# Backpressure
# --------------------------------------------------------------------------


def test_shedding_drops_oldest_research_first(bus: TaskBus) -> None:
    tasks = [bus.submit(type="scan", agent="screener", lane=Lane.RESEARCH,
                        idempotency_key=f"s{i}") for i in range(10)]
    shed = bus.shed(limit=6)

    assert shed == 4
    assert bus.get(tasks[0].id).state is TaskState.SHED
    assert bus.get(tasks[-1].id).state is TaskState.PENDING


def test_shedding_never_touches_a_protected_lane(bus: TaskBus) -> None:
    """The rule that must not be tunable away."""
    protected = [
        bus.submit(type="o", agent="order-manager", lane=Lane.EXECUTION),
        bus.submit(type="r", agent="risk", lane=Lane.RISK),
        bus.submit(type="u", agent="orchestrator", lane=Lane.USER),
    ]
    for i in range(20):
        bus.submit(type="scan", agent="screener", lane=Lane.RESEARCH,
                   idempotency_key=f"s{i}")

    bus.shed(limit=0)

    for task in protected:
        assert bus.get(task.id).state is TaskState.PENDING


def test_depth_counts_only_live_tasks(bus: TaskBus) -> None:
    bus.submit(type="a", agent="x", lane=Lane.RESEARCH)
    claimed_source = bus.submit(type="b", agent="x", lane=Lane.RESEARCH)
    claimed = bus.claim()
    drain_to_done(bus, claimed.id)
    assert bus.depth(Lane.RESEARCH) == 1


# --------------------------------------------------------------------------
# Observability — the criterion that every transition is reconstructible
# --------------------------------------------------------------------------


def test_every_transition_is_in_the_episodic_log_in_causal_order(bus: TaskBus) -> None:
    task = bus.submit(type="scan", agent="screener", lane=Lane.USER)
    claimed = bus.claim()
    bus.start(claimed.id)
    bus.complete(claimed.id, {"candidates": 9})

    kinds = [e.kind for e in bus.log.by_trace(task.trace_id)]
    assert kinds == ["task.submitted", "task.claimed", "task.running", "task.done"]


def test_every_log_entry_carries_trace_actor_and_kind(bus: TaskBus) -> None:
    task = bus.submit(type="scan", agent="screener")
    claimed = bus.claim()
    bus.start(claimed.id)
    bus.complete(claimed.id, {})

    for entry in bus.log.by_trace(task.trace_id):
        assert entry.trace_id and entry.actor and entry.kind


def test_trace_id_flows_from_submit_to_every_entry(bus: TaskBus) -> None:
    task = bus.submit(type="scan", agent="screener", trace_id="tr_explicit")
    claimed = bus.claim()
    bus.complete(claimed.id, {})
    assert all(e.trace_id == "tr_explicit" for e in bus.log.by_trace("tr_explicit"))
