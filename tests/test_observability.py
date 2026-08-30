# Spec: Genesis Markdown/10-Architecture/Observability.md
"""The two non-episodic streams.

The acceptance criterion these encode: *"Every log line has `trace_id`, `agent`,
and `event`."* Without that, the causal chain from a spoken word to a fill cannot
be reconstructed, which is the whole point of the stream.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path

import pytest

from genesis.observability import Console, EventLog, new_trace_id, redactor


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


# --------------------------------------------------------------------------
# Console
# --------------------------------------------------------------------------


def test_console_indents_by_nesting_depth() -> None:
    out = io.StringIO()
    console = Console(out)
    console.line("🌅", "Pre-market brief")
    with console.nest():
        console.line("📊", "Regime: risk-on")
        with console.nest():
            console.line("⚠️ ", "CPI 08:30 ET")

    assert out.getvalue() == (
        "🌅 Pre-market brief\n"
        "  📊 Regime: risk-on\n"
        "    ⚠️  CPI 08:30 ET\n"
    )


def test_nesting_unwinds_on_exception() -> None:
    console = Console(io.StringIO())
    with pytest.raises(RuntimeError):
        with console.nest():
            raise RuntimeError("boom")
    out = io.StringIO()
    console = Console(out)
    console.line("·", "flat")
    assert out.getvalue() == "· flat\n"


def test_degraded_output_is_visibly_labelled() -> None:
    """Degradation that isn't visible is just bad data with good manners."""
    out = io.StringIO()
    Console(out).degraded("sentiment feed down — price-only")
    assert "[degraded]" in out.getvalue()


def test_console_respects_level() -> None:
    out = io.StringIO()
    console = Console(out, level="warn")
    console.debug("noise")
    console.info("also noise")
    console.warn("signal")
    assert "noise" not in out.getvalue()
    assert "signal" in out.getvalue()


def test_console_can_be_silenced() -> None:
    out = io.StringIO()
    Console(out, enabled=False).error("nothing")
    assert out.getvalue() == ""


# --------------------------------------------------------------------------
# Structured stream
# --------------------------------------------------------------------------


def test_every_event_carries_trace_agent_and_event(tmp_path: Path) -> None:
    path = tmp_path / "genesis.jsonl"
    log = EventLog(path=path)
    log.emit(event="scan.completed", agent="screener", trace_id="tr_1")

    (record,) = read_events(path)
    for required in ("ts", "level", "agent", "trace_id", "event"):
        assert required in record, f"missing {required}"
    assert record["agent"] == "screener"
    assert record["event"] == "scan.completed"
    assert record["trace_id"] == "tr_1"


def test_emit_refuses_to_lose_the_causal_chain(tmp_path: Path) -> None:
    """trace_id/agent/event have no defaults, by design."""
    log = EventLog(path=tmp_path / "genesis.jsonl")
    with pytest.raises(TypeError):
        log.emit(event="orphan.event")  # type: ignore[call-arg]


def test_money_crosses_the_json_boundary_as_a_string(tmp_path: Path) -> None:
    """A Decimal serialised as a JSON number is a float again on the way back."""
    path = tmp_path / "genesis.jsonl"
    EventLog(path=path).emit(
        event="order.proposed",
        agent="order-manager",
        trace_id="tr_1",
        data={"limit_price": Decimal("121.00")},
    )
    assert '"limit_price": "121.00"' in path.read_text()
    assert read_events(path)[0]["data"]["limit_price"] == "121.00"


def test_secrets_are_redacted_before_they_reach_disk(tmp_path: Path) -> None:
    path = tmp_path / "genesis.jsonl"
    log = EventLog(path=path, scrub=redactor(("sk-super-secret-value",)))
    log.emit(
        event="tool.called",
        agent="broker-adapter",
        trace_id="tr_1",
        data={"headers": {"authorization": "Bearer sk-super-secret-value"}},
    )
    text = path.read_text()
    assert "sk-super-secret-value" not in text
    assert "***REDACTED***" in text


def test_redactor_ignores_short_values() -> None:
    """A two-character 'secret' would blank half the log."""
    assert redactor(("ab",))("a table of ab") == "a table of ab"


def test_degraded_flag_is_always_present(tmp_path: Path) -> None:
    path = tmp_path / "genesis.jsonl"
    log = EventLog(path=path)
    log.emit(event="quote.read", agent="market-analyst", trace_id="tr_1")
    log.emit(
        event="quote.read", agent="market-analyst", trace_id="tr_2", degraded=True
    )
    a, b = read_events(path)
    assert a["degraded"] is False
    assert b["degraded"] is True


def test_level_filtering(tmp_path: Path) -> None:
    path = tmp_path / "genesis.jsonl"
    log = EventLog(path=path, level="warn")
    log.emit(event="chatter", agent="a", trace_id="tr_1", level="debug")
    log.emit(event="problem", agent="a", trace_id="tr_1", level="error")
    assert [r["event"] for r in read_events(path)] == ["problem"]


def test_rotation_keeps_history(tmp_path: Path) -> None:
    path = tmp_path / "genesis.jsonl"
    log = EventLog(path=path, max_bytes=400)
    for i in range(20):
        log.emit(event=f"e.{i}", agent="screener", trace_id="tr_1")

    assert path.exists()
    assert path.with_suffix(".jsonl.1").exists(), "rotated file should be kept"


def test_log_directory_is_created(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deeper" / "genesis.jsonl"
    EventLog(path=path).emit(event="e", agent="a", trace_id="tr_1")
    assert path.exists()


# --------------------------------------------------------------------------
# Trace ids
# --------------------------------------------------------------------------


def test_trace_ids_are_prefixed_and_unique() -> None:
    ids = {new_trace_id() for _ in range(500)}
    assert len(ids) == 500
    assert all(i.startswith("tr_") for i in ids)


def test_trace_ids_avoid_ambiguous_characters() -> None:
    """Crockford base32: no I, L, O or U, so an id can be read aloud."""
    body = new_trace_id().removeprefix("tr_")
    assert not (set(body) & set("ILOU"))
