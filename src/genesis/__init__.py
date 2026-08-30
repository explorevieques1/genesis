# Spec: Genesis Markdown/Genesis Agent — Home.md
"""Genesis Agent -- a voice-driven, multi-agent autonomous trading system.

The specification lives in ``Genesis Markdown/``, an Obsidian vault. It is the
source of truth: if this code and its note disagree, the code is wrong, or the
design changed and the note must change with it in the same commit.

Phase 0 ships scaffolding only -- config, logging, CLI. No daemon, no task bus,
no agents, no broker. See ``00-Meta/Build Order.md``.
"""

__version__ = "0.0.1"
__all__ = ["__version__"]
