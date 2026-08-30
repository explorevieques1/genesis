# Spec: Genesis Markdown/40-Memory/Episodic Log.md
"""Identifier generation.

The vault writes ids as ``ep_01J8XZ...``, ``t_01J8XQ...``, ``tr_01J8XP...`` --
a prefix plus a ULID. ULIDs are used rather than UUID4 for one reason that
matters to an append-only log: the first 48 bits are a millisecond timestamp, so
**ids sort lexicographically in creation order** down to the millisecond. That
makes an id range a cheap time range.

Within a single millisecond the ordering is the random suffix, i.e. arbitrary --
so anything that must be strictly causal orders by ``rowid`` instead. See
:meth:`genesis.memory.episodic.EpisodicLog.by_trace`.

Crockford base32 omits I, L, O and U, so an id can be read aloud over voice
without ambiguity ([[Voice UX]]).
"""

from __future__ import annotations

import os
import time

__all__ = ["new_id", "new_trace_id", "timestamp_ms_of"]

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}

_TIME_CHARS = 10  # 48 bits
_RANDOM_CHARS = 16  # 80 bits


def _encode(value: int, length: int) -> str:
    out = [""] * length
    for i in range(length - 1, -1, -1):
        out[i] = _ALPHABET[value & 31]
        value >>= 5
    return "".join(out)


def new_id(prefix: str) -> str:
    """A prefixed ULID, e.g. ``new_id("ep")`` -> ``ep_01J8XZ...``."""
    ms = int(time.time() * 1000)
    randomness = int.from_bytes(os.urandom(10), "big")
    return f"{prefix}_{_encode(ms, _TIME_CHARS)}{_encode(randomness, _RANDOM_CHARS)}"


def new_trace_id() -> str:
    """Open a new trace. One per user utterance, per Observability.md."""
    return new_id("tr")


def timestamp_ms_of(identifier: str) -> int:
    """Recover the creation time embedded in a ULID, for tests and forensics."""
    body = identifier.split("_", 1)[-1][:_TIME_CHARS]
    value = 0
    for char in body:
        value = (value << 5) | _DECODE[char]
    return value
