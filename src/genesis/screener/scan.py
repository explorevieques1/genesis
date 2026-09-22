# Spec: Genesis Markdown/20-Agents/Research/Agent — Screener.md
"""A scan is data; running one is a filter. No model anywhere in this file.

The interpreter proposes a scan, :func:`validate` decides whether it exists.
Anything naming a field or operator outside the catalogue is rejected with the
reason -- never repaired by guessing -- so a hallucinated ``insider_buying``
field fails loudly instead of silently matching nothing.

**Absent never passes.** A criterion on a value the snapshot does not have
excludes the row and is counted, so "P/E under 15" says how many names had no
P/E rather than quietly shrinking the universe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from genesis.screener.snapshot import FIELDS, SECTORS, TEXT_FIELDS, Snapshot

__all__ = ["Criterion", "Scan", "ScanError", "describe", "expression", "parse_expression", "terms", "run", "validate"]

NUMERIC_OPS = ("<", "<=", ">", ">=", "between")
TEXT_OPS = ("=", "!=", "in", "contains")
DEFAULT_LIMIT = 50
#: Friday's close to Monday's close is ~72h, so a nightly snapshot is not stale
#: over a weekend. ponytail: ignores exchange holidays; a long weekend reads stale.
STALE_HOURS = 80


class ScanError(ValueError):
    """The scan names something that does not exist. ``problems`` says what."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Criterion:
    field: str
    op: str
    value: Any


@dataclass(frozen=True)
class Scan:
    criteria: tuple[Criterion, ...]
    sort: str | None = None
    descending: bool = True
    limit: int = DEFAULT_LIMIT

    def to_dict(self) -> dict[str, Any]:
        return {
            "criteria": [{"field": c.field, "op": c.op, "value": c.value} for c in self.criteria],
            "sort": {"field": self.sort, "direction": "desc" if self.descending else "asc"} if self.sort else None,
            "limit": self.limit,
        }


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError
    return float(str(value).rstrip("%").replace(",", ""))


def validate(raw: dict[str, Any]) -> Scan:
    """``{criteria: [{field, op, value}], sort, limit}`` -> :class:`Scan`, or :class:`ScanError`."""
    problems: list[str] = []
    criteria: list[Criterion] = []
    for item in raw.get("criteria") or []:
        name, op, value = item.get("field"), item.get("op"), item.get("value")
        if name in FIELDS:
            if op not in NUMERIC_OPS:
                problems.append(f"{name}: operator {op!r} is not one of {', '.join(NUMERIC_OPS)}")
                continue
            try:
                if op == "between":
                    lo, hi = sorted(_number(v) for v in value)
                    value = [lo, hi]
                else:
                    value = _number(value)
            except (ValueError, TypeError):
                problems.append(f"{name} {op}: {value!r} is not a number" + (" pair" if op == "between" else ""))
                continue
        elif name in TEXT_FIELDS:
            if op not in TEXT_OPS:
                problems.append(f"{name}: operator {op!r} is not one of {', '.join(TEXT_OPS)}")
                continue
            values = value if isinstance(value, list) else [value]
            if name == "sector":
                known = {s.lower(): s for s in SECTORS}
                unknown = [v for v in values if str(v).lower() not in known]
                if unknown and op != "contains":
                    problems.append(f"sector {unknown} is not one of {', '.join(SECTORS)}")
                    continue
            value = [str(v) for v in values] if op == "in" else str(values[0])
        else:
            problems.append(f"no field called {name!r}")
            continue
        criteria.append(Criterion(name, op, value))

    sort = raw.get("sort") or None
    sort_field, descending = None, True
    if sort:
        sort_field = sort.get("field") if isinstance(sort, dict) else str(sort)
        descending = not (isinstance(sort, dict) and sort.get("direction") == "asc")
        if sort_field not in FIELDS:
            problems.append(f"cannot sort by {sort_field!r}")
    try:
        limit = max(1, min(int(raw.get("limit") or DEFAULT_LIMIT), 500))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    if problems:
        raise ScanError(problems)
    return Scan(tuple(criteria), sort_field, descending, limit)


def _passes(c: Criterion, v: Any) -> bool:
    if c.field in FIELDS:
        return {
            "<": lambda: v < c.value, "<=": lambda: v <= c.value,
            ">": lambda: v > c.value, ">=": lambda: v >= c.value,
            "between": lambda: c.value[0] <= v <= c.value[1],
        }[c.op]()
    text = str(v).lower()
    if c.op == "in":
        return text in {x.lower() for x in c.value}
    if c.op == "contains":
        return str(c.value).lower() in text
    return (text == str(c.value).lower()) == (c.op == "=")


def run(scan: Scan, snapshot: Snapshot) -> dict[str, Any]:
    """Filter, sort, cut. Returns matches plus what was excluded for missing data."""
    matches: list[dict[str, Any]] = []
    missing: dict[str, int] = {}
    for row in snapshot.rows:
        for c in scan.criteria:
            if row.get(c.field) is None:
                missing[c.field] = missing.get(c.field, 0) + 1
                break
            if not _passes(c, row[c.field]):
                break
        else:
            matches.append(row)

    sort = scan.sort or next((c.field for c in scan.criteria if c.field in FIELDS), "market_cap_b")
    descending = scan.descending if scan.sort else True
    matches.sort(key=lambda r: (r.get(sort) is None, -(r.get(sort) or 0) if descending else (r.get(sort) or 0)))

    columns = list(dict.fromkeys([c.field for c in scan.criteria if c.field not in ("name",)] + [sort, "price", "market_cap_b"]))
    age = snapshot.age_hours()
    return {
        "count": len(matches),
        "universe": len(snapshot.rows),
        "columns": columns,
        "matches": [
            {k: r.get(k) for k in ["symbol", "name", "sector", *columns]} for r in matches[: scan.limit]
        ],
        "missing": missing,
        "as_of": snapshot.as_of,
        "degraded": age is None or age > STALE_HOURS,
    }


_OPS_WORD = {"<": "<", "<=": "≤", ">": ">", ">=": "≥", "=": "=", "!=": "≠", "in": "in", "contains": "contains"}


def describe(scan: Scan) -> str:
    parts = []
    for c in scan.criteria:
        unit = FIELDS[c.field][0] if c.field in FIELDS else ""
        suffix = "%" if unit == "%" else "B" if unit == "$B" else ""
        if c.op == "between":
            parts.append(f"{c.field} {c.value[0]:g}–{c.value[1]:g}{suffix}")
        elif isinstance(c.value, float):
            parts.append(f"{c.field} {_OPS_WORD[c.op]} {c.value:g}{suffix}")
        else:
            shown = ", ".join(c.value) if isinstance(c.value, list) else c.value
            parts.append(f"{c.field} {_OPS_WORD[c.op]} {shown}")
    if scan.sort:
        parts.append(f"sorted by {scan.sort} {'↓' if scan.descending else '↑'}")
    return " · ".join(parts) or "no criteria"


_TERM = re.compile(
    r"(?P<field>[a-z_0-9]+)\s*(?P<op><=|>=|!=|<|>|=|~)\s*(?P<value>.+?)"
    r"(?=\s+[a-z_0-9]+\s*(?:<=|>=|!=|<|>|=|~)|\s+(?:sort|top)\s*:|$)"
)


def parse_expression(text: str) -> dict[str, Any]:
    """``pe_trailing<20 revenue_growth>10 sector=technology sort:-market_cap_b top:20``.

    The typed door (Operating Model §1): everything the interpreter can build, a
    person can write by hand, and :func:`expression` writes any scan back out in
    this grammar. ``~`` is contains, ``!=`` excludes, ``a,b`` after ``=`` is
    *in*, ``lo..hi`` after ``=`` is *between*. Returns the raw dict for
    :func:`validate`, which does the refusing.
    """
    raw: dict[str, Any] = {"criteria": []}
    rest = text.strip()
    for key, pattern in (("sort", r"\bsort\s*:\s*(-?)([a-z_0-9]+)"), ("limit", r"\btop\s*:\s*(\d+)")):
        hit = re.search(pattern, rest)
        if hit:
            raw[key] = ({"field": hit.group(2), "direction": "desc" if hit.group(1) else "asc"}
                        if key == "sort" else int(hit.group(1)))
            rest = (rest[: hit.start()] + rest[hit.end():]).strip()
    for term in _TERM.finditer(rest):
        op = {"~": "contains"}.get(term.group("op"), term.group("op"))
        value: Any = term.group("value").strip()
        if op == "=" and ".." in value:
            op, value = "between", [v.strip() for v in value.split("..", 1)]
        elif op == "=" and "," in value:
            op, value = "in", [v.strip() for v in value.split(",") if v.strip()]
        raw["criteria"].append({"field": term.group("field"), "op": op, "value": value})
    return raw


def expression(scan: Scan) -> str:
    """A scan as the typed ``scr`` grammar -- the SCR panel's editable form of it."""
    return " ".join(terms(scan))


def terms(scan: Scan) -> list[str]:
    """One grammar term per criterion, then sort and top. The panel removes a
    criterion by dropping its term, never by re-parsing a string with spaces in it."""
    terms = []
    for c in scan.criteria:
        if c.op == "between":
            terms.append(f"{c.field}={c.value[0]:g}..{c.value[1]:g}")
        elif c.op == "in":
            terms.append(f"{c.field}={','.join(c.value)}")
        else:
            op = "~" if c.op == "contains" else c.op
            terms.append(f"{c.field}{op}{c.value:g}" if isinstance(c.value, float) else f"{c.field}{op}{c.value}")
    if scan.sort:
        terms.append(f"sort:{'-' if scan.descending else ''}{scan.sort}")
    if scan.limit != DEFAULT_LIMIT:
        terms.append(f"top:{scan.limit}")
    return terms
