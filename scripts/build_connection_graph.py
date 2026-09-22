#!/usr/bin/env python3
# Spec: Genesis Markdown/90-Graph/Connection Graph.md
"""Regenerate `Genesis Markdown/90-Graph/` — agents, tools and modules as links.

Obsidian's graph view draws a line for every wikilink, so the graph is just
notes: one per UI module, one per tool namespace, each linking to the agents
behind it. The agent notes are untouched — graph edges are undirected.

Sources, so the graph cannot drift from the thing it draws:
  modules      ui/src/workspace/modules.ts           (parsed)
  agent→tool   `## Tools` section of every agent note (parsed)
  module→agent MODULE_LINKS below                     (hand-kept: the UI declares none)

Run after adding a module, an agent, or a tool:

    python3 scripts/build_connection_graph.py
"""

import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "Genesis Markdown"
OUT = VAULT / "90-Graph"
MODULES_TS = ROOT / "ui/src/workspace/modules.ts"

# ponytail: memory.* and taskbus.* are the Memory Fabric and Task Bus, not tools —
# nearly every agent holds them, so as nodes they collapse the graph into one hub.
SKIP_NS = {"memory", "taskbus"}

# Tool namespaces that have a server note of their own.
SERVER_NOTE = {
    "genesis-charting": "genesis-charting-mcp",
    "genesis-backtest": "genesis-backtest-mcp",
    "genesis-execution": "genesis-execution-mcp",
    "tradingview": "genesis-tradingview-mcp",
}

A = "Agent — "
# module id → (agents / organs it shows, tool namespaces it reaches, its UI or design note)
MODULE_LINKS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "chart": ([A + "Chart Markup", A + "Level Watcher"], ["market-data", "genesis-charting"], ["Chart Tools"]),
    "watchlist": ([], ["market-data"], ["Market Data Plane"]),
    "watchlist-manager": ([], ["tradingview"], ["Watchlist Store"]),
    "candle-ranges": ([], ["market-data"], ["Candle Ranges"]),
    "symbol-detail": ([], ["market-data"], ["Company Data Model"]),
    "coverage": ([], ["market-data"], ["Market Data Plane"]),
    "markup-specs": ([A + "Chart Markup", A + "Pattern Recognition", A + "Multi Timeframe"], ["genesis-charting"], ["Markup Spec"]),
    "heatmap": ([], ["market-data"], ["Dashboard"]),
    "performance": ([A + "Data Viz"], ["market-data"], ["Dashboard"]),
    "tradingview": ([], ["tradingview"], ["genesis-tradingview-mcp"]),
    "backtest-runner": ([A + "Backtest Runner"], ["genesis-backtest"], ["Strategy Schema"]),
    "backtest-equity": ([A + "Backtest Runner"], ["genesis-backtest"], []),
    "backtest-stats": ([A + "Backtest Runner", A + "Risk Metrics"], ["genesis-backtest"], []),
    "backtest-trades": ([A + "Backtest Runner"], ["genesis-backtest"], []),
    "backtest-history": ([A + "Backtest Runner"], ["genesis-backtest"], []),
    "research-canvas": ([A + "Topic Researcher", A + "Idea Synthesizer"], [], ["Research Canvas"]),
    "research-directory": ([A + "Topic Researcher", A + "Market Analyst", A + "Idea Synthesizer"], [], ["Research Directory"]),
    "research-note": ([A + "Topic Researcher"], ["web"], ["Research Directory"]),
    "company-profile": ([A + "Fundamental"], ["filings"], ["Company Data Model"]),
    "tool-surface": ([], ["*"], ["MCP Gateway"]),
    "journal-graph": ([A + "Trade Journal", A + "Insight Miner"], [], ["Trade Journal Schema"]),
    "journal-entries": ([A + "Trade Journal"], [], ["Trade Journal Schema"]),
    "journal-patterns": ([A + "Insight Miner"], [], []),
    "notebook": ([], ["obsidian"], ["Notebook"]),
    "notebook-graph": ([], ["obsidian"], ["Nodes"]),
    "cadence": ([A + "Watchdog", A + "Digest"], ["time"], ["Automation"]),
    "workflow-builder": ([], [], ["Automation", "Orchestrator"]),
    "body-map": ([], [], ["Fleet View", "Agent Index", "Biological Design"]),
    "agent-inspector": ([], [], ["Fleet View", "Agent Index", "Agent Contract"]),
    "event-stream": ([], [], ["Fleet View", "Event Schema"]),
    "memory-fabric": ([], [], ["Memory Fabric"]),
    "execution-path": (["Pre-Trade Risk Engine", A + "Order Manager"], ["genesis-execution"], ["Fleet View"]),
    "trace": ([], [], ["Fleet View", "Orchestrator"]),
    "capability-map": ([], [], ["Vault Map"]),
    "ask-genesis": ([], [], ["Ask Genesis", "Orchestrator"]),
    "status": ([A + "Watchdog"], [], ["Observability"]),
    "task-manager": ([], [], ["Task Manager", "Task Bus"]),
    "help": ([], [], ["Terminal"]),
    "settings-audio": ([], [], ["Voice UX"]),
    "settings-agents": ([], [], ["Agent Index", "Agent Contract"]),
    "settings-data": ([], ["market-data"], ["Market Data Sources"]),
    "settings-approval": (["Pre-Trade Risk Engine"], [], ["Approval Modes"]),
    "settings-models": ([], [], ["LLM Model Tiers"]),
}

MODULE_RE = re.compile(
    r"\{ id: '([^']+)', code: '([^']+)', title: '([^']+)', home: '([^']+)'.*?hint: (['\"])(.*?)\5 \}"
)
FAMILY = {"Research": "research", "Charting": "charting", "Strategy": "strategy",
          "Execution": "execution", "Journal": "journal"}


def status_of(text: str) -> str:
    m = re.search(r"\A---\n.*?^status:\s*(\S+)", text, re.DOTALL | re.MULTILINE)
    return m.group(1) if m else "spec"


def main() -> int:
    names = {p.stem for p in VAULT.rglob("*.md") if OUT not in p.parents}

    modules = [m.groups() for m in MODULE_RE.finditer(MODULES_TS.read_text())]
    ids = {m[0] for m in modules}
    if ids != set(MODULE_LINKS):
        print(f"MODULE_LINKS out of sync with modules.ts: "
              f"missing {sorted(ids - set(MODULE_LINKS))}, stale {sorted(set(MODULE_LINKS) - ids)}")
        return 1

    # agent → tool namespaces, from the spec
    tools: dict[str, set[str]] = defaultdict(set)   # namespace → agents
    status: dict[str, str] = {}
    for path in sorted((VAULT / "20-Agents").glob("*/Agent — *.md")):
        text = path.read_text()
        status[path.stem] = status_of(text)
        section = re.search(r"^## Tools\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
        for cap in re.findall(r"`([a-z0-9_-]+)\.[a-z0-9_*.-]+`", section.group(1) if section else ""):
            if cap not in SKIP_NS:
                tools[cap].add(path.stem)
    for _, ns, _ in MODULE_LINKS.values():
        for n in ns:
            if n != "*":
                tools.setdefault(n, set())

    missing = {t for a, _, n in MODULE_LINKS.values() for t in a + n if t not in names}
    missing |= {s for s in SERVER_NOTE.values() if s not in names}
    if missing:
        print(f"unresolved wikilinks: {sorted(missing)}")
        return 1

    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "Modules").mkdir(parents=True)
    (OUT / "Tools").mkdir()

    def module_note(code: str, title: str) -> str:
        return f"Module {code} — {title}"

    def tool_note(ns: str) -> str:
        return f"Tool — {ns}"

    def link(n: str) -> str:
        return f"[[{n}]]"

    def with_status(agent: str) -> str:
        return f"[[{agent}]] ({status.get(agent, 'built')})"

    tool_modules: dict[str, list[str]] = defaultdict(list)
    for mid, code, title, home, _, hint in modules:
        agents, nss, notes = MODULE_LINKS[mid]
        nss = sorted(tools) if nss == ["*"] else nss
        for n in nss:
            tool_modules[n].append(module_note(code, title))
        body = [
            "---", f"title: {module_note(code, title)}", "tags: [graph, module]",
            f"module: {mid}", f"home: {home}", "---", "",
            f"# `{code}` {title}", "", hint, "",
            f"Opens with `{code}` · home page **{home}** · [[Connection Graph]]", "",
            "## Agents", "", *([f"- {with_status(a)}" for a in agents] or ["- none — reads a store directly"]), "",
            "## Tools", "", *([f"- {link(tool_note(n))}" for n in nss] or ["- none"]), "",
            "## Spec", "", *([f"- {link(n)}" for n in notes] or ["- none"]), "",
        ]
        (OUT / "Modules" / f"{module_note(code, title)}.md").write_text("\n".join(body))

    for ns in sorted(tools):
        server = SERVER_NOTE.get(ns)
        body = [
            "---", f"title: {tool_note(ns)}", "tags: [graph, tool]", "---", "",
            f"# `{ns}.*`", "",
            (f"Served by {link(server)} · " if server else "") + "[[Connection Graph]]", "",
            "## Agents that hold it", "",
            *([f"- {with_status(a)}" for a in sorted(tools[ns])] or ["- none"]), "",
            "## Modules that reach it", "",
            *([f"- {link(m)}" for m in sorted(tool_modules[ns])] or ["- none"]), "",
        ]
        (OUT / "Tools" / f"{tool_note(ns)}.md").write_text("\n".join(body))

    orphans = sorted(a for a in status
                     if not any(a in ag for ag, _, _ in MODULE_LINKS.values()))
    hub = [
        "---", "title: Connection Graph", "tags: [graph, moc]", "status: built",
        "implemented_by: [scripts/build_connection_graph.py]", "---", "",
        "# Connection Graph", "",
        "How agents, tools and UI modules connect. **Generated** by",
        "`python3 scripts/build_connection_graph.py` — do not edit these notes by hand;",
        "change `ui/src/workspace/modules.ts`, an agent's `## Tools` section, or",
        "`MODULE_LINKS` in the script, then re-run.", "",
        "Open the graph view and filter with `path:90-Graph OR path:20-Agents` to see",
        "only the connection graph. Colours: modules blue, tools amber, agents green.", "",
        "`memory.*` and `taskbus.*` are left out on purpose: almost every agent holds",
        "them, so they would pull the whole graph into one hub. See [[Memory Fabric]]",
        "and [[Task Bus]].", "",
        f"## Modules ({len(modules)})", "",
        *[f"- {link(module_note(c, t))}" for _, c, t, *_ in modules], "",
        f"## Tools ({len(tools)})", "",
        *[f"- {link(tool_note(n))}" for n in sorted(tools)], "",
        f"## Agents with no module yet ({len(orphans)})", "",
        "Reachable only through Ask Genesis or the orchestrator — parity-rule gaps",
        "([[Operating Model]]).", "",
        *[f"- {with_status(a)}" for a in orphans], "",
        "## Related", "", "[[Agent Index]] · [[MCP Server Catalog]] · [[Workspaces]]", "",
    ]
    (OUT / "Connection Graph.md").write_text("\n".join(hub))
    print(f"wrote {len(modules)} modules, {len(tools)} tools, {len(orphans)} agents with no module")
    return 0


if __name__ == "__main__":
    sys.exit(main())
