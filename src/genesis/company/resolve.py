# Spec: Genesis Markdown/10-Architecture/Operating Model.md
"""Names to tickers, deterministically. Operating Model §4: nobody knows the ticker.

Two directions over the same S&P 500 snapshot:

* :func:`resolve_subject` -- one subject someone typed ("Nvidia") to one ticker.
  Ambiguity raises; a model never guesses.
* :func:`subjects_in` -- every company a whole sentence mentions, for recall.
  Ambiguous names are dropped rather than guessed; recall that misses is
  cheaper than recall that attaches the wrong company's findings.
"""

from __future__ import annotations

import re
from typing import Any

from genesis.errors import DegradedError

__all__ = ["resolve_subject", "subjects_in"]

#: Legal-form words a person never says. "Adobe Inc." is asked about as "Adobe".
_SUFFIX = re.compile(
    r"[,\s]+(?:inc\.?|corp\.?|corporation|company|co\.?|plc|ltd\.?|limited|holdings?|"
    r"group|n\.v\.|s\.a\.|incorporated|\(class [a-z]\))$",
    re.IGNORECASE,
)


def _rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if rows is not None:
        return rows
    from genesis.screener.snapshot import load_snapshot

    return load_snapshot().rows


def resolve_subject(subject: str, rows: list[dict[str, Any]] | None = None) -> tuple[str, str | None]:
    """Ticker or company name -> ``(ticker, how)``. Deterministic; ambiguity raises.

    Names resolve against the S&P 500 snapshot; anything else is taken as typed.
    """
    from genesis.company.symbols import normalise

    text = " ".join(subject.split()).strip()
    rows = _rows(rows)
    upper = text.upper()
    if any(r.get("symbol") == upper for r in rows):
        return upper, None
    word = re.compile(rf"\b{re.escape(text)}\b", re.IGNORECASE)
    hits = [r for r in rows if text and word.search(str(r.get("name") or ""))]
    if len(hits) == 1:
        return hits[0]["symbol"], f"{text} → {hits[0]['symbol']} ({hits[0].get('name')})"
    if len(hits) > 1:
        names = ", ".join(f"{r['symbol']} ({r.get('name')})" for r in hits[:5])
        raise DegradedError(f"{text!r} matches several companies: {names}",
                            spoken_summary=f"{text} could be {names}. Which one?")
    return normalise(text), None


def short_name(name: str) -> str:
    """``"Adobe Inc."`` -> ``"Adobe"``. Strips legal forms until none are left."""
    name = name.strip()
    while (trimmed := _SUFFIX.sub("", name)) != name:
        name = trimmed
    return name


def subjects_in(text: str, rows: list[dict[str, Any]] | None = None) -> list[str]:
    """Tickers a sentence mentions, in snapshot order. Never guesses.

    A ticker counts only when written in capitals ("ADBE"), because "NOW",
    "ALL" and "A" are also English. A company name counts on a whole-word,
    case-insensitive match of its short name; a short name shared by several
    rows (Alphabet's two share classes) is dropped.
    """
    rows = _rows(rows)
    by_name: dict[str, list[str]] = {}
    for r in rows:
        short = short_name(str(r.get("name") or "")).lower()
        if len(short) >= 3:
            by_name.setdefault(short, []).append(r["symbol"])
    found: list[str] = []
    for r in rows:
        symbol = r["symbol"]
        if len(symbol) >= 2 and re.search(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])", text):
            found.append(symbol)
    lowered = text.lower()
    for short, symbols in by_name.items():
        if len(symbols) == 1 and re.search(rf"\b{re.escape(short)}\b", lowered):
            if symbols[0] not in found:
                found.append(symbols[0])
    return found


def demo() -> None:
    rows = [
        {"symbol": "ADBE", "name": "Adobe Inc."},
        {"symbol": "GOOGL", "name": "Alphabet Inc. (Class A)"},
        {"symbol": "GOOG", "name": "Alphabet Inc. (Class C)"},
        {"symbol": "NOW", "name": "ServiceNow, Inc."},
    ]
    assert short_name("Alphabet Inc. (Class A)") == "Alphabet"
    assert subjects_in("analyse Adobe earnings vs fair value", rows) == ["ADBE"]
    assert subjects_in("is alphabet cheap now", rows) == []  # ambiguous, lowercase "now"
    assert subjects_in("compare ADBE and NOW", rows) == ["ADBE", "NOW"]


if __name__ == "__main__":
    demo()
    print("ok")
