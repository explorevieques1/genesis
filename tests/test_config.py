# Spec: Genesis Markdown/10-Architecture/Config And Secrets.md
"""The config stack must load, and must refuse to start on nonsense.

*"A system that boots with a nonsense risk limit is worse than one that refuses
to boot."* -- Config And Secrets.md. These tests are that sentence, executable.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from genesis.config import (
    SECRET_ENV_VARS,
    Config,
    ConfigError,
    Secrets,
    default_config_text,
    load_config,
    load_secrets,
)

MONEY_KEYS = (
    "max_position_pct",
    "max_portfolio_heat_pct",
    "max_daily_loss_pct",
    "max_correlated_exposure_pct",
)


@pytest.fixture
def defaults() -> Config:
    """The shipped defaults, with no user config file in the stack."""
    return load_config(None)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Layer 1 -- the shipped defaults stand on their own
# --------------------------------------------------------------------------


def test_shipped_defaults_load(defaults: Config) -> None:
    assert defaults.identity.wake_word == "genesis"
    assert defaults.brokers.primary.kind == "alpaca"
    assert defaults.memory.consolidation_hour == 21


def test_default_approval_mode_is_confirm(defaults: Config) -> None:
    """Hard rule: never ship a default that trades unattended.

    See Safety Invariants and CLAUDE.md rule 5. `advisory` is only the rollout
    starting point for the execution MCP, not the system-wide default.
    """
    assert defaults.approval.mode == "confirm"


def test_default_broker_mode_is_paper(defaults: Config) -> None:
    assert defaults.brokers.primary.mode == "paper"
    assert defaults.is_live is False


def test_user_paths_are_expanded(defaults: Config) -> None:
    assert not str(defaults.memory.vault_path).startswith("~")
    assert defaults.memory.vault_path.is_absolute()


# --------------------------------------------------------------------------
# Money is Decimal, never float
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", MONEY_KEYS)
def test_risk_limits_are_decimal(defaults: Config, key: str) -> None:
    assert isinstance(getattr(defaults.risk, key), Decimal)


def test_decimal_comes_from_text_not_float(tmp_path: Path) -> None:
    """`Decimal("0.1")` is exactly 0.1; `Decimal(0.1)` is not.

    Parsing via float first would lose the value before any model could protect
    it, so the YAML loader constructs Decimal from the raw scalar text.
    """
    path = write(tmp_path, "risk:\n  max_daily_loss_pct: 0.1\n")
    value = load_config(path).risk.max_daily_loss_pct
    assert value == Decimal("0.1")
    assert str(value) == "0.1"
    assert value != Decimal(0.1)


# --------------------------------------------------------------------------
# Layer 2 -- the user file overrides, and merges without restating siblings
# --------------------------------------------------------------------------


def test_user_file_overrides_default(tmp_path: Path) -> None:
    path = write(tmp_path, "identity:\n  wake_word: atlas\n")
    assert load_config(path).identity.wake_word == "atlas"


def test_merge_is_deep_and_leaves_siblings_alone(tmp_path: Path) -> None:
    path = write(tmp_path, "risk:\n  max_daily_loss_pct: 1.0\n")
    risk = load_config(path).risk
    assert risk.max_daily_loss_pct == Decimal("1.0")
    assert risk.max_position_pct == Decimal("5.0")  # untouched sibling
    assert risk.symbol_allowlist == ["NVDA", "AMD", "AVGO", "SPY", "QQQ"]


def test_missing_user_file_is_not_an_error(tmp_path: Path) -> None:
    assert load_config(tmp_path / "absent.yaml").approval.mode == "confirm"


# --------------------------------------------------------------------------
# Refuse to start, and say exactly which key is wrong
# --------------------------------------------------------------------------


def test_rejects_nonsense_risk_limit(tmp_path: Path) -> None:
    """A daily loss limit of 150% is not a tight config -- it is a broken one."""
    path = write(tmp_path, "risk:\n  max_daily_loss_pct: 150.0\n")
    with pytest.raises(ConfigError) as exc:
        load_config(path)

    message = str(exc.value)
    assert "risk.max_daily_loss_pct" in message, "must name the offending key"
    assert "less than or equal to 100" in message, "must say what was expected"
    assert "150.0" in message, "must show what it got"


@pytest.mark.parametrize("key", MONEY_KEYS)
def test_rejects_non_positive_risk_limit(tmp_path: Path, key: str) -> None:
    path = write(tmp_path, f"risk:\n  {key}: 0.0\n")
    with pytest.raises(ConfigError, match=rf"risk\.{key}"):
        load_config(path)


def test_rejects_unknown_approval_mode(tmp_path: Path) -> None:
    path = write(tmp_path, "approval:\n  mode: yolo\n")
    with pytest.raises(ConfigError, match=r"approval\.mode"):
        load_config(path)


def test_rejects_empty_symbol_allowlist(tmp_path: Path) -> None:
    path = write(tmp_path, "risk:\n  symbol_allowlist: []\n")
    with pytest.raises(ConfigError, match=r"risk\.symbol_allowlist"):
        load_config(path)


def test_rejects_unknown_key(tmp_path: Path) -> None:
    """A typo must fail loudly, not be silently ignored."""
    path = write(tmp_path, "risk:\n  max_dialy_loss_pct: 2.0\n")
    with pytest.raises(ConfigError, match=r"max_dialy_loss_pct"):
        load_config(path)


def test_rejects_malformed_session_window(tmp_path: Path) -> None:
    path = write(tmp_path, 'risk:\n  session_window:\n    start: "9:45am"\n')
    with pytest.raises(ConfigError, match=r"session_window\.start"):
        load_config(path)


def test_rejects_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(write(tmp_path, "risk:\n  - [unclosed\n"))


def test_reports_every_problem_at_once(tmp_path: Path) -> None:
    """One boot, one complete list -- not a fix-and-retry treadmill."""
    path = write(
        tmp_path,
        "approval:\n  mode: yolo\nrisk:\n  max_daily_loss_pct: 150.0\n",
    )
    message = str(pytest.raises(ConfigError, load_config, path).value)
    assert "approval.mode" in message
    assert "risk.max_daily_loss_pct" in message
    assert "2 problems" in message


# --------------------------------------------------------------------------
# Secrets: env only, never behaviour, never in the repr
# --------------------------------------------------------------------------


def test_config_has_no_field_that_could_hold_a_secret() -> None:
    """Structural, not a convention: there is nowhere to put a key."""
    suspicious = {"api_key", "secret", "token", "password", "secret_key"}
    for name, model in Config.model_fields.items():
        annotation = getattr(model.annotation, "model_fields", {})
        assert not (suspicious & set(annotation)), f"{name} exposes a secret field"


def test_secrets_repr_does_not_leak_the_value() -> None:
    secrets = Secrets({"ANTHROPIC_API_KEY": "sk-do-not-print-me"})
    assert "sk-do-not-print-me" not in repr(secrets)
    assert "ANTHROPIC_API_KEY" in repr(secrets)


def test_require_names_the_missing_secret() -> None:
    with pytest.raises(ConfigError, match="ELEVENLABS_API_KEY"):
        Secrets({}).require("ELEVENLABS_API_KEY")


def test_env_supplies_secrets_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-value")
    monkeypatch.setenv("GENESIS_APPROVAL_MODE", "auto-within-limits")

    secrets = load_secrets(None)
    assert secrets.require("ANTHROPIC_API_KEY") == "sk-test-value"
    # An env var must never be able to loosen behaviour.
    assert load_config(None).approval.mode == "confirm"


def test_env_file_must_be_locked_down(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-leaky\n", encoding="utf-8")
    env_file.chmod(0o644)
    with pytest.raises(ConfigError, match="expected 0600"):
        load_secrets(env_file)


def test_env_file_at_0600_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("NEWS_API_KEY=from-file\n", encoding="utf-8")
    env_file.chmod(0o600)
    assert load_secrets(env_file).require("NEWS_API_KEY") == "from-file"


# --------------------------------------------------------------------------
# The shipped template is the thing `config init` writes
# --------------------------------------------------------------------------


def test_default_template_is_valid_and_carries_no_secret() -> None:
    text = default_config_text()
    assert "api_key" not in text.lower() or "keys come from env" in text.lower()
    for name in SECRET_ENV_VARS:
        assert f"{name}=" not in text
