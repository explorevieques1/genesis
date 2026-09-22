# Spec: Genesis Markdown/30-MCP/MCP Gateway.md
"""A tripwire for a name collision that would be miserable to debug.

Three things named ``mcp`` are in play: the upstream SDK, ``genesis.mcp``, and
this test directory. ``tests`` is on the pytest pythonpath ahead of
site-packages, so if ``tests/mcp/`` ever gains an ``__init__.py`` -- or Python
resolves it as a namespace package -- a bare ``import mcp`` finds the tests
instead of the SDK, and ``genesis.mcp.transports`` silently imports nothing
useful. The symptom would appear far from the cause.
"""

from __future__ import annotations


def test_the_sdk_is_not_shadowed_by_the_test_directory() -> None:
    import mcp

    assert "site-packages" in (mcp.__file__ or ""), (
        f"`import mcp` resolved to {mcp.__file__} — the test directory is "
        f"shadowing the SDK"
    )
