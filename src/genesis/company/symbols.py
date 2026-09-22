# Spec: Genesis Markdown/10-Architecture/Company Data Model.md
"""Is this a company, and what does the vendor call it?

Two jobs, and the second is a safety check rather than a convenience.

**Normalisation.** ``BRK.B`` is ``BRK-B`` to Yahoo, ``brk.b`` to a person, and
``BRK B`` to whoever typed it into a spreadsheet. One table, here, because the
alternative is each provider guessing and two of them guessing differently.
Adapted from ``TradingAgents/tradingagents/dataflows/symbol_utils.py``, which
solved the same problem for a wider instrument set.

**Validation.** This is the important half. ``yf.Ticker("ZZZZNOTREAL").info``
returns ``{"trailingPegRatio": None}`` -- a dict that is truthy, has length 1,
and describes nothing. Verified 2026-09-04. A reasonable ``if info:`` therefore
admits a symbol that does not exist, and Genesis proceeds to answer questions
about a company that was never real. That is a [[Safety Invariants]] §10
confabulation entering through a truthiness check, which is exactly the kind of
hole that no amount of care further downstream can close.

So: **a response is not evidence of an instrument.** Populated identity fields
are.
"""

from __future__ import annotations

import re

from genesis.errors import DegradedError

__all__ = [
    "IDENTITY_FIELDS",
    "UnknownSymbol",
    "is_populated_identity",
    "normalise",
    "to_yahoo",
]


class UnknownSymbol(DegradedError):
    """The symbol does not resolve to a company.

    ``degraded`` rather than ``fatal``: a typo is not a system failure, and the
    right response is to say so and let the user try again. What it must never
    be is an empty profile that reads like a real but obscure company.
    """


#: Fields whose presence means "a real issuer answered". Any ONE of these
#: alongside a name is enough -- a name on its own could be an echo of the
#: query string, but a name plus a sector could not.
IDENTITY_FIELDS = ("exchange", "sector", "industry", "marketCap", "quoteType", "cik")

#: Characters a ticker may contain after normalisation. Deliberately tight: a
#: symbol is about to be interpolated into vendor URLs, so anything outside
#: this set is rejected here rather than sanitised into something plausible.
_VALID = re.compile(r"^[A-Z0-9^][A-Z0-9.\-^=]{0,19}$")

#: Separators people and systems use for a class share. The canonical form is
#: the exchange's own -- ``BRK.B`` -- and the vendor spelling is applied at the
#: vendor boundary by `to_yahoo`, never stored. Same principle as
#: `genesis.marketdata.normalize`: a change in Yahoo's convention must not
#: rewrite our history.
_SEPARATORS = str.maketrans({" ": ".", "/": ".", "_": "."})

#: Class-share and index conventions differ per vendor. Yahoo uses `-` where
#: the exchange prints `.`, and prefixes indices with `^`.
_YAHOO_FIXES = {
    ".": "-",   # canonical BRK.B -> Yahoo's BRK-B
}

#: Symbols where the plain root is not what Yahoo wants. Short and closed;
#: anything not listed passes through unchanged, which is right for the
#: thousands of ordinary tickers.
_ALIASES = {
    "SPX": "^GSPC",
    "SP500": "^GSPC",
    "NDX": "^NDX",
    "VIX": "^VIX",
    "DJI": "^DJI",
    "RUT": "^RUT",
}


def normalise(symbol: str) -> str:
    """A typed ticker, canonicalised. Raises on anything unusable.

    Rejects rather than repairs. A symbol that has been "fixed" into validity
    is a request for data about a different company, and it will be answered
    with a straight face.
    """
    raw = (symbol or "").strip().upper()
    if not raw:
        raise UnknownSymbol("no symbol given")
    if raw in _ALIASES:
        return _ALIASES[raw]
    # Separators are canonicalised, not rejected: "BRK B" and "BRK/B" are the
    # same instrument written by different systems. Everything else that fails
    # the pattern below is still refused rather than repaired.
    raw = raw.translate(_SEPARATORS)
    if raw in _ALIASES:
        return _ALIASES[raw]
    if not _VALID.match(raw):
        raise UnknownSymbol(
            f"{symbol!r} is not a usable ticker. Expected letters, digits and "
            f"'.-^=' only.",
            spoken_summary=f"I don't recognise {symbol} as a ticker.",
        )
    return raw


def to_yahoo(symbol: str) -> str:
    """Canonical ticker in Yahoo's spelling.

    Applied at the vendor boundary only. The canonical form stays canonical in
    the store, so a change in Yahoo's conventions never rewrites our history --
    the same reason :mod:`genesis.marketdata.normalize` keeps vendor spellings
    out of the symbol id.
    """
    out = normalise(symbol)
    if out.startswith("^"):
        return out
    for bad, good in _YAHOO_FIXES.items():
        out = out.replace(bad, good)
    return out


def is_populated_identity(info: object) -> bool:
    """Does this vendor payload describe an actual company?

    The guard behind hazard 1. Requires a name AND one corroborating identity
    field, because a name alone can be an echo of the query while two
    independent facts cannot.

    Deliberately takes ``object`` and checks the type itself: a provider that
    returns ``None``, a list, or a string on failure should be caught here
    rather than raising an ``AttributeError`` three frames later.
    """
    if not isinstance(info, dict) or not info:
        return False
    named = any(
        isinstance(info.get(k), str) and info.get(k, "").strip()
        for k in ("longName", "shortName", "displayName", "name")
    )
    if not named:
        return False
    return any(info.get(k) not in (None, "", 0) for k in IDENTITY_FIELDS)
