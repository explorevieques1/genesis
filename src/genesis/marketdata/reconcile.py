# Spec: Genesis Markdown/10-Architecture/Market Data Sources.md
"""Two sources, same session, measured difference. The tier-1 gate.

Market Data Sources.md defines tier 1 as **execution truth** — the tier
[[Pre-Trade Risk Engine]] reads in Phase 7 and nothing else. Promoting a feed
to that tier because it connected successfully is precisely the drift between
believed and actual state that *proprioception before ambition* is about: the
system would then reason confidently about its own data quality and be wrong,
which is the failure mode that loses money quietly.

So promotion has a gate, and this module is it:

1. Pull the same session of the same contract from IBKR and from Databento.
2. Diff them, bar by bar, on the aligned timestamps.
3. Look at what did *not* align — that is usually the more informative half.
4. Decide a tolerance, **write the number into Market Data Sources.md**, and
   make it a test.
5. Then promote, in config, as a decision a person made on evidence.

**They will not match exactly, and that is not a failure.** The two feeds
aggregate differently and handle session boundaries differently. IBKR's
``TRADES`` bars exclude some trade conditions that Databento's MDP3 feed
includes; the two disagree about which side of a session boundary the 17:00 ET
break belongs to. A reconciliation that came back exact would mean the harness
was broken, not that the feeds were perfect.

What the number is *for*: it tells [[Pre-Trade Risk Engine]] how wide the
uncertainty band around a price is, which is what its conservative sizing
envelope needs. A tolerance nobody measured is a tolerance nobody can size
against.

Nothing here runs on a model. It is arithmetic over two sets of bars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from genesis.errors import DegradedError
from genesis.marketdata.interface import Adapter, BarRequest
from genesis.marketdata.normalize import Bar

__all__ = ["FieldStats", "Reconciliation", "reconcile", "reconcile_adapters"]


@dataclass(frozen=True)
class FieldStats:
    """How far apart two sources are on one field, in price units."""

    field: str
    n: int
    max_abs: Decimal
    mean_abs: Decimal
    #: Largest difference as a fraction of the price. The comparable number
    #: across instruments -- 0.25 on ES and 0.25 on ZN mean different things.
    max_rel: Decimal
    #: When the worst disagreement happened. Almost always the informative
    #: part: if every worst case is at a session boundary, the difference is
    #: an aggregation convention, not a data quality problem.
    worst_at: datetime | None

    @property
    def matches(self) -> bool:
        return self.max_abs == 0


@dataclass
class Reconciliation:
    """The measured difference between two sources over one window."""

    symbol_id: str
    timeframe: str
    start: datetime
    end: datetime
    source_a: str
    source_b: str
    #: Bars present in both, keyed on timestamp. Only these are compared.
    aligned: int
    #: Present in one and not the other. See :meth:`report` -- this is usually
    #: where the real story is.
    only_a: list[datetime] = field(default_factory=list)
    only_b: list[datetime] = field(default_factory=list)
    fields: dict[str, FieldStats] = field(default_factory=dict)

    @property
    def worst_abs(self) -> Decimal:
        """The largest absolute disagreement across the PRICE fields.

        Volume is excluded, and it has to be. The tolerance this feeds is
        expressed in price units -- "how many ticks apart are these feeds" --
        and volume disagreements are measured in thousands of contracts. One
        volume field would dominate the maximum permanently and make the
        tier-1 gate unpassable for a reason that has nothing to do with price
        accuracy.

        Volume still matters and is still measured; it is reported separately
        by :meth:`volume_gap` and printed by :meth:`report`. What it does not
        do is veto a promotion decision about prices.
        """
        prices = [
            stats.max_abs for name, stats in self.fields.items() if name != "volume"
        ]
        return max(prices, default=Decimal(0))

    @property
    def volume_gap(self) -> Decimal:
        """Largest volume disagreement, reported but never gating."""
        stats = self.fields.get("volume")
        return stats.max_abs if stats else Decimal(0)

    @property
    def worst_rel(self) -> Decimal:
        if not self.fields:
            return Decimal(0)
        return max(s.max_rel for s in self.fields.values())

    def within(self, tolerance: Decimal) -> bool:
        """Is every field inside ``tolerance``, in absolute price units?

        Alignment counts. A run where the two sources shared only a handful of
        timestamps can show a tiny price difference and mean nothing at all, so
        this refuses to call that a pass -- an unaligned reconciliation is not
        a lenient one, it is an absent one.
        """
        if self.aligned == 0:
            return False
        if self.only_a or self.only_b:
            return False
        return self.worst_abs <= tolerance

    def report(self) -> str:
        """The human-readable result, for the CLI and for pasting into the note."""
        lines = [
            f"{self.symbol_id} {self.timeframe} · "
            f"{self.start:%Y-%m-%d %H:%M} → {self.end:%Y-%m-%d %H:%M} UTC",
            f"  {self.source_a} vs {self.source_b}",
            f"  aligned bars: {self.aligned}",
        ]
        if self.only_a or self.only_b:
            lines.append(
                f"  UNALIGNED: {len(self.only_a)} only in {self.source_a}, "
                f"{len(self.only_b)} only in {self.source_b}"
            )
            for ts in self.only_a[:3]:
                lines.append(f"    only {self.source_a}: {ts:%Y-%m-%d %H:%M}")
            for ts in self.only_b[:3]:
                lines.append(f"    only {self.source_b}: {ts:%Y-%m-%d %H:%M}")
        for name, stats in self.fields.items():
            lines.append(
                f"  {name:<7} max |Δ| {stats.max_abs:>12} · "
                f"mean |Δ| {stats.mean_abs:>12} · "
                f"max rel {stats.max_rel:.2%}"
                + (f" · worst {stats.worst_at:%Y-%m-%d %H:%M}" if stats.worst_at else "")
            )
        lines.append(f"  → worst absolute PRICE difference: {self.worst_abs}")
        if self.volume_gap:
            lines.append(
                f"  → volume differs by up to {self.volume_gap} "
                f"(reported, not gating — the tolerance is in price units)"
            )
        return "\n".join(lines)


_FIELDS = ("open", "high", "low", "close", "volume")


def reconcile(
    a: Sequence[Bar],
    b: Sequence[Bar],
    *,
    source_a: str = "a",
    source_b: str = "b",
) -> Reconciliation:
    """Compare two bar sets on their shared timestamps.

    Alignment is on the timestamp alone, and unaligned bars are **reported, not
    dropped quietly**. Silently intersecting the two sets would turn "these
    feeds disagree about where a session starts" -- a real and important
    finding -- into a clean-looking pass over whatever happened to overlap.
    """
    if not a or not b:
        raise DegradedError(
            f"cannot reconcile: {source_a} has {len(a)} bars, "
            f"{source_b} has {len(b)}. Both sources must answer."
        )

    by_a = {bar.ts: bar for bar in a}
    by_b = {bar.ts: bar for bar in b}
    shared = sorted(by_a.keys() & by_b.keys())

    result = Reconciliation(
        symbol_id=a[0].symbol_id,
        timeframe=a[0].timeframe,
        start=min(min(by_a), min(by_b)),
        end=max(max(by_a), max(by_b)),
        source_a=source_a,
        source_b=source_b,
        aligned=len(shared),
        only_a=sorted(by_a.keys() - by_b.keys()),
        only_b=sorted(by_b.keys() - by_a.keys()),
    )

    for name in _FIELDS:
        diffs: list[tuple[Decimal, Decimal, datetime]] = []
        for ts in shared:
            left = getattr(by_a[ts], name)
            right = getattr(by_b[ts], name)
            absolute = abs(left - right)
            denominator = max(abs(left), abs(right))
            relative = absolute / denominator if denominator else Decimal(0)
            diffs.append((absolute, relative, ts))
        if not diffs:
            continue
        worst = max(diffs, key=lambda d: d[0])
        result.fields[name] = FieldStats(
            field=name,
            n=len(diffs),
            max_abs=worst[0],
            mean_abs=sum((d[0] for d in diffs), Decimal(0)) / len(diffs),
            max_rel=max(d[1] for d in diffs),
            worst_at=worst[2],
        )
    return result


def reconcile_adapters(
    adapter_a: Adapter,
    adapter_b: Adapter,
    symbol_id: str,
    timeframe: str,
    *,
    start: datetime,
    end: datetime,
) -> Reconciliation:
    """Pull the same window from two adapters and compare.

    Both are asked for the identical window, which matters: comparing IBKR's
    idea of "yesterday" with Databento's idea of "yesterday" would measure the
    two definitions of a day rather than the two feeds.
    """
    request = BarRequest(symbol_id=symbol_id, timeframe=timeframe, start=start, end=end)
    caps_a = adapter_a.capabilities()
    caps_b = adapter_b.capabilities()
    return reconcile(
        adapter_a.fetch(request),
        adapter_b.fetch(request),
        source_a=caps_a.name,
        source_b=caps_b.name,
    )
