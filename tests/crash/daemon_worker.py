# Spec: Genesis Markdown/00-Meta/Build Order.md  (Phase 1 exit criterion)
"""Child process for the echo-agent exit test.

Runs a real daemon against a real database, claims the echo agent's task, and
SIGKILLs itself while the task is in flight -- after the claim, before the
completion. That is the worst moment: the bus believes the work is running and
the only thing that will ever say otherwise is the claim TTL.

Run as:  python daemon_worker.py <db> <mode>

``crash``
    Claim the task, start it, then die mid-run.
``resume``
    Boot, recover, and drain normally -- the restarted daemon.
"""

from __future__ import annotations

import datetime as dt
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from genesis.bus import TaskBus  # noqa: E402
from genesis.daemon import Daemon  # noqa: E402
from genesis.observability import Console  # noqa: E402

from tests.crash.echo_fixture import CRASH_TTL_SEC, build_daemon  # noqa: E402


def main() -> None:
    db, mode = sys.argv[1], sys.argv[2]
    daemon, agent = build_daemon(db)
    now = dt.datetime(2026, 8, 31, 14, 0, tzinfo=dt.UTC)  # 10:00 ET, market open

    if mode == "crash":
        daemon.boot(now)
        # Dispatch the cadence work onto the bus.
        for work in daemon.scheduler.due(now):
            daemon.bus.submit(
                type=f"{work.agent_id}.run",
                agent=work.agent_id,
                args={"reason": work.reason},
                idempotency_key=f"cadence:{work.agent_id}:{work.cadence.type}",
                trace_id="tr_exit_criterion",
            )
        task = daemon.bus.claim(agent="echo", ttl_sec=CRASH_TTL_SEC)
        daemon.bus.start(task.id)
        print(task.id, flush=True)
        sys.stdout.flush()
        os.kill(os.getpid(), signal.SIGKILL)  # mid-run, claim held

    if mode == "resume":
        daemon.boot(now)
        report = daemon.tick(now)
        print(",".join(report.ran), flush=True)
        print(f"runs={len(agent.runs)}", flush=True)


if __name__ == "__main__":
    main()
