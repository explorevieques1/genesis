# Spec: Genesis Markdown/50-Risk/Safety Invariants.md §1, §12
"""A workflow step cannot reach an order path -- by import graph, not by string.

Every automation module is imported in a clean interpreter, and then the set of
modules actually loaded is inspected. If anything in the chain pulls in
execution or risk code, it is in ``sys.modules`` and this fails.
"""

from __future__ import annotations

import json
import subprocess
import sys

from genesis.automation.grant import WORKFLOW_GRANT

FORBIDDEN = ("genesis.execution", "genesis.risk", "genesis.marketdata.ibkr_live",
             "genesis.server.broker_routes")

MODULES = ("genesis.automation", "genesis.automation.grant", "genesis.automation.workflow",
           "genesis.automation.store", "genesis.automation.runner", "genesis.automation.actions",
           "genesis.automation.catalog")


def test_automation_imports_no_order_path() -> None:
    script = (
        "import importlib, json, sys\n"
        f"for m in {MODULES!r}: importlib.import_module(m)\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                         check=True, timeout=60)
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    reached = [m for m in loaded if m.startswith(FORBIDDEN)]
    assert reached == [], f"automation reaches an order path through {reached}"


def test_the_grant_holds_no_execution_namespace() -> None:
    assert not [p for p in WORKFLOW_GRANT if "execution" in p or p.startswith("broker")]
