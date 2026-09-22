# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""The one place MCP tools become something a model can call.

The gateway already decides *what an agent may reach* and *what it costs to
reach it* -- allow-list, SSRF guard, cache, rate limit, fence. This module adds
nothing to that. It translates:

* a :class:`~genesis.mcp.spec.ToolSpec` into an Anthropic tool schema, and
* an Anthropic ``tool_use`` block back into a :meth:`Gateway.call`.

Everything load-bearing stays on the gateway side of the translation, which is
the point. If a check ever moves into this file it stops applying to agents that
call the gateway directly, and the boundary becomes two boundaries.

**Selection is per turn, not per process.** Orchestrator.md's latency criterion
is *"adding 50 MCP tools changes orchestrator latency by less than 10%"*, and
101 tool schemas in a prompt fails it on the first turn -- roughly 20k tokens
before the trader has said anything. :func:`tools_for_utterance` asks the
router for the handful that match what was actually said. The escape hatch for
a bad guess is ``tool_search``, which is a tool like any other and is budgeted.

**A tool name is not a capability.** The model sees sanitised names because the
API constrains them to ``[a-zA-Z0-9_-]``; ``market-data.ohlcv`` is not legal and
``market_data__ohlcv`` is. The mapping is held here and reversed on the way
back, so a model that invents a name resolves to nothing and gets an error
rather than a lucky near-match against a real capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from genesis.errors import GenesisError
from genesis.mcp.router import SearchBudget, SearchBudgetExhausted

if TYPE_CHECKING:  # pragma: no cover - typing only
    from genesis.llm.anthropic_backend import ToolCall
    from genesis.mcp.gateway import Gateway
    from genesis.mcp.spec import ToolSpec

__all__ = [
    "SEARCH_TOOL",
    "SEARCH_TOOL_NAME",
    "ToolBridge",
    "schema_for",
    "wire_name",
]

#: How many tools the router puts in front of the model for one utterance.
#: Eight rather than the gateway's own default because these are rendered as
#: full JSON schemas into a prompt on the voice latency path, where the cost of
#: one more is paid in silence the operator hears.
DEFAULT_TOOL_LIMIT = 8

#: Tool searches allowed per utterance. The escape hatch has to be capped or it
#: becomes a loop made of rephrasings -- the router's own warning, and it
#: applies with more force here because the model controls the rephrasing.
DEFAULT_SEARCH_BUDGET = 3

SEARCH_TOOL_NAME = "find_more_tools"

#: The escape hatch, described to the model in terms of when to reach for it.
#: Deliberately the only tool in the surface that is not an MCP tool.
SEARCH_TOOL: dict[str, Any] = {
    "name": SEARCH_TOOL_NAME,
    "description": (
        "Search for a tool that is not in the list above. Use this only when "
        "none of the offered tools can do what was asked. Returns tool names "
        "and descriptions; it does not call anything."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What the tool needs to do, in a few words.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def wire_name(capability: str) -> str:
    """``market-data.ohlcv`` -> ``market_data__ohlcv``.

    The API restricts tool names to ``[a-zA-Z0-9_-]{1,128}``, so the dots and
    dashes a capability is written with cannot survive the trip. Two separators
    rather than one because collapsing both to ``_`` would map
    ``market-data.ohlcv`` and ``market.data.ohlcv`` onto the same wire name,
    and the reverse lookup would then be a coin flip.
    """
    return capability.replace("-", "_").replace(".", "__")


def schema_for(spec: ToolSpec) -> dict[str, Any]:
    """One :class:`ToolSpec` as an Anthropic tool definition.

    The description carries the read/write distinction in words the model acts
    on, because Biological Design's afferent/efferent split is only real if it
    is visible at the point of choosing. The *enforcement* is the gateway's
    allow-list, not this sentence -- a description is guidance, and guidance is
    not a boundary.
    """
    schema = dict(spec.input_schema) if spec.input_schema else {"type": "object", "properties": {}}
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})

    description = spec.description or spec.capability
    if not spec.mutating:
        description = f"[read-only] {description}"
    return {
        "name": wire_name(spec.capability),
        "description": description[:1024],
        "input_schema": schema,
    }


@dataclass
class ToolBridge:
    """Renders a tool surface for one agent, and executes what it calls back.

    One bridge per agent identity, not per turn: the allow-list and the search
    budget are properties of *who is asking*, and a fresh bridge per utterance
    would reset the budget on every sentence, which is the same as not having
    one.
    """

    gateway: Gateway
    agent: str = "orchestrator"
    limit: int = DEFAULT_TOOL_LIMIT
    search_budget: int = DEFAULT_SEARCH_BUDGET
    #: capability, keyed by the sanitised name the model was shown.
    _by_wire: dict[str, str] = field(default_factory=dict, repr=False)
    _budget: SearchBudget | None = field(default=None, repr=False)

    # -- what the model is shown -------------------------------------------

    def tools_for_utterance(
        self, utterance: str, *, task_type: str = ""
    ) -> list[dict[str, Any]]:
        """The tool schemas worth offering for this utterance.

        Resets the per-utterance state, so this is also the call that starts a
        turn. An empty list is a real answer and not a failure: it means the
        agent can reach nothing relevant, and the caller should say so rather
        than hand the model an empty surface and a hopeful prompt.
        """
        self._by_wire = {}
        self._budget = SearchBudget(self.search_budget)

        selection = self.gateway.select(
            self.agent, utterance, task_type=task_type, limit=self.limit
        )
        schemas = [self._offer(spec) for spec in selection]
        if schemas:
            # Only worth offering when there is something to search *past*.
            schemas.append(SEARCH_TOOL)
        return schemas

    def _offer(self, spec: ToolSpec) -> dict[str, Any]:
        schema = schema_for(spec)
        self._by_wire[schema["name"]] = spec.capability
        return schema

    # -- what comes back ----------------------------------------------------

    def execute(self, call: ToolCall) -> tuple[str, bool]:
        """Run one model-requested call. Returns ``(content, is_error)``.

        Never raises. Every outcome the model could act on -- a result, a
        refusal, an unknown name, an exhausted budget -- comes back as content,
        because the loop's contract is that a call always produces a result.
        Raising here would strand a ``tool_use`` block with no ``tool_result``,
        which is both an API error and a model that starts guessing.
        """
        if call.name == SEARCH_TOOL_NAME:
            return self._search(str(call.arguments.get("query", "")))

        capability = self._by_wire.get(call.name)
        if capability is None:
            # Either a hallucinated name or one from a previous turn's surface.
            # Both are the same mistake from here, and naming the tools that
            # *are* available is what lets the model recover in one step.
            offered = ", ".join(sorted(self._by_wire)) or "none"
            return (
                f"No tool named {call.name!r}. Available: {offered}. "
                f"Use {SEARCH_TOOL_NAME} to look for something else.",
                True,
            )

        try:
            result = self.gateway.call(self.agent, capability, call.arguments)
        except GenesisError as exc:
            # A typed failure is the gateway working as designed: denied by the
            # allow-list, rate limited, fenced, or the server is down. Every one
            # of those is something the model can act on, so it sees the reason
            # rather than a bare failure. ToolCallError is a DegradedError, so
            # this is also the path a tool's own error takes.
            return f"{capability} failed: {exc.reason}", True

        return _render(result), False

    def _search(self, query: str) -> tuple[str, bool]:
        if not query.strip():
            return "find_more_tools needs a query.", True
        budget = self._budget or SearchBudget(self.search_budget)
        try:
            selection = self.gateway.tool_search(
                self.agent, query, budget=budget, limit=5
            )
        except SearchBudgetExhausted:
            return (
                "No searches left this turn. Answer with the tools you have, "
                "or say what you cannot do.",
                True,
            )
        except GenesisError as exc:
            return f"tool search failed: {exc.reason}", True

        if not len(selection):
            return f"No tool matches {query!r}.", False

        lines = []
        for spec in selection:
            schema = self._offer(spec)
            lines.append(f"- {schema['name']}: {schema['description'][:200]}")
        return (
            "These are now callable:\n" + "\n".join(lines),
            False,
        )


def _render(result: Any) -> str:
    """A :class:`~genesis.mcp.runtime.ToolResult` as text for the model.

    Deliberately dumb. The gateway has already fenced untrusted content, and
    re-interpreting a payload here -- picking fields, summarising, pretty
    printing JSON -- would be this module quietly deciding what the model gets
    to see, which is a judgement it has no basis to make.
    """
    content = getattr(result, "content", result)
    if isinstance(content, str):
        return content
    if content is None:
        return "(no content)"
    return str(content)
