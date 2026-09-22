# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The catalogue. One canonical tool per capability, and nothing else.

MCP Gateway.md asks for "every MCP tool and every built-in tool in one
searchable catalogue, with normalized schemas", so an agent asks for a
capability rather than a server. Two rules do the real work.

**Deduplicate at the registry, not the router.**
``openbb``, ``mcp-market-data-server`` and ``tradingview-mcp`` all return
quotes. MCP Server Catalog.md is precise about why three ``get_quote`` variants
is a *different* failure from having too many tools: the router picks a
defensible-but-wrong one and the agent never notices, because the shape of the
answer is right. The losers are therefore **unregistered**, not deprioritised.
The contest is decided by tier -- Market Data Sources.md, lowest wins, tier 1
being the venue's own book -- and a tie raises rather than picks, because a
silent coin-flip between two data sources is the thing this rule exists to
prevent.

**Writes are gated, and one class of write is gated absolutely.**
Two different rules, because they protect against two different things.

``allow_writes`` is the ordinary gate. Off by default, so a server's write half
does not register unless somebody decided it should. Turning it on is how the
vault gets written -- Phase 4's exit criterion is a daily brief *in the vault*,
which is a write, and a system that can only read cannot produce it.

:data:`EXECUTION_NAMESPACES` is the absolute one. Anything that can move money
or position is refused whatever ``allow_writes`` says, and only
``allow_execution_writes`` -- a Phase 7 act, performed by the server that owns
the risk gate -- lifts it. This is Safety Invariants §1 as a structure: a write
to a markdown file and a write to a broker are not the same kind of thing, and
a single boolean that conflated them would eventually be turned on for the
wrong reason. The one that matters is not reachable by the flag anybody has a
day-to-day motive to flip.

Every refusal is kept in :attr:`ToolRegistry.rejected`. A catalogue that
silently omits things is indistinguishable from a broken loader, and the first
question anyone asks about a missing tool is *why*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from genesis.config import ConfigError
from genesis.mcp.errors import ToolNotRegisteredError
from genesis.mcp.spec import ToolSpec

__all__ = ["EXECUTION_NAMESPACES", "Rejection", "ToolRegistry"]

#: Capability namespaces that move money or position. Refused regardless of
#: ``allow_writes``; only ``allow_execution_writes`` reaches them. Prefixes, so
#: ``order.propose`` and ``order.place`` are both covered without enumerating.
EXECUTION_NAMESPACES = ("order.", "broker.", "position.", "execution.", "genesis-execution.")


def _is_execution(capability: str) -> bool:
    return any(capability.startswith(ns) for ns in EXECUTION_NAMESPACES)


@dataclass(frozen=True)
class Rejection:
    """A tool that was offered and not catalogued, and why."""

    tool_id: str
    reason: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.tool_id}: {self.reason}"


class ToolRegistry:
    """The gateway's world model.

    Not thread-safe for writes, deliberately: the catalogue is built once at
    start-up on one thread and read from many afterwards. A registry that could
    be mutated from a worker mid-call is a registry whose contents depend on
    timing, and the allow-list check reads it on every call.
    """

    def __init__(
        self,
        *,
        allow_writes: bool = False,
        allow_execution_writes: bool = False,
    ) -> None:
        self._by_id: dict[str, ToolSpec] = {}
        self._by_capability: dict[str, ToolSpec] = {}
        self.allow_writes = allow_writes
        self.allow_execution_writes = allow_execution_writes
        self.rejected: list[Rejection] = []

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------

    def register(self, spec: ToolSpec) -> bool:
        """Offer a tool to the catalogue. Returns whether it was taken.

        Raises only for conditions an operator must fix -- a duplicate id, or a
        capability contest with no defensible winner. Everything else is a
        recorded rejection, because a server offering one tool we do not want
        is normal and must not stop the other forty from registering.
        """
        if spec.id in self._by_id:
            raise ConfigError(f"tool {spec.id!r} is registered twice")

        if spec.mutating and _is_execution(spec.capability):
            # The absolute gate. No amount of ordinary write permission reaches
            # a capability that can move money — Safety Invariants §1.
            if not self.allow_execution_writes:
                self._reject(
                    spec,
                    f"execution-namespace write ({spec.capability}) — refused "
                    f"until the Pre-Trade Risk Engine exists",
                )
                return False
        elif spec.mutating and not self.allow_writes:
            self._reject(spec, "write tool, and this registry is read-only")
            return False

        incumbent = self._by_capability.get(spec.capability)
        if incumbent is not None and not self._wins(spec, incumbent):
            return False

        if incumbent is not None:
            del self._by_id[incumbent.id]
            self._reject(
                incumbent,
                f"capability {spec.capability!r} won by {spec.id} at tier {spec.tier}",
            )

        self._by_id[spec.id] = spec
        self._by_capability[spec.capability] = spec
        return True

    def register_all(self, specs: Iterable[ToolSpec]) -> int:
        """Register many, in tier order so the contest outcome is stable.

        Sorting first is what makes registration order irrelevant: without it,
        the same config loaded twice could catalogue different tools depending
        on which server answered ``list_tools`` first.
        """
        taken = 0
        for spec in sorted(specs, key=lambda s: (s.tier, s.id)):
            taken += bool(self.register(spec))
        return taken

    def _wins(self, challenger: ToolSpec, incumbent: ToolSpec) -> bool:
        if challenger.tier == incumbent.tier:
            raise ConfigError(
                f"capability {challenger.capability!r} is claimed by both "
                f"{incumbent.id!r} and {challenger.id!r} at tier {challenger.tier}. "
                f"Registry deduplication cannot pick between them — set a tier, or "
                f"drop one. See MCP Server Catalog.md §overlap."
            )
        if challenger.tier > incumbent.tier:
            self._reject(
                challenger,
                f"capability {challenger.capability!r} already owned by "
                f"{incumbent.id} at tier {incumbent.tier}",
            )
            return False
        return True

    def _reject(self, spec: ToolSpec, reason: str) -> None:
        self.rejected.append(Rejection(spec.id, reason))

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self._by_id[tool_id]
        except KeyError:
            raise ToolNotRegisteredError(tool_id) from None

    def find(self, tool_id: str) -> ToolSpec | None:
        return self._by_id.get(tool_id)

    def for_capability(self, capability: str) -> ToolSpec | None:
        """The one tool that owns this capability, or nothing."""
        return self._by_capability.get(capability)

    def by_server(self, server: str) -> tuple[ToolSpec, ...]:
        return tuple(s for s in self if s.server == server)

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_capability))

    def surface(self) -> tuple[str, ...]:
        """The registered surface, one line per tool, sorted.

        This is what a test enumerates to assert that no mutating Alpaca tool
        is present -- and what a person reads when they want to know what the
        fleet can actually do.
        """
        return tuple(s.catalogue_line() for s in sorted(self, key=lambda s: s.id))

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, tool_id: object) -> bool:
        return tool_id in self._by_id
