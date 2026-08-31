# Spec: Genesis Markdown/40-Memory/Working Memory.md
"""Making the conversation durable.

Orchestrator's seventh responsibility is *"write turns, decisions, and outcomes
to Memory Fabric"*, and until this module existed the voice loop wrote none of
them: a turn reached a console printer and was gone. Nothing recorded what was
asked, which rung of the answer ladder took it, why the planner declined, or
how long any of it took -- so every latency and degradation the notes ask you
to observe was unobservable in practice.

Two rules shape what gets written.

**Ambient speech is counted, never quoted.** Working Memory's snapshot excludes
the ambient buffer because *"conversation you did not address to the system does
not end up on disk"*, and this is the same boundary one layer down. A turn the
classifier ruled ambient is logged as a count of words and nothing else. The
[[Voice Stack]] privacy line -- audio leaves the machine only after the local
wake gate fires -- would be worth very little if the transcript of everything
said near the microphone were then written to a database.

**Rolloff is summarisation, not deletion.** [[Working Memory]] is explicit that
what rolls out of the live buffer is preserved in the [[Episodic Log]], and that
a restart restores conversation *as a summary, not verbatim*. Both halves live
here: :meth:`VoiceRecorder.on_rolloff` preserves, :meth:`restore_summary`
reconstitutes.

The summary is built deterministically from the log rather than by a model.
Rolloff happens inside ``add_turn`` on the voice path, and a hosted call there
would put a network round trip between hearing you and answering; a restart
summary that is dull but instant and always correct is the better trade.
"""

from __future__ import annotations

from typing import Any

from genesis.ids import new_trace_id
from genesis.memory.episodic import EpisodicLog

__all__ = ["VoiceRecorder"]

#: One utterance, clipped. Long enough for any real request, short enough that
#: a runaway transcript cannot bloat a log entry.
MAX_TEXT_CHARS = 400

#: How many past exchanges a restart summary may mention. Working Memory:
#: conversation returns as a summary, and a summary that restates twenty turns
#: is just the transcript with extra steps.
RESTORE_TURNS = 6


class VoiceRecorder:
    """Sinks for :class:`~genesis.orchestrator.loop.VoiceLoop` and
    :class:`~genesis.memory.working.WorkingMemory`.

    Never raises. This is wired into the audio path, and a logging fault must
    not be able to end a conversation -- Error Handling And Degradation:
    *voice is a surface, not the spine*.
    """

    def __init__(self, log: EpisodicLog, *, actor: str = "orchestrator") -> None:
        self.log = log
        self.actor = actor

    # -- the voice loop's on_turn sink -------------------------------------

    def on_turn(self, turn: Any) -> None:
        kind, summary, payload = self._entry_for(turn)
        self._append(
            kind=kind,
            summary=summary,
            payload=payload,
            trace_id=getattr(turn, "trace_id", "") or new_trace_id(),
            degraded=bool(payload.get("stt_degraded") or kind == "voice.error"),
        )

    def _entry_for(self, turn: Any) -> tuple[str, str, dict[str, Any]]:
        intent = getattr(turn, "intent", "") or "unknown"
        fields = dict(getattr(turn, "fields", {}) or {})
        timings = {
            "wake_ms": round(getattr(turn, "wake_ms", 0.0), 1),
            "stt_ms": round(getattr(turn, "stt_ms", 0.0), 1),
            "total_ms": round(getattr(turn, "total_ms", 0.0), 1),
        }

        if intent == "ambient":
            # Counted, never quoted. The one branch in this module that must
            # not be "improved" by including the text for debugging.
            words = len(str(getattr(turn, "heard", "")).split())
            return (
                "voice.ambient",
                "ambient speech, ignored",
                {"words": words, **timings},
            )

        if intent == "echo":
            return "voice.echo", "heard ourselves, discarded", timings

        if intent == "error":
            return "voice.error", "the turn raised", {**fields, **timings}

        payload: dict[str, Any] = {
            "intent": intent,
            "path": getattr(turn, "path", ""),
            "source": getattr(turn, "source", ""),
            **timings,
            **fields,
        }
        # The bus trace for a dispatched plan, so a spoken request and the tasks
        # it produced can be read as one story. The runner encodes it in the
        # answer's source as ``plan:<id>[:state]``.
        source = str(getattr(turn, "source", ""))
        if source.startswith("plan:"):
            payload["plan_id"] = source.split(":")[1]

        if intent == "stop":
            return "voice.reflex", f"reflex: {fields.get('reflex', 'stop')}", payload

        heard = _clip(getattr(turn, "heard", ""))
        spoken = _clip(getattr(turn, "spoken", ""))
        payload["heard"] = heard
        payload["spoken"] = spoken
        return "voice.turn", f'"{heard}" -> "{spoken}"' if spoken else f'"{heard}"', payload

    # -- working memory's on_rolloff sink ----------------------------------

    def on_rolloff(self, turns: list[Any]) -> None:
        """Preserve turns aging out of the live buffer.

        These are turns that were already addressed to Genesis -- ambient
        speech never entered the buffer in the first place -- so preserving
        them verbatim is consistent with the privacy boundary above.
        """
        if not turns:
            return
        self._append(
            kind="conversation.rolloff",
            summary=f"{len(turns)} turn(s) rolled out of working memory",
            payload={
                "turns": [
                    {"speaker": getattr(t, "speaker", "?"), "text": _clip(getattr(t, "text", ""))}
                    for t in turns
                ]
            },
            trace_id=new_trace_id(),
        )

    # -- restart continuity -------------------------------------------------

    def restore_summary(self, *, limit: int = RESTORE_TURNS) -> str | None:
        """A sentence describing the conversation before the restart.

        Deterministic and cheap: the last few things you asked, in order, as
        one line. Amnesia is the default for these systems, and continuity is
        manufactured -- [[Biological Design]] names this as a thing you build
        rather than a thing you have.
        """
        try:
            entries = self.log.by_kind("voice.turn", limit=limit)
        except Exception:  # noqa: BLE001 - a missing log is not a crash
            return None
        asked = [
            (e.payload or {}).get("heard", "")
            for e in reversed(entries)
            if (e.payload or {}).get("heard")
        ]
        if not asked:
            return None
        joined = "; ".join(_clip(a, 80) for a in asked[-limit:])
        return f"Earlier you asked: {joined}."

    # -- internals ----------------------------------------------------------

    def _append(
        self, *, kind: str, summary: str, payload: dict[str, Any], trace_id: str, degraded: bool = False
    ) -> None:
        try:
            self.log.append(
                actor=self.actor,
                kind=kind,
                trace_id=trace_id,
                summary=summary,
                payload=payload,
                degraded=degraded,
            )
        except Exception:  # noqa: BLE001 - never end a conversation over a log write
            pass


def _clip(text: Any, limit: int = MAX_TEXT_CHARS) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
