# Spec: Genesis Markdown/10-Architecture/Agent Contract.md · 20-Agents/Agent Index.md
"""The fleet, discovered rather than listed.

Every agent module declares itself at module scope::

    DECLARATION = AgentDeclaration(id="watchdog", family="journal", ...)

This walks the ``genesis.agents`` packages and collects those. The result is
the fleet **as code**, which is the only roster that cannot lie.

That distinction is the reason this module exists. The front-end previously
carried its own roster — 25 agents hand-written in TypeScript, drawn from the
vault's agent index. Thirteen of them existed. The surface therefore drew a
body map of an organism with twelve phantom limbs, and every one of them
rendered as `idle` rather than `absent`, because a list has no way to express
the difference between "this agent is quiet" and "this agent was never built".

`Biological Design` §3 has a name for that: proprioceptive drift, *"the system
will then reason confidently about itself and be wrong"*. A roster derived by
import cannot drift. Delete an agent's module and it leaves the map in the same
commit.

The vault's declared-but-unbuilt agents are not hidden — they are reported
separately, with ``built: false``, so the UI can show the whole intended
organism while being unambiguous about which parts of it have tissue.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["discover_agents", "AGENT_PACKAGES"]

#: Where agent modules live. A new family is a new entry here — and the fact
#: that adding one is a code change rather than a config edit is deliberate:
#: the fleet is structure, not preference.
AGENT_PACKAGES: tuple[str, ...] = (
    "genesis.agents.charting",
    "genesis.agents.journal",
)


def discover_agents() -> list[dict[str, Any]]:
    """Every agent whose module imports, as plain dicts.

    Import failures are **reported, not swallowed**. An agent that fails to
    import is a down organ, and a surface that silently omits it would show a
    healthy fleet with a missing member — the exact failure this module is
    written to prevent. It appears with ``built: false`` and the exception
    text, which is what a person needs to fix it.
    """
    agents: list[dict[str, Any]] = []
    seen: set[str] = set()

    for package_name in AGENT_PACKAGES:
        try:
            package = importlib.import_module(package_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("agent package %s failed to import: %s", package_name, exc)
            agents.append({
                "id": package_name.rsplit(".", 1)[-1],
                "name": package_name,
                "family": "unknown",
                "built": False,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        for info in pkgutil.iter_modules(package.__path__):
            # `fleet.py` assembles a family; it is wiring, not an agent, and
            # it has no DECLARATION. Skipped by name rather than by a failed
            # getattr so the absence is intentional rather than incidental.
            if info.name.startswith("_") or info.name == "fleet":
                continue
            module_name = f"{package_name}.{info.name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001
                log.warning("agent module %s failed to import: %s", module_name, exc)
                agents.append({
                    "id": info.name, "name": info.name,
                    "family": package_name.rsplit(".", 1)[-1],
                    "module": module_name, "built": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            declaration = getattr(module, "DECLARATION", None)
            if declaration is None:
                continue
            record = _describe(declaration, module_name)
            if record["id"] in seen:
                continue
            seen.add(record["id"])
            agents.append(record)

    agents.sort(key=lambda a: (a.get("family", ""), a.get("id", "")))
    return agents


def _describe(declaration: Any, module_name: str) -> dict[str, Any]:
    """One ``AgentDeclaration`` flattened for the wire.

    ``reflex`` is derived here rather than left to the front-end. Biological
    Design §1 makes ``model_tier == "none"`` mean *spinal cord* — deterministic,
    incapable of hallucinating — and that is a fact about the agent, not a
    rendering choice. Computing it server-side means every surface that draws
    the fleet agrees about which parts of it can be talked out of firing.
    """
    data = declaration.model_dump(mode="python") if hasattr(declaration, "model_dump") else {}
    tier = data.get("model_tier", "none")
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "family": data.get("family"),
        "module": module_name,
        "built": True,
        "model_tier": tier,
        # The reflex arc, as a boolean the UI can style on.
        "reflex": tier == "none",
        "vision": bool(data.get("vision")),
        "cadence": data.get("cadence") or [],
        "tools": list(data.get("tools") or []),
        "memory": data.get("memory") or {},
        "timeout_sec": data.get("timeout_sec"),
        "max_concurrent": data.get("max_concurrent"),
    }
