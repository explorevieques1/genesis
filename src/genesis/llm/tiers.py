# Spec: Genesis Markdown/10-Architecture/LLM Model Tiers.md
"""Changing which model serves a tier.

One function, two callers -- the settings panel and ``genesis config set-tier``.
Operating Model's parity rule is the reason it is written this way round:
*"anything Genesis can do, a person can do by hand, through the same door, with
the same audit line."* A tier switch reachable only from a React panel is not
shipped.

**A tier change takes effect on daemon restart, and the return value says so.**
The fleets bind their backends once at construction (``cli._tier_backend``), so
nothing already running swaps model mid-flight. That is reported rather than
hidden: a toggle whose effect is invisible until some later restart, with no
indication of that, is the control-that-does-nothing this codebase keeps
refusing to ship.

**The write is validated by loading it back.** The new YAML is merged and run
through :class:`~genesis.config.Config` before it is saved, so a bad model
string fails here rather than at 04:00 when the daemon will not start.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genesis.config import (
    DEFAULT_CONFIG_PATH,
    LLM_BACKENDS,
    ConfigError,
    load_config,
)

__all__ = [
    "TIERS",
    "TierBuild",
    "TierChange",
    "budget",
    "build_tier",
    "set_tier",
    "usage_log",
]

_USAGE_LOG: Any = None
_BUDGET: Any = None


def usage_log(config: Any):  # noqa: ANN001, ANN201
    """The shared meter. One per process -- every tier writes to one table."""
    global _USAGE_LOG
    if _USAGE_LOG is None:
        from genesis.llm.usage import UsageLog

        _USAGE_LOG = UsageLog(config.memory.db_path)
    return _USAGE_LOG


def budget(config: Any):  # noqa: ANN001, ANN201
    """The day's token ceiling. One per process, shared by every tier.

    Per-tier budgets would let the large tier eat the day and leave the small
    tier a number it can never reach; the ceiling is a property of the day.
    """
    global _BUDGET
    if _BUDGET is None:
        from genesis.llm.usage import Budget

        _BUDGET = Budget(
            usage_log(config), daily_tokens=config.llm.daily_token_budget
        )
    return _BUDGET


@dataclass(frozen=True)
class TierBuild:
    """One tier, built or not, and why not.

    ``note`` is phrased for a person and is never empty when ``backend`` is
    ``None`` for a reason worth reporting. ``refused`` separates *"the guard
    said no"* from *"the key is missing"*: the first is a decision the operator
    made and must see loudly, the second is a degradation.
    """

    backend: Any = None
    note: str | None = None
    refused: bool = False


def build_tier(config: Any, tier_name: str) -> TierBuild:  # noqa: ANN001
    """Construct one model tier, metered. Never raises; a failure is a note.

    **One builder, every caller.** This used to live in ``cli._tier_backend``
    and nowhere else, so the CLI learned about ``gemini``, ``groq``,
    ``openrouter`` and ``ollama`` while :func:`~genesis.orchestrator.build.build_ladder`
    -- which is what the terminal and [[Ask Genesis]] actually talk to -- still
    knew only ``anthropic`` and answered *"large tier backend 'gemini' is not
    wired yet"*. A free provider that worked on the command line and not in the
    chat box is precisely the drift Operating Model §1 is written against, and
    two copies of this function is how it happened.

    A tier this cannot build is ``None``, which every fleet and every rung
    already treats as a documented degraded mode.
    """
    tier = getattr(config.llm, tier_name)
    if tier.backend == "none" or not tier.model:
        return TierBuild()

    from genesis.errors import DegradedError
    from genesis.llm.openai_compat import PROVIDERS, is_dev_only
    from genesis.llm.usage import MeteredBackend

    # A free tier that trains on its prompts must never see a live account.
    # Structural, not advisory: "remember to switch the config back" is exactly
    # the instruction a reflex exists to replace.
    if config.is_live and is_dev_only(tier.backend):
        return TierBuild(
            note=(
                f"{tier_name} tier is {tier.backend}, which is development-only, "
                f"and the broker is live -- refusing to build it"
            ),
            refused=True,
        )

    try:
        if tier.backend == "anthropic":
            from genesis.llm.anthropic_backend import AnthropicBackend

            inner = AnthropicBackend(tier.model)
        elif tier.backend == "ollama":
            from genesis.llm.backend import OllamaBackend

            inner = OllamaBackend(tier.model)
        elif tier.backend in PROVIDERS:
            from genesis.llm.openai_compat import OpenAICompatBackend

            inner = OpenAICompatBackend(tier.model, provider=tier.backend)
        else:
            return TierBuild(
                note=f"{tier_name} tier: unknown backend {tier.backend!r} -- tier is offline"
            )
    except DegradedError as exc:
        return TierBuild(note=f"{tier_name} tier unavailable: {exc.reason}")

    return TierBuild(
        MeteredBackend(
            inner,
            tier=tier_name,
            backend=tier.backend,
            log=usage_log(config),
            budget=budget(config),
        )
    )


#: ``nano`` is absent deliberately. Open Questions §4: intent classification is
#: deterministic code, not a model tier, and offering a model picker for it
#: would invite putting one back on the hot path.
TIERS = ("small", "large", "vision", "embedding")


@dataclass(frozen=True)
class TierChange:
    tier: str
    backend: str
    model: str
    path: Path
    previous_backend: str
    previous_model: str
    restart_required: bool = True

    @property
    def changed(self) -> bool:
        return (self.backend, self.model) != (self.previous_backend, self.previous_model)


def set_tier(
    tier: str,
    backend: str,
    model: str,
    *,
    path: Path | None = None,
) -> TierChange:
    """Point one tier at one model. Raises :class:`ConfigError` on bad input."""
    import yaml

    if tier not in TIERS:
        raise ConfigError(f"unknown tier {tier!r}; expected one of: {', '.join(TIERS)}")
    if backend not in LLM_BACKENDS:
        known = ", ".join(sorted(LLM_BACKENDS))
        raise ConfigError(f"unknown backend {backend!r}; expected one of: {known}")
    if backend != "none" and not model.strip():
        raise ConfigError(f"backend {backend!r} needs a model name")

    target = (path or DEFAULT_CONFIG_PATH).expanduser()
    before = getattr(load_config().llm, tier)

    # Read the *user* layer only. Merging the packaged defaults in and writing
    # the result back would freeze today's shipped values into the user's file,
    # so a later upgrade to a default would silently not apply.
    existing: dict[str, Any] = {}
    if target.is_file():
        existing = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    llm = dict(existing.get("llm") or {})
    llm[tier] = {"backend": backend, "model": model.strip()}
    existing["llm"] = llm

    # Validate before writing: load_config merges over the packaged defaults,
    # which is the same stack the daemon will see.
    scratch = target.with_suffix(target.suffix + ".tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
    try:
        load_config(scratch)
    except ConfigError:
        scratch.unlink(missing_ok=True)
        raise
    # Atomic: a half-written config file is a daemon that will not start.
    scratch.replace(target)

    return TierChange(
        tier=tier,
        backend=backend,
        model=model.strip(),
        path=target,
        previous_backend=before.backend,
        previous_model=before.model,
    )
