# Spec: Genesis Markdown/50-Risk/Risk Envelope.md · 10-Architecture/Market Data Catalog.md
"""What this desk is allowed to trade, as a file rather than a network call.

The risk gate's allow-list check is a **reflex**: deterministic, sub-millisecond,
and it runs on every order. "All S&P 500 names and the liquid ETFs" cannot be
that check directly -- membership lives in a holdings file on SSGA's servers,
and a reflex that makes an HTTP request is not a reflex, it is a dependency with
a timeout. A gate that cannot answer is a gate that fails closed, which would
mean no order can be placed while a vendor is slow.

So membership is resolved **deliberately, in advance**, into one JSON file that
the config reads at load:

    genesis universe refresh      # fetch SPY's holdings, write the snapshot
    genesis universe show         # what is allowed, and how old it is

The gate keeps doing exactly what it did: a set membership test against a
literal list.

**Fail-closed on both edges.** A missing or unreadable snapshot yields the
configured futures roots and nothing else -- never "everything", and never an
empty list, which would refuse the futures this desk was already trading. A
stale snapshot is reported with its age rather than silently trusted: a company
removed from the index last week is a position nobody meant to be allowed to
open, and the honest answer is "this is 9 days old", not silence.

**"All ETFs" is not enumerable and this does not pretend otherwise.** There is
no free, authoritative list of every US ETF, and a guess would be an allow-list
with holes in it -- the worst shape for a safety control. :data:`CORE_ETFS` is
the liquid set a news brief actually names; anything else is added by hand, on
purpose, in the config.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["CORE_ETFS", "Universe", "load", "refresh"]

#: The ETFs a market brief names, plus the sector SPDRs. Deliberately a short
#: hand-kept list: see the module docstring on why "all ETFs" is not a thing
#: that can be enumerated honestly.
CORE_ETFS: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "DIA", "MDY", "RSP", "VOO", "VTI",
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY",
    "SMH", "SOXX", "XBI", "IBB", "ITB", "XHB", "XRT", "KRE", "XME", "JETS",
    "TLT", "IEF", "SHY", "HYG", "LQD", "TIP",
    "GLD", "SLV", "USO", "UNG", "DBC", "URA", "COPX", "GDX",
    "EEM", "EFA", "FXI", "EWZ", "EWJ", "INDA",
    "VIXY", "UVXY", "ARKK", "IYR", "VNQ",
)

#: A snapshot older than this is reported stale. Index membership changes a few
#: times a quarter, so a week is generous and a month is not.
STALE_AFTER_DAYS = 7


@dataclass(frozen=True)
class Universe:
    """The tradeable set, and where each part of it came from."""

    futures: tuple[str, ...]
    equities: tuple[str, ...]
    etfs: tuple[str, ...]
    #: ``{ticker: company name}`` for the equity half, from the holdings file.
    #: The only deterministic way to turn "Chevron" in a headline into `CVX`.
    names: dict[str, str] = field(default_factory=dict)
    as_of: str = ""
    source: str = ""
    #: Set when the equity half could not be loaded. The futures still trade.
    degraded: str = ""

    @property
    def symbols(self) -> tuple[str, ...]:
        """One flat list, which is all the gate's check wants."""
        return tuple(dict.fromkeys([*self.futures, *self.etfs, *self.equities]))

    @property
    def age_days(self) -> float | None:
        if not self.as_of:
            return None
        try:
            stamp = time.mktime(time.strptime(self.as_of[:10], "%Y-%m-%d"))
        except ValueError:
            return None
        return (time.time() - stamp) / 86400.0

    @property
    def stale(self) -> bool:
        age = self.age_days
        return age is not None and age > STALE_AFTER_DAYS

    def as_dict(self) -> dict[str, Any]:
        return {
            "futures": list(self.futures), "equities": list(self.equities),
            "etfs": list(self.etfs), "as_of": self.as_of, "source": self.source,
            "degraded": self.degraded, "count": len(self.symbols),
            "age_days": None if self.age_days is None else round(self.age_days, 1),
            "stale": self.stale,
        }


def path_for(config: Any) -> Path:
    """Beside the other state, never hardcoded to a home directory."""
    return Path(config.memory.db_path).expanduser().parent / "universe.json"


def load(config: Any, *, futures: tuple[str, ...] | None = None) -> Universe:
    """The allow-list this install trades. Never raises; degrades to futures.

    ``futures`` overrides the configured roots, which is only used by tests --
    everything else reads them from the risk envelope, so there is one source
    for the part of the list that must never depend on a file being present.
    """
    roots = tuple(futures if futures is not None else config.risk.symbol_allowlist)
    if not getattr(config.risk, "equity_universe", False):
        return Universe(futures=roots, equities=(), etfs=(), source="config")

    snapshot = path_for(config)
    try:
        data = json.loads(snapshot.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Universe(
            futures=roots, equities=(), etfs=tuple(CORE_ETFS), source="core-etfs",
            degraded=f"no universe snapshot at {snapshot} — run `genesis universe refresh`",
        )
    except (OSError, ValueError) as exc:
        return Universe(
            futures=roots, equities=(), etfs=tuple(CORE_ETFS), source="core-etfs",
            degraded=f"universe snapshot unreadable ({exc}) — futures and core ETFs only",
        )

    equities = tuple(str(s).upper() for s in data.get("equities") or ())
    names = {str(k).upper(): str(v) for k, v in (data.get("names") or {}).items()}
    etfs = tuple(str(s).upper() for s in data.get("etfs") or CORE_ETFS)
    return Universe(
        futures=roots, equities=equities, etfs=etfs, names=names,
        as_of=str(data.get("as_of") or ""), source=str(data.get("source") or "snapshot"),
    )


def refresh(config: Any, *, etfs: tuple[str, ...] = CORE_ETFS) -> Universe:
    """Fetch S&P 500 membership and write the snapshot. The network call, alone.

    Deliberately the *only* function here that touches the network, and nothing
    on the order path calls it. It is a person's command, or a maintenance
    workflow's step, and its result is a file.
    """
    from genesis.marketdata.index_map import _holdings

    holdings = _holdings("SPY")
    members = sorted(holdings["members"])
    if len(members) < 400:
        # A partial parse would quietly shrink the allow-list, and an allow-list
        # that shrank by accident refuses trades for a reason nobody can see.
        raise ValueError(
            f"SPY holdings parsed to {len(members)} members, which is too few to "
            f"be the S&P 500 — refusing to write a snapshot from it"
        )
    # Names as well as tickers. A news brief writes "Chevron", not "CVX", and
    # resolving one to the other is a lookup this file is the only honest
    # source for — Operating Model §4: nobody knows the ticker, least of all a
    # model asked to guess one.
    names = {ticker: name for ticker, (name, _weight) in holdings["members"].items()}
    snapshot = {
        # Normalised to ISO on the way in. SSGA writes `17-Sep-2026`, and a
        # snapshot whose date only this module can parse is a date nobody else
        # can compare -- including the staleness check two functions up, which
        # silently returned "unknown age" for every snapshot it ever wrote.
        "as_of": _iso(holdings.get("as_of")) or time.strftime("%Y-%m-%d"),
        "source": "SSGA SPY daily holdings",
        "equities": members,
        "etfs": list(etfs),
        "names": names,
    }
    out = path_for(config)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    return load(config)


def _iso(raw: Any) -> str:
    """`17-Sep-2026` or an ISO date, as an ISO date. Empty when neither."""
    text = str(raw or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return time.strftime("%Y-%m-%d", time.strptime(text, fmt))
        except ValueError:
            continue
    return ""
