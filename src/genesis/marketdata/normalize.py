# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""One bar schema, one symbol id, UTC, provenance stamped.

Market Data Plane.md puts this module between every adapter and the store, and
Build sequence step 1 says why it is written *first*: "the value is that the
schema and the provenance stamps are right on day one, because retrofitting
them across a year of accumulated history is painful." Everything else in this
package depends on the shapes here, so they are the decisions worth being slow
about.

Four of them are load-bearing.

**The timestamp is the bar's OPEN, always, in UTC.** Vendors disagree: Databento
stamps the open, yfinance stamps the open in exchange-local time, IBKR stamps
the open but formats it in the account's timezone. A store that mixes the two
conventions is off by one bar in a way that never raises and quietly ruins
every backtest -- the model buys on a bar it could not have seen. So the
convention is stated once, here, and every adapter converts to it.

**Prices are Decimal.** Conventions.md §Money is not negotiable, and futures are
where float would first bite: ES trades in quarter points, and 4512.25 is not
representable in binary floating point. The store holds Decimal. The conversion
to float happens in exactly one place -- :mod:`genesis.marketdata.source`, on
the way out to :class:`~genesis.charting.bars.Bars`, which is a drawing buffer
and not the money truth.

**Provenance is on the row.** ``source``, ``tier``, ``as_of`` and ``ingested_at``
travel with every bar because Market Data Sources requires that a tier-3 bar
never silently satisfy a tier-2 request, and that is enforceable only if the
tier outlives the cache it arrived in.

**A symbol id says what kind of thing it is.** See :func:`instrument_id`. This
is the one that Open Questions §13 is about, and the one that is close to
unrecoverable if it is wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from genesis.charting.timeframes import normalise as normalise_timeframe
from genesis.errors import DegradedError

__all__ = [
    "ASSET_CLASSES",
    "Bar",
    "Instrument",
    "MONTH_CODES",
    "NormalizeError",
    "continuous_id",
    "instrument_id",
    "normalise_bars",
    "parse_instrument_id",
    "to_decimal",
    "utc",
]


class NormalizeError(DegradedError):
    """A vendor payload could not be made into our shape.

    ``degraded`` rather than ``fatal`` for the same reason
    :class:`~genesis.charting.bars.BarParseError` is: one unreadable vendor
    response is a reason to fall down the chain, not a reason to stop. What it
    must never be is a bar with a guessed field.
    """


#: What a symbol id's first segment may say. Deliberately short and closed --
#: an open vocabulary here becomes four spellings of "future" within a year.
ASSET_CLASSES = ("EQ", "FUT", "CONT", "IDX", "FX", "CRYPTO")

#: The exchange month codes. Futures identity is a month, and every vendor
#: spells the month differently: Databento says ``ESZ5``, IBKR says
#: ``lastTradeDateOrContractMonth=202512``, a person says "December ES". One
#: table, because three tables is three tables that disagree.
MONTH_CODES: dict[str, int] = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}
_CODE_BY_MONTH = {v: k for k, v in MONTH_CODES.items()}


# --------------------------------------------------------------------------
# Symbol identity
# --------------------------------------------------------------------------
#
# Open Questions §13 states the problem: ``ES``, ``ESZ6``, ``ES1!`` and a
# back-adjusted continuous series are four different things, and a store that
# calls them all "ES" corrupts every backtest silently.
#
# The scheme below makes the distinction structural rather than conventional --
# you cannot write a continuous series into a dated contract's id by accident,
# because they do not have the same number of segments.
#
#   EQ:XNAS:AAPL                 an equity, MIC-qualified
#   FUT:CME:ES:2025-12           ONE dated contract. Unambiguous forever.
#   CONT:CME:ES:volume:back      a continuous series -- RESERVED, see below
#   IDX:CBOE:VIX                 an index
#
# Only the dated form is written this session. `continuous_id` exists to fix
# the *spelling* of the thing we are not yet building, so that when §13 is
# answered the answer has somewhere to go that does not collide with history
# already accumulated. A continuous series is a *derived* product with a roll
# rule and an adjustment method baked into it, and those two choices belong in
# the id, because a back-adjusted-on-volume ES and a ratio-adjusted-on-OI ES
# are different price series that must never share a key.


def instrument_id(
    asset_class: str,
    exchange: str,
    root: str,
    *,
    contract_month: str | None = None,
) -> str:
    """Build a canonical symbol id.

    ``contract_month`` is ``YYYY-MM`` and is required for ``FUT`` -- a dated
    contract without its month is the ambiguity this whole scheme exists to
    prevent, so it raises rather than defaulting to the front month.
    """
    asset_class = asset_class.upper()
    if asset_class not in ASSET_CLASSES:
        raise NormalizeError(f"unknown asset class {asset_class!r}")
    if asset_class == "CONT":
        raise NormalizeError(
            "continuous contracts are not implemented -- Open Questions §13 is "
            "unanswered. Store dated contracts; see continuous_id()."
        )
    exchange = exchange.upper()
    root = root.upper()
    if asset_class == "FUT":
        if not contract_month:
            raise NormalizeError(
                f"{root}: a futures id needs a contract month. "
                f"'ES' alone is not an instrument -- it is a family."
            )
            # Never guess the front month here. The front month is a function
            # of *today*, so an id built from it means yesterday's id and
            # today's id name different contracts. That is the silent
            # corruption Open Questions §13 warns about, arriving through the
            # side door.
        if not re.fullmatch(r"\d{4}-\d{2}", contract_month):
            raise NormalizeError(
                f"contract month {contract_month!r} is not YYYY-MM"
            )
        return f"FUT:{exchange}:{root}:{contract_month}"
    return f"{asset_class}:{exchange}:{root}"


def continuous_id(
    exchange: str, root: str, roll: str, adjustment: str
) -> str:
    """The id a continuous series *would* have. Not yet writable.

    Present so that the spelling is decided before the data is, and so that
    :func:`parse_instrument_id` can recognise one if it ever meets one. The
    store refuses to write these until Open Questions §13 is answered.
    """
    return f"CONT:{exchange.upper()}:{root.upper()}:{roll}:{adjustment}"


@dataclass(frozen=True)
class Instrument:
    """What a symbol id means, unpacked.

    ``multiplier`` and ``tick_size`` are here rather than in a separate
    reference table because futures arithmetic is wrong without them and the
    wrongness is invisible: an ES point is $50, an NQ point is $20, and a P&L
    computed without the multiplier is a plausible number that is off by a
    factor of fifty.
    """

    symbol_id: str
    asset_class: str
    exchange: str
    root: str
    contract_month: str | None = None
    #: What the vendor calls it. Kept so a request can be replayed against the
    #: vendor that answered it, and so a mis-mapping is debuggable rather than
    #: mysterious.
    vendor_symbol: str | None = None
    multiplier: Decimal | None = None
    tick_size: Decimal | None = None
    currency: str = "USD"

    @property
    def is_future(self) -> bool:
        return self.asset_class == "FUT"

    @property
    def is_continuous(self) -> bool:
        return self.asset_class == "CONT"

    @property
    def month_code(self) -> str | None:
        """``2025-12`` -> ``Z5``. The spelling Databento and CME use."""
        if not self.contract_month:
            return None
        year, month = self.contract_month.split("-")
        return f"{_CODE_BY_MONTH[int(month)]}{year[-1]}"


def parse_instrument_id(symbol_id: str) -> Instrument:
    """Inverse of :func:`instrument_id`. Raises on anything unparseable."""
    parts = symbol_id.split(":")
    if len(parts) < 3:
        raise NormalizeError(f"not a symbol id: {symbol_id!r}")
    kind = parts[0].upper()
    if kind not in ASSET_CLASSES:
        raise NormalizeError(f"unknown asset class in {symbol_id!r}")
    if kind == "FUT":
        if len(parts) != 4:
            raise NormalizeError(
                f"{symbol_id!r}: a futures id is FUT:exchange:root:YYYY-MM"
            )
        # The same validation `instrument_id` applies on the way in. Without
        # it the two disagree: building "FUT:CME:ES:banana" raises, parsing it
        # succeeds -- so an id that could never be constructed can still be
        # read back out of a store or a config file and used.
        if not re.fullmatch(r"\d{4}-\d{2}", parts[3]):
            raise NormalizeError(
                f"{symbol_id!r}: contract month {parts[3]!r} is not YYYY-MM"
            )
        if not 1 <= int(parts[3][5:]) <= 12:
            raise NormalizeError(
                f"{symbol_id!r}: {parts[3]!r} is not a real month"
            )
        return Instrument(symbol_id, kind, parts[1], parts[2], contract_month=parts[3])
    if kind == "CONT":
        if len(parts) != 5:
            raise NormalizeError(
                f"{symbol_id!r}: a continuous id is CONT:exchange:root:roll:adjustment"
            )
        return Instrument(symbol_id, kind, parts[1], parts[2])
    return Instrument(symbol_id, kind, parts[1], parts[2])


# --------------------------------------------------------------------------
# The bar
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Bar:
    """One closed OHLCV bar, with everything needed to trust it later.

    Immutable, and the store treats it as such: a closed bar is written once
    and never updated. A vendor that restates one does not overwrite it -- the
    old row is moved aside and both are kept, because a history that changes
    under a backtest invalidates the backtest without telling anyone.
    """

    symbol_id: str
    timeframe: str
    #: The bar's OPEN, in UTC. See the module docstring -- this convention is
    #: the difference between a correct backtest and a lookahead bug.
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    #: Provenance. Every one of these is a column in the store.
    source: str = "unknown"
    tier: int = 3
    #: When the vendor says this data was current. For a closed bar this is
    #: normally the bar's close; it differs for a restatement, which is exactly
    #: when you need to know.
    as_of: datetime | None = None
    ingested_at: datetime | None = None
    adjusted: bool = False

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise NormalizeError(
                f"{self.symbol_id} {self.ts}: naive timestamp. "
                f"A bar without a timezone is a bar in an unknown session."
            )
        if self.high < self.low:
            raise NormalizeError(
                f"{self.symbol_id} {self.ts}: high {self.high} below low {self.low}"
            )
        # Deliberately NOT checking open/close within [low, high]. Some vendors
        # report a settlement close outside the traded range, legitimately, and
        # rejecting those would discard real data to satisfy a tidiness rule.
        # high < low is different: it cannot be true, so it is a parse failure.

    @property
    def key(self) -> tuple[str, str, datetime]:
        """What makes a bar the same bar. The store's primary key."""
        return (self.symbol_id, self.timeframe, self.ts)

    def stamped(self, *, ingested_at: datetime | None = None) -> Bar:
        """A copy with ingest provenance filled in, applied on write."""
        return replace(self, ingested_at=ingested_at or datetime.now(UTC))


# --------------------------------------------------------------------------
# Conversion helpers
# --------------------------------------------------------------------------


def utc(value: Any) -> datetime:
    """Anything a vendor calls a timestamp, as an aware UTC datetime.

    Naive datetimes are **assumed UTC and not silently localised**. Every
    adapter is required to localise before it gets here, because only the
    adapter knows the vendor's convention -- guessing at this layer is how a
    session boundary moves by five hours.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        # Vendors use seconds, milliseconds and nanoseconds, and the only
        # reliable discriminator is magnitude. 1e11 seconds is the year 5138;
        # 1e11 milliseconds is 1973. The thresholds are chosen so every
        # plausible market timestamp lands in the right branch.
        v = float(value)
        if v > 1e17:
            dt = datetime.fromtimestamp(v / 1e9, tz=UTC)
        elif v > 1e11:
            dt = datetime.fromtimestamp(v / 1e3, tz=UTC)
        else:
            dt = datetime.fromtimestamp(v, tz=UTC)
    elif isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise NormalizeError(f"unparseable timestamp {value!r}") from exc
    elif hasattr(value, "to_pydatetime"):  # pandas Timestamp
        dt = value.to_pydatetime()
    else:
        raise NormalizeError(f"unparseable timestamp {value!r}")
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def to_decimal(value: Any, *, field: str = "price") -> Decimal:
    """A vendor number as Decimal, via ``str`` so float noise never enters.

    ``Decimal(4512.25)`` from a float carries the binary representation error
    into the store permanently. ``Decimal(str(4512.25))`` does not. The
    round-trip through ``str`` is the whole point and is not an inefficiency
    worth removing.
    """
    if value is None:
        raise NormalizeError(f"missing {field} -- refusing to invent one")
    if isinstance(value, Decimal):
        return value
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizeError(f"{field} {value!r} is not a number") from exc
    if not dec.is_finite():
        raise NormalizeError(f"{field} is {value!r}; a bar cannot hold NaN or inf")
    return dec


def normalise_bars(
    rows: Iterable[dict[str, Any]],
    *,
    symbol_id: str,
    timeframe: str,
    source: str,
    tier: int,
    adjusted: bool = False,
    as_of: datetime | None = None,
) -> list[Bar]:
    """Vendor rows -> canonical bars, sorted, deduplicated, provenance stamped.

    Every adapter ends here. Sorting is done rather than assumed, for the
    reason :mod:`genesis.charting.bars` gives: bars arrive out of order often
    enough to matter and everything downstream assumes chronological order.

    Duplicate timestamps within one payload are a vendor bug, and the last one
    wins with no complaint -- vendors legitimately resend a bar within a single
    response. A duplicate across two *fetches* is a different matter entirely
    and is handled by the store, which can see the earlier value.
    """
    tf = normalise_timeframe(timeframe)
    now = datetime.now(UTC)
    by_ts: dict[datetime, Bar] = {}
    for row in rows:
        ts = utc(row["ts"] if "ts" in row else row["time"])
        by_ts[ts] = Bar(
            symbol_id=symbol_id,
            timeframe=tf,
            ts=ts,
            open=to_decimal(row["open"], field="open"),
            high=to_decimal(row["high"], field="high"),
            low=to_decimal(row["low"], field="low"),
            close=to_decimal(row["close"], field="close"),
            volume=to_decimal(row.get("volume", 0), field="volume"),
            source=source,
            tier=tier,
            as_of=as_of or ts,
            ingested_at=now,
            adjusted=adjusted,
        )
    return [by_ts[k] for k in sorted(by_ts)]
