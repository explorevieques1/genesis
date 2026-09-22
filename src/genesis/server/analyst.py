# Spec: Genesis Markdown/00-Meta/UI-0 Build Order.md §step 0
#       Genesis Markdown/10-Architecture/Operating Model.md §2 §4
"""The senior analyst, reachable by typing.

``POST /v1/command`` matched the deterministic command table and stopped. A
sentence the table did not know came back as *"I didn't catch a command in
that"* -- with a fully-wired reasoner one import away, reachable only by
speaking into a microphone.

That is the parity failure Operating Model §2 is written against, and this
module is the other half of the fix: :mod:`genesis.orchestrator.answer` made
the ladder callable, and this makes the daemon a caller.

**Built on first use, not at start-up.** The same reasoning ``tool_routes``
uses for the gateway: a ladder needs an LLM client and, for tools, seventeen
MCP subprocesses. Paying that when the daemon boots makes ``genesis serve``
look broken. Paying it on the first sentence the command table declines is the
honest moment -- a person asked a real question, and the task is already
narrated onto the bus, so the wait is visible rather than mysterious.

**It shares the gateway with the hand-driven tool route** (``tool_routes.GATEWAY``)
rather than building its own. Not only to avoid two copies of every server
subprocess: the parity rule is that a person and the model reach the same
catalogue through the same chokepoint, and two gateways is two catalogues that
can drift.

**Reads only.** The ladder answers from the ``orchestrator`` allow-list, which
grants no execution, no broker, no order. Safety Invariants §1 is unaffected
because there is nothing here to route around -- this route could not reach an
order path if it tried.
"""

from __future__ import annotations

import logging
import threading

from genesis.orchestrator.answer import Ladder, Rung

__all__ = ["Analyst", "ANALYST"]

log = logging.getLogger(__name__)


class Analyst:
    """The answer ladder for the HTTP path, built once, lazily, under a lock.

    The lock is held across the whole build for the same reason
    ``tool_routes`` holds its own: two questions asked at once must not start
    two gateways. The second caller waiting for the first is correct.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ladder: Ladder | None = None
        self._notes: list[str] = []
        self._bus = None
        self._registry = None
        self._supervisor = None
        self._scheduler = None

    def attach(self, *, bus=None, registry=None, supervisor=None, scheduler=None) -> None:  # noqa: ANN001
        """Give the HTTP path a Task Bus and a fleet to plan for.

        Called by whatever started a daemon in this process. Until it is, the
        planning rung is *absent* rather than lying -- a catalogue advertising
        agents nothing will drain turns "I'll research that" into a task that
        queues forever.

        Any ladder already built is discarded, because a ladder built before
        the fleet arrived has no planning rung and would keep answering from
        the reasoner alone for the life of the process. That is the bug this
        method exists to not have.
        """
        with self._lock:
            self._bus = bus
            self._registry = registry
            self._supervisor = supervisor
            self._scheduler = scheduler
            self._ladder = None

    @property
    def bus(self):  # noqa: ANN201
        """The daemon's Task Bus, or ``None`` until a fleet is attached."""
        return self._bus

    @property
    def planning(self) -> bool:
        """Whether a typed sentence can reach the fleet."""
        return self._bus is not None and bool(self._registry)

    def ladder(self) -> Ladder:
        """The ladder. Blocking, slow on the first call, instant after.

        Never raises. A ladder with every rung ``None`` is a real, honest
        state -- it answers *"I can't reach my reasoning model right now"*,
        which is what a trader with no API key should hear rather than a 500.
        """
        with self._lock:
            if self._ladder is None:
                self._ladder = self._build()
            return self._ladder

    def _build(self) -> Ladder:
        notes: list[str] = []
        try:
            from genesis.config import load_config
            from genesis.orchestrator.build import build_ladder
            from genesis.server.tool_routes import GATEWAY

            gateway, error = GATEWAY.get()
            if error:
                notes.append(f"no MCP gateway: {error}")

            # With a bus and a registry -- which `genesis serve` attaches once
            # its in-process daemon has built the fleet -- the planning rung is
            # live, and a *typed* sentence reaches the same agents a spoken one
            # does. That is Operating Model §3 ("typed and spoken are one
            # path") stated as wiring rather than as an intention.
            #
            # Without them the ladder is verbosity -> trivial -> reasoner, and
            # the planning rung declines by being absent rather than by lying.
            if self._bus is None:
                notes.append("no task bus attached — typed commands cannot reach the fleet")
            parts = build_ladder(
                load_config(),
                gateway=gateway,
                bus=self._bus,
                registry=self._registry,
                supervisor=self._supervisor,
                scheduler=self._scheduler,
                notes=notes,
            )
            self._notes = notes
            log.info("analyst ready · %s", "; ".join(notes) or "all rungs wired")
            return parts.ladder
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            # A broken config or a missing dependency must not take the daemon
            # down. It costs the slow rungs and says so in the log; the
            # deterministic command table in front of this is untouched.
            log.exception("the answer ladder did not build")
            self._notes = [f"{type(exc).__name__}: {exc}"]
            return Ladder()

    @property
    def notes(self) -> list[str]:
        """Degradations found while building. Reported, never swallowed."""
        return list(self._notes)

    def answer(self, text: str, *, context: str = "") -> Rung:
        """One question, one Rung. Blocking -- call it in an executor."""
        return self.ladder().answer(text, context=context)


#: One per process. The build is expensive and the result is stateless.
ANALYST = Analyst()

