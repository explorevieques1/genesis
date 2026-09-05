# Spec: Genesis Markdown/10-Architecture/Biological Design.md §3 Proprioception
"""What this system can actually do, discovered rather than declared.

`Biological Design` §3 says *proprioception before ambition*: never build an
actuator before the sense that verifies it acted, because the failure mode of a
system that acts without perceiving itself is drift between believed and actual
state — and that one loses money quietly.

A UI is a proprioceptive organ. Its whole job is to report the body's state,
and the most dangerous thing it can do is report an organ the body does not
have. That is exactly what happens when a front-end ships a "Backtest" page
with a plausible equity curve on it: everyone who looks at the screen now
believes there is a backtest engine.

So the surface does not decide what it can show. It asks. Every probe below
performs a **real check** — an import that either succeeds or raises, a file
that either exists or does not — and the page renders against the answer. A
capability reported ``built: false`` carries the spec note that describes it,
so the empty state can say *what* is missing and *where it is specified*
instead of spinning forever.

The rule this enforces: **there is no code path in the UI that can display a
number this module has not vouched for.**
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

__all__ = ["Capability", "probe_all", "CAPABILITIES"]


@dataclass(frozen=True)
class Capability:
    """One thing the system either can or cannot do.

    ``probe`` returns ``(built, detail)``. It must be cheap and must not raise
    — a probe that throws is itself a false negative about the system's state,
    which is the failure this module exists to prevent, so
    :func:`probe_all` catches and reports rather than propagating.
    """

    id: str
    label: str
    #: The organ this belongs to. Groups the UI's capability report and maps
    #: onto the families in `20-Agents/`.
    family: str
    #: The vault note that specifies it. Shown in the empty state, so a page
    #: that cannot render tells you where to read about what is missing.
    spec: str
    probe: Callable[[], tuple[bool, str]] = field(repr=False)


def _importable(module: str, attr: str | None = None) -> Callable[[], tuple[bool, str]]:
    """Built iff the module imports and optionally exposes ``attr``.

    An import is the honest test. A module listed in a config, referenced by a
    docstring, or named in a vault note proves nothing; a module that imports
    is code that exists on this disk right now.
    """
    def probe() -> tuple[bool, str]:
        try:
            mod = importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        if attr and not hasattr(mod, attr):
            return False, f"{module} has no {attr}"
        return True, module

    return probe


def _file(path: str, *, describe: str) -> Callable[[], tuple[bool, str]]:
    def probe() -> tuple[bool, str]:
        p = Path(path).expanduser()
        if not p.exists():
            return False, f"{describe} not created yet ({p})"
        size = p.stat().st_size
        return True, f"{p} ({size:,} bytes)"

    return probe


def _bars_present() -> tuple[bool, str]:
    """Market data is "built" only if there are bars, not just a schema.

    A store file with no rows is a different fact from a store with AAPL in
    it, and a chart page needs to tell them apart before it decides whether to
    say "no data yet" or draw.
    """
    try:
        from genesis.marketdata.store import BarStore

        store = BarStore(read_only=True)
        try:
            rows = store.symbols()
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if not rows:
        return False, "bar store exists but holds no series"
    total = sum(count for _, _, count in rows)
    return True, f"{len(rows)} series, {total:,} bars"


def _backtest_ready() -> tuple[bool, str]:
    """The engine is Nautilus, so both halves must be present.

    Checking only Genesis' own adapter would report the capability as built on
    a machine where `nautilus_trader` is missing, and the page would then render
    a run button that always 503s. The version is reported because a report is
    only reproducible against the engine that produced it.
    """
    try:
        import nautilus_trader
    except Exception as exc:  # noqa: BLE001
        return False, f"nautilus_trader not installed: {exc}"
    try:
        importlib.import_module("genesis.backtest.runner")
    except Exception as exc:  # noqa: BLE001
        return False, f"adapter unavailable: {type(exc).__name__}: {exc}"
    return True, f"nautilus_trader {nautilus_trader.__version__}"


def _voice_stt() -> tuple[bool, str]:
    """Local transcription needs the model package, not just our wrapper."""
    try:
        importlib.import_module("faster_whisper")
    except Exception as exc:  # noqa: BLE001
        return False, f"faster-whisper not installed: {exc}"
    return True, "faster-whisper (tiny.en, local)"


#: Every capability the surface may ask about. Adding a page means adding a
#: probe here first — that ordering is the point, not bureaucracy.
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "marketdata.bars", "Historical bars", "data",
        "10-Architecture/Market Data Plane.md", _bars_present,
    ),
    Capability(
        "marketdata.realtime", "Realtime quotes", "data",
        "10-Architecture/Market Data Sources.md",
        # Deliberately a hard false: there is no streaming adapter wired, and
        # a chart that animates a last price it does not have is the single
        # most misleading thing this UI could do.
        lambda: (False, "no streaming adapter is wired; bars are historical only"),
    ),
    Capability(
        "company.profiles", "Company fundamentals", "data",
        "10-Architecture/Company Data Model.md",
        _importable("genesis.company.profile", "resolve"),
    ),
    Capability(
        "charting.render", "Chart rendering", "charting",
        "10-Architecture/Charting Engine.md",
        _importable("genesis.charting.render"),
    ),
    Capability(
        "charting.markup", "Chart markup specs", "charting",
        "10-Architecture/Markup Spec.md",
        _importable("genesis.charting.store", "SpecStore"),
    ),
    Capability(
        "charting.analytics", "Analytics renders", "charting",
        "10-Architecture/Charting Engine.md",
        _importable("genesis.charting.analytics", "render_analytics"),
    ),
    Capability(
        "journal.store", "Trade journal", "journal",
        "20-Agents/Journal/Agent — Trade Journal.md",
        _file("~/.genesis/memory/journal.db", describe="journal database"),
    ),
    Capability(
        "journal.patterns", "Behavioural patterns", "journal",
        "20-Agents/Journal/Agent — Insight Miner.md",
        _importable("genesis.journal.patterns", "detect_all"),
    ),
    Capability(
        "journal.drift", "Backtest-vs-live drift", "journal",
        "20-Agents/Journal/Agent — Backtest Vs Live Drift.md",
        _importable("genesis.journal.drift", "compare"),
    ),
    Capability(
        "metrics.core", "Performance metrics", "journal",
        "20-Agents/Journal/Agent — Performance Analyst.md",
        _importable("genesis.metrics.core", "summarize"),
    ),
    Capability(
        "backtest.engine", "Backtest engine", "strategy",
        "20-Agents/Strategy/Agent — Backtest Runner.md", _backtest_ready,
    ),
    Capability(
        "backtest.store", "Backtest history", "strategy",
        "20-Agents/Strategy/Agent — Backtest Runner.md",
        _file("~/.genesis/memory/backtest.db", describe="backtest history"),
    ),
    Capability(
        "mcp.gateway", "MCP tool gateway", "tools",
        "30-MCP/MCP Gateway.md",
        _importable("genesis.mcp.gateway"),
    ),
    Capability(
        "orchestrator.planner", "Planner", "core",
        "10-Architecture/Orchestrator.md",
        _importable("genesis.orchestrator.planner"),
    ),
    Capability(
        "memory.working", "Working memory", "memory",
        "40-Memory/Working Memory.md",
        _importable("genesis.memory.working", "WorkingMemory"),
    ),
    Capability(
        "memory.episodic", "Episodic memory", "memory",
        "40-Memory/Memory Fabric.md",
        _importable("genesis.memory.episodic"),
    ),
    Capability(
        "voice.stt", "Speech to text", "voice",
        "10-Architecture/Voice Stack.md", _voice_stt,
    ),
    Capability(
        "voice.tts", "Text to speech", "voice",
        "10-Architecture/Voice Stack.md",
        _importable("genesis.voice.tts"),
    ),
    Capability(
        "risk.pretrade", "Pre-trade risk engine", "risk",
        "50-Risk/Pre-Trade Risk Engine.md",
        # No module, and that is correct for this phase. Reported loudly
        # because Safety Invariants #1 means no order surface may exist until
        # this is true -- the UI reads this flag to keep the execution page
        # structurally unreachable rather than merely hidden.
        _importable("genesis.risk.pretrade"),
    ),
    Capability(
        "execution.broker", "Broker execution", "execution",
        "50-Risk/Safety Invariants.md",
        _importable("genesis.execution.broker"),
    ),
    Capability(
        "automation.workflows", "Automation workflows", "automation",
        "60-UI/Automation.md",
        _importable("genesis.automation.workflow"),
    ),
    Capability(
        "research.canvas", "Research canvas", "research",
        "60-UI/Research Canvas.md",
        _importable("genesis.research.canvas"),
    ),
)


def probe_all() -> dict[str, Any]:
    """Run every probe. Never raises.

    Returns a body shaped for the UI's capability store: a flat map keyed by
    id, plus the family grouping the settings page renders.
    """
    out: dict[str, Any] = {}
    for cap in CAPABILITIES:
        try:
            built, detail = cap.probe()
        except Exception as exc:  # noqa: BLE001
            built, detail = False, f"probe failed: {type(exc).__name__}: {exc}"
        out[cap.id] = {
            "id": cap.id,
            "label": cap.label,
            "family": cap.family,
            "spec": cap.spec,
            "built": bool(built),
            "detail": detail,
        }

    families: dict[str, list[str]] = {}
    for cap in CAPABILITIES:
        families.setdefault(cap.family, []).append(cap.id)

    built_count = sum(1 for v in out.values() if v["built"])
    return {
        "capabilities": out,
        "families": families,
        "built": built_count,
        "total": len(out),
    }
