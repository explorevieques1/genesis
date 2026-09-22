# Spec: Genesis Markdown/60-UI/Automation.md §Q2
"""What a workflow step may call. Read namespaces only.

A workflow has no invoking agent, so it cannot inherit one's allow-list. It
holds this grant and nothing more. Widening it is a code change reviewed in a
diff -- which is what makes a workflow stored as data acceptable at all.

Enforced twice: :func:`genesis.automation.workflow.Workflow` refuses a ``gather``
outside it at save, and the compiled declaration's ``tools`` are bound by the
gateway's own :class:`~genesis.mcp.allowlist.AllowList` at run.

Every entry is a read. Where a namespace mixes reads and writes it is granted
capability by capability instead: ``genesis-charting.render`` writes files and
``papers.download`` writes to disk, so neither is here.
"""

from __future__ import annotations

from genesis.mcp.allowlist import matches

__all__ = ["WORKFLOW_GRANT", "permits"]

WORKFLOW_GRANT: tuple[str, ...] = (
    "news.*",
    "market-data.*",
    "fundamentals.*",
    "analyst.*",
    "corporate.*",
    "calendar.*",
    "screen.*",
    "ta.*",
    "analytics.*",
    "filings.*",
    "macro.*",
    "research.*",
    "web.search",
    "web.read",
    "papers.search",
    "papers.abstract",
    "genesis-charting.compute_levels",
    "genesis-charting.structure",
)


def permits(capability: str) -> bool:
    return any(matches(pattern, capability) for pattern in WORKFLOW_GRANT)
