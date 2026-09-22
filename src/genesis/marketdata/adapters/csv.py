# Spec: Genesis Markdown/10-Architecture/Market Data Plane.md
"""Deterministic replay from a CSV file.

Written first among the adapters, because it is the one that makes the other
three testable. Every property the plane claims -- write-once, supersede,
coverage, tier filtering, zero network calls on a second run -- has to be
provable without a vendor, a key, or a socket, and this is what provides that.

It is also the offline path. Market Data Plane.md's degradation table has a row
for "store corrupt / disk full" but the more common case in practice is simply
*no network*, and a CSV of yesterday's bars is the difference between a system
that works on a train and one that does not.

**Tier 3, and honestly so.** A CSV is exactly as trustworthy as whoever wrote
it, which the plane cannot know. It never claims better, so a level computed
from replayed bars is labelled tier 3 all the way to whatever speaks it.
"""

from __future__ import annotations

import csv as _csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from genesis.errors import DegradedError
from genesis.marketdata.interface import AdapterCapabilities, BarRequest
from genesis.marketdata.normalize import Bar, normalise_bars, utc

__all__ = ["CsvAdapter"]

#: Column spellings seen in the wild, lowercased. The same permissiveness
#: charting/bars.py applies to vendor JSON, for the same reason: the shapes
#: genuinely differ and the place to absorb that is one module, not five.
_ALIASES = {
    "ts": ("ts", "time", "date", "datetime", "timestamp"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c", "adj close", "adj_close"),
    "volume": ("volume", "vol", "v"),
}


@dataclass
class CsvAdapter:
    """Bars from ``{root}/{symbol_id}/{timeframe}.csv``.

    The symbol id goes into the path with ``:`` replaced by ``_``, because a
    colon is legal in a filename on Linux and a minefield everywhere else, and
    a replay fixture that only works on one OS is a fixture that will break in
    CI.
    """

    root: Path
    tier: int = 3
    name: str = "csv"
    adjusted: bool = False
    #: Counts every read. Tests assert on it; it costs nothing and it is the
    #: only way to prove "the second run touched no source" from outside.
    reads: int = field(default=0, init=False)

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name=self.name,
            tier=self.tier,
            timeframes=frozenset(
                {"1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"}
            ),
            asset_classes=frozenset({"EQ", "FUT", "IDX", "FX", "CRYPTO"}),
            # No pacing at all: a local file has no quota, and inventing one
            # would make tests slow for no safety gain.
            pacing=(),
            adjusted=self.adjusted,
            serves_expired_contracts=True,
            supports_streaming=False,
            requires_session=False,
        )

    def path_for(self, symbol_id: str, timeframe: str) -> Path:
        return Path(self.root) / symbol_id.replace(":", "_") / f"{timeframe}.csv"

    def fetch(self, request: BarRequest) -> Sequence[Bar]:
        path = self.path_for(request.symbol_id, request.timeframe)
        if not path.exists():
            raise DegradedError(
                f"no replay file at {path} for {request.symbol_id} "
                f"{request.timeframe}"
            )
        self.reads += 1
        rows: list[dict[str, object]] = []
        with path.open(newline="") as handle:
            reader = _csv.DictReader(handle)
            if reader.fieldnames is None:
                raise DegradedError(f"{path}: empty file, no header")
            columns = _map_columns(reader.fieldnames, path)
            for line in reader:
                ts = utc(line[columns["ts"]])
                # Half-open, matching BarRequest: start <= ts < end.
                if ts < request.start or ts >= request.end:
                    continue
                rows.append(
                    {
                        "ts": ts,
                        "open": line[columns["open"]],
                        "high": line[columns["high"]],
                        "low": line[columns["low"]],
                        "close": line[columns["close"]],
                        "volume": line.get(columns.get("volume", ""), 0) or 0,
                    }
                )
        return normalise_bars(
            rows,
            symbol_id=request.symbol_id,
            timeframe=request.timeframe,
            source=self.name,
            tier=self.tier,
            adjusted=self.adjusted,
        )


def _map_columns(fieldnames: Sequence[str], path: Path) -> dict[str, str]:
    """Header -> our field names. Raises on a missing OHLC column.

    Volume is optional; OHLC is not. A missing close is not a zero and not a
    forward-fill -- it is a file this adapter will not read, per
    Conventions.md §Errors.
    """
    lowered = {name.strip().lower(): name for name in fieldnames}
    out: dict[str, str] = {}
    for field_name, spellings in _ALIASES.items():
        for spelling in spellings:
            if spelling in lowered:
                out[field_name] = lowered[spelling]
                break
    missing = {"ts", "open", "high", "low", "close"} - out.keys()
    if missing:
        raise DegradedError(
            f"{path}: missing column(s) {sorted(missing)}; "
            f"header was {list(fieldnames)}"
        )
    return out
