# Spec: Genesis Markdown/60-UI/Voice UX.md
"""Non-verbal status. Faster than words and less intrusive.

Voice UX gives seven sounds and one hard requirement: *"the order-placed and
risk-rejection sounds must be immediately distinguishable from each other with
no words attached."* That is a design constraint on the waveforms, not on the
labels, so the two are separated along every axis at once -- direction, timbre,
rhythm and register. A bright three-note rising arpeggio and a low two-pulse
buzz cannot be confused in a noisy room or through a door.

They also earn their place on the latency budget. [[10-Architecture/Voice Stack]]:
anything needing agents exceeds the 1.5 s target, so *"acknowledge immediately
with an earcon plus a one-liner."* The tone is the half of that acknowledgement
that can fire in milliseconds, before the planner has decided anything.

Synthesised rather than shipped as files: a sine with an envelope is a few
lines, has no licensing or path questions, and stays correct if the player's
sample rate changes. Every tone is generated once and cached, because an earcon
that has to be computed before it can be heard is not an earcon.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from enum import Enum

__all__ = ["Earcon", "EarconPlayer", "render", "TONES"]

SAMPLE_RATE = 24_000
#: Kept well under the speech that may follow. An earcon that takes half a
#: second is an interruption, not a signal.
MAX_DURATION_SEC = 0.6


class Earcon(str, Enum):
    """The seven sounds in Voice UX, by meaning rather than by pitch."""

    ACKNOWLEDGED = "acknowledged"       # heard you, working on it
    DONE = "done"                       # finished, no speech follows
    NEUTRAL = "neutral"                 # noted, no action needed
    ORDER_PLACED = "order_placed"       # an order went out
    RISK_REJECTED = "risk_rejected"     # the gate said no
    INVALIDATION = "invalidation"       # a level broke on an open position
    COMPONENT_DOWN = "component_down"   # something went down


@dataclass(frozen=True)
class Tone:
    """One earcon as a sequence of (frequency Hz, duration s, gap s) steps."""

    steps: tuple[tuple[float, float, float], ...]
    amplitude: float = 0.22
    #: A square-ish timbre for the two warnings. Harmonically rich, so it cuts
    #: through a room and cannot be mistaken for the pure-tone family.
    harsh: bool = False

    @property
    def duration_sec(self) -> float:
        return sum(d + g for _f, d, g in self.steps)


#: The table. Read down the ``ORDER_PLACED`` / ``RISK_REJECTED`` rows together:
#: rising vs falling, bright vs low, three notes vs two, pure vs harsh. Four
#: independent differences, so no single degradation -- a bad speaker, a noisy
#: room, hearing loss at one end of the range -- can collapse them into each
#: other.
TONES: dict[Earcon, Tone] = {
    # Soft rising tone: heard you.
    Earcon.ACKNOWLEDGED: Tone(steps=((660.0, 0.07, 0.0), (880.0, 0.09, 0.0))),
    # Soft double tone, level: done, nothing more to say.
    Earcon.DONE: Tone(steps=((760.0, 0.06, 0.05), (760.0, 0.08, 0.0)), amplitude=0.18),
    # Low neutral: noted.
    Earcon.NEUTRAL: Tone(steps=((420.0, 0.10, 0.0),), amplitude=0.15),
    # Distinct chime: bright, rising, three notes.
    Earcon.ORDER_PLACED: Tone(
        steps=((784.0, 0.06, 0.01), (1046.0, 0.06, 0.01), (1318.0, 0.13, 0.0)),
        amplitude=0.26,
    ),
    # Low buzz: dark, flat, two pulses, harsh timbre. The opposite of above.
    Earcon.RISK_REJECTED: Tone(
        steps=((150.0, 0.12, 0.04), (150.0, 0.16, 0.0)), amplitude=0.24, harsh=True
    ),
    # Urgent triple: fast, high, insistent.
    Earcon.INVALIDATION: Tone(
        steps=((988.0, 0.05, 0.03), (988.0, 0.05, 0.03), (988.0, 0.09, 0.0)),
        amplitude=0.30,
    ),
    # Descending: something went down.
    Earcon.COMPONENT_DOWN: Tone(steps=((520.0, 0.08, 0.0), (330.0, 0.14, 0.0)), amplitude=0.20),
}


def render(earcon: Earcon, *, sample_rate: int = SAMPLE_RATE) -> bytes:
    """The earcon as 16-bit mono PCM.

    Each step gets a short raised-cosine envelope. Without it the abrupt start
    and stop of a sine produce a click, which on a small speaker is louder and
    more startling than the tone itself.
    """
    tone = TONES[earcon]
    samples: list[int] = []
    peak = int(32767 * tone.amplitude)

    for frequency, duration, gap in tone.steps:
        count = int(sample_rate * duration)
        ramp = max(1, int(sample_rate * 0.006))
        for i in range(count):
            phase = 2 * math.pi * frequency * i / sample_rate
            value = math.sin(phase)
            if tone.harsh:
                # A touch of third harmonic: buzzy, unmistakably not a chime.
                value = 0.75 * value + 0.25 * math.sin(3 * phase)
            envelope = min(1.0, i / ramp, (count - i) / ramp)
            samples.append(int(peak * value * envelope))
        samples.extend([0] * int(sample_rate * gap))

    return struct.pack(f"<{len(samples)}h", *samples)


class EarconPlayer:
    """Plays earcons through the same device as speech.

    Holds its own rendered cache and nothing else -- no thread, no queue. It
    shares the :class:`~genesis.voice.player.Player`, so ``stop`` on the
    speaker silences a tone as well, which is what you want when you interrupt.
    """

    def __init__(self, player, *, sample_rate: int = SAMPLE_RATE, enabled: bool = True) -> None:
        self.player = player
        self.sample_rate = getattr(player, "sample_rate", sample_rate)
        self.enabled = enabled
        self._cache: dict[Earcon, bytes] = {}
        self.played: list[Earcon] = []

    def warm(self) -> None:
        """Render every tone up front, off the latency path."""
        for earcon in Earcon:
            self._pcm(earcon)

    def play(self, earcon: Earcon) -> None:
        """Fire and forget. Never raises: a missing audio device is not a fault
        worth failing a conversation over."""
        self.played.append(earcon)
        if not self.enabled:
            return
        try:
            self.player.feed(self._pcm(earcon))
        except Exception:  # noqa: BLE001 - voice is a surface, not the spine
            pass

    def _pcm(self, earcon: Earcon) -> bytes:
        if earcon not in self._cache:
            self._cache[earcon] = render(earcon, sample_rate=self.sample_rate)
        return self._cache[earcon]
