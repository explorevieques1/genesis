# Spec: Genesis Markdown/10-Architecture/Observability.md
"""The two non-episodic log streams.

Observability.md defines three streams. Two of them are Phase 0:

==================  ==========================  ==================================
Stream              Audience                    Store
==================  ==========================  ==================================
Console / CLI       you, live                   stdout, emoji-prefixed, indented
Structured log      machines, debugging         JSONL on disk, rotated
Episodic Log        agents, audit, Insight Miner SQLite -- **Phase 1, not here**
==================  ==========================  ==================================

The organising idea is tracing: every user utterance opens a ``trace_id``, and
every task, tool call, LLM call, memory write, order and fill descending from it
carries that id. One query then reconstructs the whole causal chain from the
words spoken to the fill. Nothing here is useful unless that id is threaded
through, so :class:`EventLog` refuses to write an event without ``trace_id``,
``agent`` and ``event``.

Secrets are redacted on the way to disk, never after.
"""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from genesis.ids import new_trace_id

__all__ = [
    "Console",
    "EventLog",
    "LEVELS",
    "new_trace_id",
    "redactor",
]

LEVELS: dict[str, int] = {"debug": 10, "info": 20, "warn": 30, "error": 40}

# Id generation lives in genesis.ids so the Episodic Log and the Task Bus mint
# ids the same way. Re-exported here because trace ids are an observability
# concept and callers expect to find them alongside the log.


# --------------------------------------------------------------------------
# Console stream
# --------------------------------------------------------------------------


class Console:
    """Emoji-prefixed, indented stdout -- the house style from Conventions.md.

    ::

        con = Console()
        con.line("🌅", "Pre-market brief")
        with con.nest():
            con.line("📊", "Regime: risk-on · VIX 14.2")
            with con.nest():
                con.warn("CPI 08:30 ET -- high impact")

    Indentation is structural, not decorative: it is how a person reads a fleet
    of thirty agents without reading a log file.
    """

    _INDENT = "  "

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        enabled: bool = True,
        level: str = "info",
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._enabled = enabled
        self._level = LEVELS[level]
        self._depth = 0

    # -- structure ---------------------------------------------------------

    class _Nest:
        def __init__(self, console: Console) -> None:
            self._console = console

        def __enter__(self) -> Console:
            self._console._depth += 1
            return self._console

        def __exit__(self, *exc: object) -> None:
            self._console._depth -= 1

    def nest(self) -> Console._Nest:
        """Indent one level for the duration of the ``with`` block."""
        return Console._Nest(self)

    # -- output ------------------------------------------------------------

    def line(self, emoji: str, text: str, *, level: str = "info") -> None:
        if not self._enabled or LEVELS[level] < self._level:
            return
        prefix = self._INDENT * self._depth
        self._stream.write(f"{prefix}{emoji} {text}\n")
        self._stream.flush()

    def info(self, text: str, emoji: str = "·") -> None:
        self.line(emoji, text)

    def ok(self, text: str) -> None:
        self.line("✅", text)

    def warn(self, text: str) -> None:
        self.line("⚠️ ", text, level="warn")

    def error(self, text: str) -> None:
        self.line("❌", text, level="error")

    def degraded(self, text: str) -> None:
        """Degraded output must be *visibly* labelled -- never silent bad data."""
        self.line("🟡", f"{text}  [degraded]", level="warn")

    def debug(self, text: str) -> None:
        self.line("🔎", text, level="debug")


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


def redactor(secret_values: tuple[str, ...]) -> Any:
    """Build a function that scrubs known secret values out of any structure.

    Redaction happens *before* anything is persisted -- Config And Secrets.md:
    secrets are never logged, never written to the vault, never sent to an LLM.
    Short values are ignored: a two-character "secret" would blank half the log.
    """
    targets = tuple(sorted((v for v in secret_values if len(v) >= 8), key=len, reverse=True))

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for secret in targets:
                if secret in value:
                    value = value.replace(secret, "***REDACTED***")
            return value
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [scrub(v) for v in value]
        return value

    return scrub


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        # Money crosses the JSON boundary as a string. Serialising a Decimal as a
        # JSON number would reintroduce the float this system is built to avoid.
        return str(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return repr(obj)


# --------------------------------------------------------------------------
# Structured stream
# --------------------------------------------------------------------------


@dataclass
class EventLog:
    """Append-only JSONL, one object per line, in the Observability.md shape.

    ::

        {"ts": "...", "level": "info", "agent": "screener",
         "trace_id": "tr_...", "task_id": "t_...", "event": "scan.completed",
         "data": {...}, "cost": {...}, "degraded": false}

    Rotation is size-based and dumb on purpose: a log that rotates is one you
    still have three weeks later, which is the whole acceptance criterion.
    """

    path: Path
    level: str = "info"
    max_bytes: int = 32 * 1024 * 1024
    keep: int = 5
    scrub: Any = field(default=None)

    def __post_init__(self) -> None:
        self.path = Path(self.path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._threshold = LEVELS[self.level]
        self._lock = threading.Lock()
        if self.scrub is None:
            self.scrub = redactor(())

    def emit(
        self,
        *,
        event: str,
        agent: str,
        trace_id: str,
        level: str = "info",
        task_id: str | None = None,
        data: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
        degraded: bool = False,
    ) -> None:
        """Write one event.

        ``event``, ``agent`` and ``trace_id`` are required, not optional with a
        default -- Observability.md's acceptance criterion is that *every* log
        line carries all three. A default would let a caller silently break the
        causal chain, which is the one thing this file exists to prevent.
        """
        if LEVELS[level] < self._threshold:
            return

        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": level,
            "agent": agent,
            "trace_id": trace_id,
            "event": event,
        }
        if task_id is not None:
            record["task_id"] = task_id
        record["data"] = self.scrub(data or {})
        if cost is not None:
            record["cost"] = cost
        record["degraded"] = degraded

        line = json.dumps(record, default=_json_default, ensure_ascii=False)
        with self._lock:
            self._rotate_if_needed(len(line) + 1)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def _rotate_if_needed(self, incoming: int) -> None:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size + incoming <= self.max_bytes:
            return
        for i in range(self.keep - 1, 0, -1):
            src = self.path.with_suffix(self.path.suffix + f".{i}")
            if src.exists():
                src.replace(self.path.with_suffix(self.path.suffix + f".{i + 1}"))
        self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))

    @classmethod
    def from_config(cls, config: Any, scrub: Any = None) -> EventLog:
        return cls(
            path=config.logging.jsonl_path,
            level=config.logging.level,
            scrub=scrub,
        )
