# Spec: Genesis Markdown/10-Architecture/Operating Model.md §4 · 20-Agents/Research/Agent — News And Catalyst.md
"""Which symbols a brief is actually about — by lookup, never by asking a model.

Operating Model §4: *nobody knows the ticker.* "Chevron" resolves to `CVX` by
deterministic lookup against the universe snapshot, ambiguity is surfaced rather
than guessed, and what got resolved is shown. That rule is why this module is
regexes and a dictionary instead of a prompt: a model asked to extract tickers
will confidently return `MOON`, and nothing downstream could tell.

A brief already carries explicit symbols on its stories and its trade ideas.
Those are the strongest signal and are used as-is. What this adds is the rest of
the text — the overview, the themes, the risks, the body of each story — where
a company is named and never tagged, which is most of them.

Three ways a symbol is found, in descending confidence:

1. **Tagged** on a story or trade idea (`symbols: ["CVX"]`). No inference.
2. **A cashtag or a bare ticker** — `$CVX`, or `CVX` standing alone in upper
   case and present in the tradeable universe.
3. **A company name** — `Chevron` matched against the holdings file's own name
   for `CVX`, word-bounded, after the corporate suffixes are stripped.

**The false-positive problem is the whole difficulty.** Dozens of real tickers
are ordinary English words in upper case: `A`, `ALL`, `IT`, `NOW`, `ON`, `SO`,
`KEY`, `CAT`, `GO`, `WELL`. A headline reading "ALL EYES ON THE FED" would
otherwise produce three ideas. :data:`WORD_TICKERS` refuses those unless they
carry a `$`, and single letters are refused outright. The cost is missing a
genuine mention of `IT`; the alternative is a desk full of ideas about
prepositions.

**Direction comes from the story, not from sentiment analysis.** A brief labels
each story `bullish | bearish | mixed | neutral`. A symbol tagged on a bullish
story leans long. A symbol that appears in two stories pointing opposite ways is
**watch**, not a coin toss — ambiguity surfaced, never picked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Mention", "extract"]

#: Tickers that are also common English words. Refused unless cashtagged.
#: Not exhaustive and cannot be: it is a blacklist protecting a heuristic, and
#: the honest description of its failure mode is "a real mention of ON gets
#: missed", which is the cheap direction.
WORD_TICKERS = frozenset("""
    A ALL AN AND ANY ARE AS AT BE BIG BY CAN CAT CEO CPI DD DO EA EPS ETF EU FED
    FOR GDP GO GPS HAS HE IF IN IS IT ITS KEY LOW NEW NOW OF ON ONE OR OUT PM
    POST REAL RUN SO STAY T THE TO TV UP US USA V VS WE WELL WILL
""".split())

#: Stripped before a company name is matched, so "CHEVRON CORP" matches
#: "Chevron" in prose.
_SUFFIXES = re.compile(
    r"\b(inc|corp|corporation|co|company|plc|ltd|limited|holdings?|group|"
    r"class\s+[a-c]|the|&|and)\b\.?", re.I)
#: `nasdaq 100`, `s&p 500`, `russell 2000` — the index, not the company that
#: runs it. Without this, "Nasdaq 100 rebalance" produces an idea about NDAQ,
#: which is a real company whose shares the story is not about at all.
_INDEX_PHRASE = re.compile(r"\b(nasdaq|russell|dow|s&p|sp|ftse|nikkei|dax)\s+\d", re.I)
_CASHTAG = re.compile(r"\$([A-Z][A-Z.\-]{0,5})\b")
_BARE = re.compile(r"\b([A-Z]{2,5})\b")
_WORD = re.compile(r"[a-z0-9]+")

#: What each kind of evidence is worth. Tagged symbols dominate because they
#: involved no inference at all.
WEIGHT_TAGGED = 3.0
#: A `$` is a deliberate, unambiguous act by whoever wrote the text — the one
#: form that cannot be an accident of capitalisation. Worth the bar on its own.
WEIGHT_CASHTAG = 2.5
WEIGHT_TICKER = 1.5
WEIGHT_NAME = 2.0
#: Each repeat mention, capped — a symbol named eight times is not eight times
#: more interesting than one named twice.
WEIGHT_REPEAT = 0.5
MAX_REPEATS = 3
#: Below this a symbol is a passing reference, not what the brief is about.
#:
#: Calibrated against the weights above, and the calibration is the design: a
#: symbol *tagged* on a story clears it alone, and so does a cashtag. A company
#: **named once** in passing does not — it needs a second mention, or a ticker
#: alongside the name. One sentence about Chevron in a market wrap is not a
#: trade idea about Chevron, and a desk that treated it as one would fill up
#: with every company anyone mentioned.
MIN_SCORE = 2.5

_BIAS = {"bullish": "long", "bearish": "short", "mixed": "watch", "neutral": "watch"}


@dataclass
class Mention:
    """One symbol the brief is about, with the evidence that found it."""

    symbol: str
    score: float = 0.0
    #: ``long``, ``short`` or ``watch``. ``watch`` when the brief points both
    #: ways on it, or gives no direction at all.
    direction: str = "watch"
    #: Every distinct reason it was picked, in the order they were found.
    why: list[str] = field(default_factory=list)
    #: The headlines it came from, for the idea's thesis.
    stories: list[str] = field(default_factory=list)
    tagged: bool = False
    #: Set when stories disagree about the direction.
    conflicted: bool = False

    def add(self, weight: float, why: str) -> None:
        self.score += weight
        if why not in self.why:
            self.why.append(why)

    def lean(self, direction: str) -> None:
        """Record a side. Disagreement demotes to watch, permanently.

        Once two stories have pointed opposite ways, a third agreeing with one
        of them does not break the tie -- the brief is not of one mind about
        this symbol, and that is the finding. An earlier version let the next
        directional mention overwrite the demotion, so a conflicted symbol came
        out flagged `conflicted` and labelled `long`: the flag said ambiguous
        and the field picked a side anyway.
        """
        if direction == "watch" or self.conflicted:
            return
        if self.direction == "watch":
            self.direction = direction
        elif self.direction != direction:
            self.conflicted = True
            self.direction = "watch"

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "score": round(self.score, 2),
            "direction": self.direction, "why": list(self.why),
            "stories": list(self.stories), "tagged": self.tagged,
            "conflicted": self.conflicted,
        }


def _clean_name(name: str) -> str:
    """`CHEVRON CORP` -> `chevron`. Empty when nothing usable is left."""
    text = _SUFFIXES.sub(" ", name.lower())
    words = _WORD.findall(text)
    return " ".join(words).strip()


def _name_index(names: dict[str, str]) -> dict[str, str]:
    """``{cleaned company name: ticker}``, minus the ones too short to match.

    A three-letter cleaned name ("BOX", "IQ") matches inside ordinary prose far
    too often to be worth the ideas it would produce.
    """
    index: dict[str, str] = {}
    for ticker, raw in names.items():
        cleaned = _clean_name(raw)
        if len(cleaned) >= 4 and cleaned not in index:
            index[cleaned] = ticker.upper()
    return index


def _texts(brief: dict[str, Any]) -> list[tuple[str, str, str]]:
    """``(text, headline, direction)`` for every readable part of the brief."""
    out: list[tuple[str, str, str]] = [(str(brief.get("overview") or ""), "", "")]
    for story in brief.get("stories") or []:
        if not isinstance(story, dict):
            continue
        headline = str(story.get("headline") or "")
        body = " ".join(str(story.get(k) or "") for k in
                        ("headline", "what_happened", "why_it_matters"))
        out.append((body, headline, str(story.get("direction") or "")))
    for key in ("themes", "watch", "risks"):
        for line in brief.get(key) or []:
            out.append((str(line), "", ""))
    return out


def extract(
    brief: dict[str, Any],
    *,
    universe: Any,
    limit: int = 8,
    min_score: float = MIN_SCORE,
) -> list[Mention]:
    """Every symbol this brief is about, ranked. Pure: reads text, writes nothing.

    ``universe`` is a :class:`genesis.marketdata.universe.Universe` -- both the
    name lookup and the filter. A symbol this desk cannot trade is not extracted
    at all, because an idea about it could never be sized and would sit on the
    board as noise.
    """
    tradeable = {s.upper() for s in universe.symbols}
    names = _name_index(getattr(universe, "names", {}) or {})
    found: dict[str, Mention] = {}

    def mention(symbol: str) -> Mention | None:
        symbol = symbol.upper().strip()
        if symbol not in tradeable:
            return None
        return found.setdefault(symbol, Mention(symbol=symbol))

    # 1. Tagged — no inference, so nothing to be wrong about.
    for story in brief.get("stories") or []:
        if not isinstance(story, dict):
            continue
        direction = _BIAS.get(str(story.get("direction") or "").lower(), "watch")
        headline = str(story.get("headline") or "")
        for raw in story.get("symbols") or []:
            hit = mention(str(raw))
            if hit is None:
                continue
            hit.tagged = True
            hit.add(WEIGHT_TAGGED, f"tagged on “{headline[:60]}”" if headline else "tagged on a story")
            hit.lean(direction)
            if headline and headline not in hit.stories:
                hit.stories.append(headline)

    # 2 and 3. The text itself.
    for text, headline, raw_direction in _texts(brief):
        if not text:
            continue
        direction = _BIAS.get(raw_direction.lower(), "watch")

        for token in _CASHTAG.findall(text):
            hit = mention(token)
            if hit is not None:
                hit.add(WEIGHT_CASHTAG, f"${token} in the text")
                hit.lean(direction)

        for token in _BARE.findall(text):
            if token in WORD_TICKERS:
                continue
            hit = mention(token)
            if hit is not None:
                hit.add(WEIGHT_TICKER, f"{token} named in the text")
                hit.lean(direction)

        lowered = " " + " ".join(_WORD.findall(text.lower())) + " "
        # An index reference is not a mention of the exchange's own shares.
        indexed = {m.group(1).lower() for m in _INDEX_PHRASE.finditer(text)}
        for cleaned, ticker in names.items():
            if f" {cleaned} " not in lowered:
                continue
            if cleaned in indexed:
                continue
            hit = mention(ticker)
            if hit is None:
                continue
            repeats = min(lowered.count(f" {cleaned} ") - 1, MAX_REPEATS)
            hit.add(WEIGHT_NAME + repeats * WEIGHT_REPEAT,
                    f"“{cleaned}” named in the text")
            hit.lean(direction)
            if headline and headline not in hit.stories:
                hit.stories.append(headline)

    ranked = sorted(found.values(), key=lambda m: (-m.score, m.symbol))
    return [m for m in ranked if m.score >= min_score][:limit]
