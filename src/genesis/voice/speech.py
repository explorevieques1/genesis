# Spec: Genesis Markdown/60-UI/Voice UX.md
"""Turning numbers into the words a trader actually says.

Voice UX.md opens its number section with the reason this module exists:

    The most common way a voice trading assistant becomes unusable is by
    reading numbers badly.

``121.06`` is *"one twenty-one oh six"*, not *"one hundred twenty-one point
zero six"*. ``NVDA`` is *"N-V-D-A"*, never *"nividia"*. A screen reader is
wrong here in a way that is not a matter of taste: the wrong rendering takes
longer to say, is harder to hear against a noisy room, and is not the form the
listener's ear is trained on.

**This is spinal.** Biological Design's reflex arc puts deterministic,
sub-millisecond work below the model, and there is no judgement anywhere in
reading a price aloud -- only a convention, which code holds more reliably than
a prompt does. An LLM asked to format these would be slower, occasionally
creative, and impossible to unit-test. Every function here is pure.

The public entry point is :func:`speakable`, which rewrites a whole sentence.
The ``say_*`` functions are exposed for callers that already know what they
hold.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = [
    "PRONOUNCED_TICKERS",
    "say_confidence",
    "say_date",
    "say_ordinal",
    "say_year",
    "say_money",
    "say_multiple",
    "say_percent",
    "say_price",
    "say_r_multiple",
    "say_ticker",
    "say_time",
    "speakable",
]

# --------------------------------------------------------------------------
# Cardinals
# --------------------------------------------------------------------------

_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
)


def _under_100(n: int) -> str:
    """0-99 in words. ``42`` -> ``forty-two``."""
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] if ones == 0 else f"{_TENS[tens]}-{_ONES[ones]}"


def _under_1000(n: int) -> str:
    """0-999 in words, no ``and``. ``312`` -> ``three hundred twelve``."""
    if n < 100:
        return _under_100(n)
    hundreds, rest = divmod(n, 100)
    head = f"{_ONES[hundreds]} hundred"
    return head if rest == 0 else f"{head} {_under_100(rest)}"


def _cardinal(n: int) -> str:
    """Any non-negative int in words. Used for share counts and dollars."""
    if n < 1000:
        return _under_1000(n)
    parts: list[str] = []
    for scale, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand")):
        if n >= scale:
            count, n = divmod(n, scale)
            parts.append(f"{_under_1000(count)} {name}")
    if n:
        parts.append(_under_1000(n))
    return " ".join(parts)


# --------------------------------------------------------------------------
# Prices -- trader shorthand, not arithmetic
# --------------------------------------------------------------------------


def _say_price_integer(n: int) -> str:
    """The integer part of a price, in the grouping traders use.

    The convention is to read a price as *pairs*, not as a magnitude:

    =======  ==========================  ============================
    Value    Trader                      Screen reader (wrong)
    =======  ==========================  ============================
    ``121``  one twenty-one              one hundred twenty-one
    ``1642`` sixteen forty-two           one thousand six hundred...
    ``545``  five forty-five             five hundred forty-five
    =======  ==========================  ============================

    Three digits split 1+2, four digits split 2+2. Below 100 there is nothing
    to group. Above five digits the shorthand stops being clearer than the
    plain cardinal, so it falls back.
    """
    if n < 100:
        return _under_100(n)
    if n < 1000:
        head, rest = divmod(n, 100)
        # 500 is "five hundred", not "five oh oh" -- the pair form only helps
        # when there is a non-zero remainder to pair with.
        if rest == 0:
            return f"{_ONES[head]} hundred"
        if rest < 10:
            return f"{_ONES[head]} oh {_ONES[rest]}"
        return f"{_ONES[head]} {_under_100(rest)}"
    if n < 10_000:
        head, rest = divmod(n, 100)
        if rest == 0:
            return f"{_under_100(head)} hundred"
        if rest < 10:
            return f"{_under_100(head)} oh {_ONES[rest]}"
        return f"{_under_100(head)} {_under_100(rest)}"
    return _cardinal(n)


def _say_cents(cents: str) -> str:
    """The fractional part of a price, given as its literal digits.

    ``06`` -> ``oh six``, ``40`` -> ``forty``, ``00`` -> ``""`` (dropped
    entirely -- ``1,642.00`` is *"sixteen forty-two"*, and saying "point zero
    zero" is noise the listener has to discard).
    """
    value = int(cents)
    if value == 0:
        return ""
    if len(cents) == 2 and value < 10:
        return f"oh {_ONES[value]}"
    if len(cents) == 2:
        return _under_100(value)
    # Three or more decimal places (FX, some futures): read digit by digit
    # rather than inventing a grouping convention that does not exist.
    return " ".join(_ONES[int(d)] for d in cents)


def say_price(value: Decimal | str | int) -> str:
    """A price, the way it is said on a desk.

    ``121.06`` -> *"one twenty-one oh six"*; ``1642.00`` -> *"sixteen
    forty-two"*; ``118.40`` -> *"one eighteen forty"*.
    """
    d = _to_decimal(value)
    sign = "negative " if d < 0 else ""
    d = abs(d)
    text = format(d, "f")
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0") if frac else ""
    if len(frac) == 1:
        frac += "0"  # .4 means forty cents, not four
    if int(whole) == 0 and frac:
        # Sub-dollar. There is no pair shorthand below a dollar, and "zero
        # fifty" is not something anyone says -- read the digits.
        return f"{sign}{_say_decimal_digits(d)}"
    spoken = _say_price_integer(int(whole))
    cents = _say_cents(frac) if frac else ""
    return f"{sign}{spoken} {cents}".strip()


# --------------------------------------------------------------------------
# The other quantities in the table
# --------------------------------------------------------------------------


def _say_decimal_digits(d: Decimal) -> str:
    """``0.72`` -> ``point seven two``. Digit by digit after the point."""
    text = format(d.normalize(), "f")
    _, _, frac = text.partition(".")
    return "point " + " ".join(_ONES[int(c)] for c in frac) if frac else ""


def _say_magnitude(d: Decimal) -> str:
    """A non-negative quantity as words, dropping a leading zero.

    Voice UX writes ``0.31%`` as *"point three one percent"* -- the ``zero`` is
    dead weight on a value the listener already knows is fractional.
    """
    whole = int(d)
    if d == whole:
        return _cardinal(whole)
    digits = _say_decimal_digits(d)
    return digits if whole == 0 else f"{_cardinal(whole)} {digits}"


def say_money(value: Decimal | str | int) -> str:
    """``$312`` -> *"three hundred twelve dollars"*.

    Dollars are a magnitude, not a price, so they take the plain cardinal --
    "three hundred twelve", never the "three twelve" price shorthand. Risk
    figures are the main caller and must not be mistakable for a price.
    """
    d = _to_decimal(value)
    sign = "minus " if d < 0 else ""
    d = abs(d)
    whole = int(d)
    cents = int((d - whole) * 100)
    # The unit agrees with the dollar count alone: "$1.50" is "one dollar
    # fifty", never "one dollars fifty". Cents do not make the dollar plural.
    unit = "dollar" if whole == 1 else "dollars"
    if not cents:
        return f"{sign}{_cardinal(whole)} {unit}"
    # Shares the price convention so "$1.05" is "one dollar oh five" rather
    # than "one dollar five", which a listener hears as $1.50.
    return f"{sign}{_cardinal(whole)} {unit} {_say_cents(f'{cents:02d}')}"


def say_percent(value: Decimal | str | int, *, directional: bool = True) -> str:
    """``-2.1%`` -> *"down two point one percent"*.

    ``directional`` renders sign as up/down, which is how a move is described.
    Set it False for a quantity that is not a move -- *"point three one percent
    of equity"* -- where "up" would be nonsense.
    """
    d = _to_decimal(value)
    magnitude = abs(d)
    body = _say_magnitude(magnitude)
    if not directional:
        return f"{body} percent"
    if d < 0:
        return f"down {body} percent"
    if d > 0:
        return f"up {body} percent"
    return f"{body} percent"


def say_r_multiple(value: Decimal | str | int) -> str:
    """``+1.2R`` -> *"plus one point two R"*. Sign is always spoken."""
    d = _to_decimal(value)
    body = _say_magnitude(abs(d))
    sign = "minus" if d < 0 else "plus"
    return f"{sign} {body} R"


def say_confidence(value: Decimal | str | float) -> str:
    """``0.72`` -> *"point seven two"*.

    Voice UX offers "seventy-two percent" as an alternative. Genesis says the
    decimal: confidence sits next to real percentages (risk, P&L) in the same
    sentence, and rendering it as a percent invites confusing a score with a
    money figure.
    """
    d = _to_decimal(value)
    if d >= 1:
        return _cardinal(int(d))
    return _say_decimal_digits(d)


def say_multiple(value: Decimal | str | int) -> str:
    """``2.4x`` -> *"two point four times"*."""
    d = _to_decimal(value)
    return f"{_say_magnitude(d)} times"


def say_time(text: str) -> str:
    """``08:30`` -> *"eight thirty"*; ``09:00`` -> *"nine o'clock"*."""
    hh, _, mm = text.partition(":")
    hour = int(hh)
    minute = int(mm)
    hour_12 = hour % 12 or 12
    if minute == 0:
        return f"{_ONES[hour_12]} o'clock"
    if minute < 10:
        return f"{_ONES[hour_12]} oh {_ONES[minute]}"
    return f"{_ONES[hour_12]} {_under_100(minute)}"


# --------------------------------------------------------------------------
# Ordinals, years and dates
# --------------------------------------------------------------------------
#
# A year is not a number, and a day of the month is not a count. ``1993`` read
# as a cardinal is *"one thousand nine hundred ninety-three"* -- which is not
# wrong so much as not English, and it takes three times as long to say as
# *"nineteen ninety-three"*. Same failure the module's opening docstring
# describes for prices: the wrong rendering is longer, harder to hear, and not
# the form the listener's ear is trained on.
#
# The hard part is not the arithmetic. It is knowing that ``1995`` is a year
# here and a share count there, which is why :func:`speakable` requires a
# positive signal before it treats a bare number as a year -- see
# :data:`_YEAR_CUES`.

_ORDINALS = (
    "zeroth", "first", "second", "third", "fourth", "fifth", "sixth",
    "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth",
    "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
    "eighteenth", "nineteenth",
)
_TENS_ORDINAL = (
    "", "", "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth",
    "seventieth", "eightieth", "ninetieth",
)

MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
)


def say_ordinal(n: int) -> str:
    """``5`` -> *"fifth"*; ``21`` -> *"twenty-first"*; ``30`` -> *"thirtieth"*."""
    if n < 0:
        raise ValueError(f"no ordinal for {n}")
    if n < 20:
        return _ORDINALS[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        if ones == 0:
            return _TENS_ORDINAL[tens]
        return f"{_TENS[tens]}-{_ORDINALS[ones]}"
    # Beyond a day of the month this is vanishingly rare; say the cardinal and
    # suffix it rather than inventing a rule nobody will hear used.
    return f"{_cardinal(n)}th"


def say_year(n: int) -> str:
    """``1993`` -> *"nineteen ninety-three"*; ``2026`` -> *"twenty twenty-six"*.

    The conventions people actually use, which are not one rule:

    ==========  =========================
    ``2000``    two thousand
    ``2005``    two thousand five
    ``2026``    twenty twenty-six
    ``1900``    nineteen hundred
    ``1905``    nineteen oh five
    ``1993``    nineteen ninety-three
    ==========  =========================

    Outside 1000-2999 it falls back to the cardinal, because *"three oh five"*
    for ``305`` would be a confident answer to a question nobody asked.
    """
    if not 1000 <= n <= 2999:
        return _cardinal(n)
    century, rest = divmod(n, 100)

    if rest == 0:
        # 2000 is "two thousand"; 1900 is "nineteen hundred". The difference is
        # whether the century is a round multiple of ten.
        if century % 10 == 0:
            return f"{_cardinal(century // 10)} thousand"
        return f"{_cardinal(century)} hundred"

    if century % 10 == 0:
        # The 2000s: "two thousand five", then "twenty twenty-six" from 2010.
        if rest < 10:
            return f"{_cardinal(century // 10)} thousand {_ONES[rest]}"
        return f"{_cardinal(century)} {_under_100(rest)}"

    if rest < 10:
        return f"{_cardinal(century)} oh {_ONES[rest]}"
    return f"{_cardinal(century)} {_under_100(rest)}"


def say_date(year: int | None, month: int, day: int | None) -> str:
    """Assemble a spoken date from parts that are already known.

    *"April fifth, nineteen ninety-three"*. The day is an ordinal because that
    is how a date is said aloud -- *"April five"* is how a form is read, not
    how a person speaks.
    """
    name = _MONTH_NAMES[month - 1]
    parts = name if day is None else f"{name} {say_ordinal(day)}"
    return parts if year is None else f"{parts}, {say_year(year)}"


# --------------------------------------------------------------------------
# Tickers
# --------------------------------------------------------------------------

#: Symbols said as words rather than spelled. Voice UX: *"Tickers are spelled
#: unless they're conventionally pronounced."* Deliberately short -- when in
#: doubt, spelling is always intelligible, whereas a wrong guess ("nividia")
#: is the failure the note calls out by name. Add only what a desk actually
#: says aloud.
PRONOUNCED_TICKERS: dict[str, str] = {
    "SPY": "spy",
    "QQQ": "cues",
    "VIX": "vix",
    "IWM": "russell",
    "DIA": "dia",
    "SPX": "S-P-X",
    "ES": "E-S",
    "NQ": "N-Q",
}


def say_ticker(symbol: str) -> str:
    """``NVDA`` -> *"N-V-D-A"*; ``SPY`` -> *"spy"*."""
    upper = symbol.upper()
    if upper in PRONOUNCED_TICKERS:
        return PRONOUNCED_TICKERS[upper]
    return "-".join(upper)


# --------------------------------------------------------------------------
# Whole-sentence rewriting
# --------------------------------------------------------------------------

#: Month names, longest first so ``June`` is not matched as ``Jun``.
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

#: Words that make a following 19xx/20xx a **year** rather than a quantity.
#:
#: This list is the whole reason dates are safe to speak in a trading system.
#: ``1995`` is a year in *"founded in 1995"* and a share count in *"sold 1995
#: shares"*, and nothing about the digits distinguishes them. So a bare number
#: is left alone unless something nearby says otherwise: the default stays the
#: cardinal, and a missing cue costs a clumsy reading rather than a wrong one.
#:
#: Deliberately excludes ``at``, ``to`` and ``of`` — *"filled at 2000"* is a
#: price, and reading it as a year would be exactly the failure this guards.
_YEAR_CUES = (
    "in|since|from|until|through|during|before|after|by"
    "|founded|established|incorporated|launched|circa"
    "|year|fiscal|FY|Q1|Q2|Q3|Q4"
)

_TOKEN = re.compile(
    rf"""
      (?P<money>\$-?\d[\d,]*(?:\.\d+)?)
    | (?P<percent>[-+]?\d[\d,]*(?:\.\d+)?%)
    | (?P<r>[-+]\d+(?:\.\d+)?R\b)
    | (?P<mult>\d+(?:\.\d+)?x\b)
    | (?P<iso>\b\d{{4}}-\d{{2}}-\d{{2}}\b)
    | (?P<usdate>\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b)
    | (?P<mdy>\b(?:{_MONTH_ALT})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b)
    | (?P<dmy>\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_ALT})\.?,?\s+\d{{4}}\b)
    | (?P<md>\b(?:{_MONTH_ALT})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b)
    | (?P<cueyear>\b(?:{_YEAR_CUES})\s+(?:19|20)\d{{2}}\b)
    | (?P<time>\b\d{{1,2}}:\d{{2}}\b)
    | (?P<ticker>\b[A-Z]{{1,5}}\b)
    | (?P<number>-?\d[\d,]*(?:\.\d+)?)
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: Groups above that must keep their case-sensitive meaning. ``_TOKEN`` is
#: IGNORECASE so month names match in any casing, which would otherwise make
#: every lowercase word a candidate ticker.
_CASE_SENSITIVE = ("ticker",)

_DATE_PARTS = re.compile(rf"({_MONTH_ALT})|(\d+)", re.IGNORECASE)


def _date_from(raw: str, *, order: str) -> str:
    """Pull month, day and year out of a matched date however it was written."""
    month = day = year = None
    numbers: list[int] = []
    for name, digits in _DATE_PARTS.findall(raw):
        if name:
            month = MONTHS[name.lower()]
        else:
            numbers.append(int(digits))
    if order == "iso":
        year, month, day = numbers[0], numbers[1], numbers[2]
    elif order == "us":
        month, day = numbers[0], numbers[1]
        year = numbers[2] if len(numbers) > 2 else None
        if year is not None and year < 100:  # 9/2/26
            year += 2000
    else:  # a month name carried the month; the digits are day and maybe year
        day = numbers[0] if numbers else None
        if len(numbers) > 1:
            year = numbers[1]
        if order == "dmy" and len(numbers) > 1:
            day, year = numbers[0], numbers[1]
    return say_date(year, month, day)

#: Uppercase words that are not tickers. Without this every ``R`` and ``NVDA
#: long`` sentence turns "OK" into "O-K".
_NOT_TICKERS = frozenset({
    "A", "I", "AM", "PM", "ET", "UTC", "OK", "R", "AND", "OR", "IF", "IN",
    "ON", "AT", "TO", "BY", "UP", "NO", "THE", "PNL", "USD",
})


def speakable(text: str) -> str:
    """Rewrite every number and ticker in ``text`` into spoken form.

    The orchestrator calls this on the last hop before TTS, so no path to the
    speakers can skip it::

        >>> speakable("NVDA long from 121.06, stop 118.40, risk $312 (0.31%)")
        'N-V-D-A long from one twenty-one oh six, stop one eighteen forty, ...'

    Bare decimals below 1 are read as confidence scores (*"point seven two"*)
    and bare numbers with cents as prices. That heuristic is why callers
    holding a known quantity should prefer the explicit ``say_*`` function --
    :func:`speakable` is for text already assembled into a sentence.
    """

    def replace(m: re.Match[str]) -> str:
        kind = m.lastgroup
        raw = m.group()
        try:
            if kind == "money":
                return say_money(raw[1:].replace(",", ""))
            if kind == "percent":
                return say_percent(raw[:-1].replace(",", ""), directional=raw[0] in "+-")
            if kind == "r":
                return say_r_multiple(raw[:-1])
            if kind == "mult":
                return say_multiple(raw[:-1])
            if kind == "iso":
                return _date_from(raw, order="iso")
            if kind == "usdate":
                return _date_from(raw, order="us")
            if kind in ("mdy", "md"):
                return _date_from(raw, order="mdy")
            if kind == "dmy":
                return _date_from(raw, order="dmy")
            if kind == "cueyear":
                # Keep the cue word; only the year is rewritten.
                cue, _, digits = raw.rpartition(" ")
                return f"{cue} {say_year(int(digits))}"
            if kind == "time":
                return say_time(raw)
            if kind == "ticker":
                if raw != raw.upper():
                    return raw  # IGNORECASE matched a lowercase word
                return raw if raw in _NOT_TICKERS else say_ticker(raw)
            if kind == "number":
                cleaned = raw.replace(",", "")
                d = _to_decimal(cleaned)
                if "." not in cleaned:
                    return _cardinal(int(abs(d))) if d >= 0 else f"negative {_cardinal(int(abs(d)))}"
                if abs(d) < 1:
                    return say_confidence(d)
                return say_price(cleaned)
        except (InvalidOperation, ValueError, IndexError):
            # Never let a malformed number silence the whole sentence: speaking
            # the raw token is worse than the convention but better than an
            # exception on the path to the speakers.
            return raw
        return raw

    return _TOKEN.sub(replace, text)


def _to_decimal(value: Decimal | str | int | float) -> Decimal:
    """Money is Decimal, never float -- the rule config.py enforces at the parser.

    A float argument is accepted (confidence scores legitimately arrive as
    floats) but is routed through ``str`` so ``0.1`` stays ``0.1``.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)
