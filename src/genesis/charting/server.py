# Spec: Genesis Markdown/30-MCP/genesis-charting-mcp.md
"""genesis-charting-mcp — level computation and rendering, as tools.

The note lists six tools; all six are here, plus ``render_analytics``, which the
non-price half of the family needs and which no third-party server can provide
because the analytics spec is ours too.

**Every tool takes ids and symbols. None takes rows.** A tool's arguments are
written by a language model, so an argument big enough to hold bars is an
argument that costs two hundred rows of context before the first level is
computed -- and Orchestrator Tools.md's rule (*"moves ids and summaries, never
rows"*) exists precisely for that. Bars are fetched on this side of the model by
:mod:`genesis.charting.source`, through the gateway, with the allow-list and
rate limits still in force.

**Why ours, restated from the note.** The Markup Spec is a Genesis concept no
third-party server knows about; rendering must be deterministic and identical
across the vault, the dashboard and vision input; and ``diff_spec`` is only
possible because specs are immutable objects we control.

Access is allow-listed to the Charting Family and, for ``compile_pine``, to
Agent — Strategy Author.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from genesis.charting.analytics import AnalyticsSpec, render_analytics
from genesis.charting.compose import candidate_table, candidates, compose_default
from genesis.charting.levels import compute_levels
from genesis.charting.outcomes import evaluate
from genesis.charting.pine import compile_pine
from genesis.charting.render import render, render_composite
from genesis.charting.source import BarSource
from genesis.charting.store import SpecStore
from genesis.charting.structure import read_structure
from genesis.charting.timeframes import normalise
from genesis.errors import GenesisError

__all__ = ["ChartingService", "build_server", "main"]

#: Where renders land. Charting Engine.md fixes the shape of the filename --
#: SYMBOL-YYYY-MM-DD-TF.png -- because a chart is looked for by symbol and date
#: long after anyone remembers its spec id.
DEFAULT_CHART_DIR = "~/.genesis/vault/20-Charts"


class ChartingService:
    """The tools, as plain methods. The MCP surface is a thin wrapper on this.

    Separated so every behaviour is testable without an MCP session, which is
    the same split ``genesis-tradingview-mcp`` uses and for the same reason: the
    rules worth testing must run on every test run, not only where a server can
    be launched.
    """

    def __init__(
        self,
        source: BarSource,
        store: SpecStore | None = None,
        *,
        chart_dir: str | Path = DEFAULT_CHART_DIR,
        journal: Any = None,
    ) -> None:
        self.source = source
        #: Optional journal store. Scoring a spec is the moment its levels'
        #: outcomes are knowable, and once the symbol is re-marked the original
        #: question is unanswerable -- so the record is written here or not at
        #: all.
        self.journal = journal
        # `store if store is not None`, not `store or ...`: SpecStore defines
        # __len__, so an *empty* store is falsy and `or` silently swapped a
        # caller's brand-new database for the default one in ~/.genesis. The
        # symptom is a test that passes against production data.
        self.store = store if store is not None else SpecStore()
        self.chart_dir = Path(chart_dir).expanduser()

    # -- the whole pipeline, one call --------------------------------------

    def chart(
        self,
        symbol: str,
        timeframe: str = "1D",
        *,
        lookback_bars: int = 0,
        max_annotations: int = 8,
        created_by: str = "chart-markup",
        trace_id: str | None = None,
        remark: bool = True,
    ) -> dict[str, Any]:
        """Fetch, compute, compose, render, store. Returns ids and a summary.

        ``remark`` links this spec to the previous one for the same symbol and
        timeframe, so re-charting a name builds the lineage the Insight Miner
        later reads. Off only for a deliberate fresh start.
        """
        timeframe = normalise(timeframe)
        bars = self.source.fetch(symbol, timeframe, bars=lookback_bars)
        computation = compute_levels(bars, max_levels=max_annotations)
        structure = read_structure(bars)
        parent = self.store.latest(symbol, timeframe) if remark else None

        spec = compose_default(
            bars, computation, structure,
            max_annotations=max_annotations,
            created_by=created_by,
            trace_id=trace_id,
            parent=parent.id if parent else None,
        )
        result = render(bars, spec, path=self._path(spec))
        spec = spec.with_render(result.ref())
        self.store.put(spec)
        return _spec_payload(spec, computation, structure)

    # -- the note's six ----------------------------------------------------

    def compute_levels(self, symbol: str, timeframe: str = "1D", *, lookback_bars: int = 0) -> dict[str, Any]:
        """Every structural level, scored and merged. No chart, no spec."""
        timeframe = normalise(timeframe)
        bars = self.source.fetch(symbol, timeframe, bars=lookback_bars)
        computation = compute_levels(bars)
        return {
            "ok": True,
            "symbol": bars.symbol,
            "timeframe": timeframe,
            "as_of": bars.last_time.isoformat(),
            "spot": round(computation.spot, 4),
            "atr14": round(computation.atr, 4),
            "source": bars.source,
            "tier": bars.tier,
            "candidates": candidate_table(candidates(computation)),
            "notes": list(computation.notes),
            "degraded": computation.degraded,
        }

    def structure(self, symbol: str, timeframe: str = "1D", *, lookback_bars: int = 0) -> dict[str, Any]:
        """Deterministic structure measurements — the skeptic's half."""
        timeframe = normalise(timeframe)
        bars = self.source.fetch(symbol, timeframe, bars=lookback_bars)
        read = read_structure(bars)
        return {
            "ok": True, "symbol": bars.symbol, "timeframe": timeframe,
            "as_of": bars.last_time.isoformat(), **read.to_dict(),
        }

    def render_spec(self, spec_id: str, *, lookback_bars: int = 0) -> dict[str, Any]:
        """Re-render a stored spec against the bars it was built from."""
        spec = self._spec(spec_id)
        bars = self.source.fetch(spec.symbol, spec.timeframe, bars=lookback_bars)
        result = render(bars, spec, path=self._path(spec))
        return {
            "ok": True, "spec": spec.id, "image": str(result.path),
            "render_hash": result.render_hash,
        }

    def render_composite(
        self, symbol: str, timeframes: list[str] | None = None, *, lookback_bars: int = 0
    ) -> dict[str, Any]:
        """One image, several timeframes. Higher timeframes small, trading TF large."""
        ladder = [normalise(tf) for tf in (timeframes or ["1M", "1W", "1D"])]
        panels = []
        for position, timeframe in enumerate(ladder):
            bars = self.source.fetch(symbol, timeframe, bars=lookback_bars)
            # Context panels are small and unlabelled, so eight lines there is
            # a texture rather than information. The trading timeframe -- the
            # last in the ladder -- keeps the full budget.
            budget = 8 if position == len(ladder) - 1 else 4
            spec = compose_default(
                bars, compute_levels(bars), read_structure(bars),
                max_annotations=budget,
                created_by="multi-timeframe",
            )
            self.store.put(spec)
            panels.append((bars, spec))
        path = self.chart_dir / (
            f"{symbol.upper()}-{panels[-1][0].last_time.date().isoformat()}-MTF.png"
        )
        result = render_composite(panels, path=path, title=f"{symbol.upper()} — multi-timeframe")
        return {
            "ok": True,
            "image": str(result.path),
            "render_hash": result.render_hash,
            "specs": [spec.id for _, spec in panels],
            "ladder": [
                {"timeframe": spec.timeframe, "trend": spec.structure.trend,
                 "swing": spec.structure.swing}
                for _, spec in panels
            ],
        }

    def diff_spec(self, spec_id: str) -> dict[str, Any]:
        """*"Show me how that level held up."* Score an old spec against today.

        Only possible because specs are immutable. The chart re-rendered here is
        provably the analysis that was made at the time, not a reconstruction of
        what we would say about that date now.
        """
        spec = self._spec(spec_id)
        bars = self.source.fetch(spec.symbol, spec.timeframe)
        outcome = evaluate(spec, bars)
        if self.journal is not None:
            from genesis.journal.bridge import record_spec_outcome

            record_spec_outcome(self.journal, outcome)
        result = render(bars, spec, path=self._path(spec, suffix="-diff"))
        return {
            "ok": True, "image": str(result.path),
            "summary": outcome.summary(), **outcome.to_dict(),
        }

    def compile_pine(self, spec_id: str) -> dict[str, Any]:
        """A spec as a PineScript indicator, for the chart you look at all day."""
        spec = self._spec(spec_id)
        return {
            "ok": True, "spec": spec.id, "symbol": spec.symbol,
            "timeframe": spec.timeframe, "pine": compile_pine(spec),
        }

    # -- the analytics half ------------------------------------------------

    def render_analytics(self, spec: dict[str, Any]) -> dict[str, Any]:
        """A declared non-price chart — ranked bars, macro series, correlation.

        The argument is a whole :class:`AnalyticsSpec` as JSON, and that is the
        one place a payload rather than an id is correct: the *data* here is the
        answer to the question (eleven sector returns, eighty quarterly rate
        prints), it is small, and the agent that assembled it from primary
        sources is the only thing that knows what belongs on the chart.
        """
        parsed = AnalyticsSpec.model_validate(spec)
        path = self.chart_dir / f"{_slug(parsed.title)}.png"
        result = render_analytics(parsed, path=path)
        return {
            "ok": True, "image": str(result.path),
            "render_hash": result.render_hash, "form": parsed.form,
            "title": parsed.title,
        }

    # -- lineage -----------------------------------------------------------

    def lineage(self, spec_id: str) -> dict[str, Any]:
        chain = self.store.lineage(spec_id)
        return {
            "ok": True,
            "chain": [
                {
                    "spec": s.id, "as_of": s.as_of.isoformat(),
                    "trend": s.structure.trend,
                    "levels": [
                        {"label": level.label, "price": round(level.price, 4)}
                        for level in s.levels()
                    ],
                }
                for s in chain
            ],
        }

    # -- internals ---------------------------------------------------------

    def _spec(self, spec_id: str):
        spec = self.store.get(spec_id)
        if spec is None:
            raise GenesisError(f"no markup spec {spec_id!r}")
        return spec

    def _path(self, spec, suffix: str = "") -> Path:
        return self.chart_dir / (
            f"{spec.symbol}-{spec.as_of.date().isoformat()}-{spec.timeframe}{suffix}.png"
        )


def _spec_payload(spec, computation, structure) -> dict[str, Any]:
    return {
        "ok": True,
        "spec": spec.id,
        "parent": spec.parent,
        "symbol": spec.symbol,
        "timeframe": spec.timeframe,
        "as_of": spec.as_of.isoformat(),
        "image": spec.render.output,
        "render_hash": spec.render.render_hash,
        "spot": round(computation.spot, 4),
        "atr14": round(computation.atr, 4),
        "structure": structure.to_dict(),
        "annotations": [
            {
                "kind": a.kind, "label": a.label,
                "price": getattr(a, "price", None), "why": a.why,
                "strength": getattr(a, "strength", None),
                "confluence": list(getattr(a, "confluence", ()) or ()),
            }
            for a in spec.annotations
        ],
        "degraded": spec.degraded,
        "notes": list(computation.notes),
    }


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80] or "chart"


def build_server(service: ChartingService) -> Any:
    """Assemble the MCP server around a service. Testable without a transport."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="genesis-charting",
        instructions=(
            "Computes structural levels and renders charts from a Markup Spec. "
            "Takes symbols and spec ids, never bars. Prices returned here are "
            "computed from stored bars and are research-grade (tier 3): never "
            "use them to size a position or set a stop."
        ),
    )

    def _wrap(fn):
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return fn(*args, **kwargs)
            except GenesisError as exc:
                # A typed failure is information the caller can act on, and the
                # gateway already knows how to classify one. Never a guess and
                # never a silent empty chart.
                return {
                    "ok": False, "error": exc.reason,
                    "class": exc.failure_class, "retryable": exc.retryable,
                }
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    @server.tool()
    @_wrap
    def chart(symbol: str, timeframe: str = "1D", lookback_bars: int = 0) -> dict[str, Any]:
        """Mark up a symbol: compute levels, render a chart, store the spec."""
        return service.chart(symbol, timeframe, lookback_bars=lookback_bars)

    @server.tool()
    @_wrap
    def compute_levels(symbol: str, timeframe: str = "1D") -> dict[str, Any]:
        """Structural levels for a symbol, scored and merged. No chart."""
        return service.compute_levels(symbol, timeframe)

    @server.tool()
    @_wrap
    def structure(symbol: str, timeframe: str = "1D") -> dict[str, Any]:
        """Trend, swing sequence, range and volatility — measured, not judged."""
        return service.structure(symbol, timeframe)

    @server.tool()
    @_wrap
    def render_spec(spec_id: str) -> dict[str, Any]:
        """Re-render a stored markup spec to a PNG."""
        return service.render_spec(spec_id)

    @server.tool()
    @_wrap
    def render_composite(symbol: str, timeframes: list[str] | None = None) -> dict[str, Any]:
        """Several timeframes of one symbol as a single composite image."""
        return service.render_composite(symbol, timeframes)

    @server.tool()
    @_wrap
    def diff_spec(spec_id: str) -> dict[str, Any]:
        """Score an old spec against current price: which levels held."""
        return service.diff_spec(spec_id)

    @server.tool()
    @_wrap
    def compile_pine(spec_id: str) -> dict[str, Any]:
        """Compile a markup spec into a PineScript indicator."""
        return service.compile_pine(spec_id)

    @server.tool()
    @_wrap
    def render_analytics(spec: dict[str, Any]) -> dict[str, Any]:
        """Render a declared non-price chart: ranked bars, time series, heatmap."""
        return service.render_analytics(spec)

    @server.tool()
    @_wrap
    def lineage(spec_id: str) -> dict[str, Any]:
        """The parent chain of a spec — how a read of a symbol evolved."""
        return service.lineage(spec_id)

    return server


def main() -> None:  # pragma: no cover - process entry point
    """Entry point for ``genesis-charting-mcp``."""
    from genesis.charting.source import GatewayBarSource
    from genesis.mcp.build import build_gateway

    build = build_gateway()
    service = ChartingService(GatewayBarSource(build.gateway))
    build_server(service).run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
