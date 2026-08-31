# Spec: Genesis Markdown/60-UI/Voice UX.md
"""Earcons, including the one acceptance criterion that is about sound itself.

Voice UX: *"Order-placed and risk-rejected earcons are distinguishable blind."*
That cannot be asserted by ear in CI, so it is asserted along the axes that
make it true — direction, register, rhythm and timbre — and each of those is a
property of the table rather than of the renderer.
"""

from __future__ import annotations

import struct

import pytest

from genesis.voice.earcons import (
    MAX_DURATION_SEC,
    TONES,
    Earcon,
    EarconPlayer,
    render,
)
from genesis.voice.player import NullPlayer


def samples(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


def frequencies(earcon: Earcon) -> list[float]:
    return [f for f, _d, _g in TONES[earcon].steps]


# -- all seven exist and are sane ---------------------------------------------


def test_voice_ux_lists_seven_earcons_and_all_seven_exist() -> None:
    assert len(Earcon) == 7
    assert set(TONES) == set(Earcon)


@pytest.mark.parametrize("earcon", list(Earcon))
def test_every_earcon_renders_audible_pcm(earcon: Earcon) -> None:
    pcm = render(earcon)
    assert pcm, f"{earcon} rendered nothing"
    assert len(pcm) % 2 == 0
    assert max(abs(s) for s in samples(pcm)) > 1000, "inaudibly quiet"


@pytest.mark.parametrize("earcon", list(Earcon))
def test_no_earcon_outstays_its_welcome(earcon: Earcon) -> None:
    assert TONES[earcon].duration_sec <= MAX_DURATION_SEC


@pytest.mark.parametrize("earcon", list(Earcon))
def test_every_earcon_starts_and_ends_near_silence(earcon: Earcon) -> None:
    """The envelope, tested. An un-ramped sine clicks, and on a small speaker
    the click is louder and more startling than the tone."""
    s = samples(render(earcon))
    assert abs(s[0]) < 500 and abs(s[-1]) < 500


# -- the acceptance criterion --------------------------------------------------


def test_order_placed_and_risk_rejected_differ_on_every_axis() -> None:
    placed, rejected = frequencies(Earcon.ORDER_PLACED), frequencies(Earcon.RISK_REJECTED)

    # Direction: one rises, the other is flat.
    assert placed == sorted(placed) and len(set(placed)) > 1
    assert len(set(rejected)) == 1

    # Register: no overlap at all, more than two octaves apart.
    assert min(placed) > max(rejected) * 4

    # Rhythm: three notes against two.
    assert len(placed) == 3 and len(rejected) == 2

    # Timbre: pure against harsh.
    assert TONES[Earcon.ORDER_PLACED].harsh is False
    assert TONES[Earcon.RISK_REJECTED].harsh is True


def test_the_two_money_earcons_are_the_loudest() -> None:
    """They mean an order went out or the gate stopped one. Nothing routine
    should be able to mask them."""
    routine = max(TONES[e].amplitude for e in (Earcon.DONE, Earcon.NEUTRAL))
    assert TONES[Earcon.ORDER_PLACED].amplitude > routine
    assert TONES[Earcon.RISK_REJECTED].amplitude > routine


def test_every_earcon_is_distinguishable_from_every_other() -> None:
    """No two earcons share a signature. A duplicate would be worse than a
    missing sound: it would mean the wrong thing confidently."""
    signatures = {
        e: (tuple(frequencies(e)), len(TONES[e].steps), TONES[e].harsh) for e in Earcon
    }
    assert len(set(signatures.values())) == len(Earcon)


# -- the player ----------------------------------------------------------------


def test_playing_feeds_the_same_device_as_speech() -> None:
    player = NullPlayer()
    earcons = EarconPlayer(player)
    earcons.play(Earcon.ACKNOWLEDGED)
    assert earcons.played == [Earcon.ACKNOWLEDGED]


def test_warming_renders_everything_off_the_latency_path() -> None:
    earcons = EarconPlayer(NullPlayer())
    earcons.warm()
    assert len(earcons._cache) == len(Earcon)


def test_a_dead_audio_device_does_not_raise() -> None:
    class Broken:
        sample_rate = 24_000

        def feed(self, pcm: bytes) -> None:
            raise OSError("no such device")

    EarconPlayer(Broken()).play(Earcon.RISK_REJECTED)  # must not raise


def test_silent_mode_plays_nothing_but_still_records_intent() -> None:
    class Counting(NullPlayer):
        fed = 0

        def feed(self, pcm: bytes) -> None:
            type(self).fed += 1

    player = Counting()
    earcons = EarconPlayer(player, enabled=False)
    earcons.play(Earcon.DONE)
    assert Counting.fed == 0
    assert earcons.played == [Earcon.DONE]  # the trace still knows
