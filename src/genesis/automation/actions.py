# Spec: Genesis Markdown/60-UI/Automation.md §Node library
"""The built-in nodes: what a workflow step can do beyond calling a tool.

Every action is defined once, here, with its category, its settings and the
function that runs it. The canvas's palette and inspector are generated from
this table (``/v1/automation/catalog``), so a node the UI offers is a node the
runtime can run -- there is no second list to drift.

Rules every action keeps:

- **Deterministic, tier none.** Signals compute from bars with
  :mod:`genesis.charting.indicators`; gates read the market calendar. No model
  sizes, compares or decides anything in this file. Judgement is dispatched to
  an agent (the ``agent.*`` actions), which already owns its model.
- **Reads and writes are visibly different.** An action that changes something
  outside the run -- an alert, a note, a watchlist -- is ``writes=True``; the
  canvas badges it, and it is the only kind that leaves a mark.
- **No order path.** Nothing here imports execution or risk code, and no action
  can reach a broker. ``tests/automation/test_import_graph.py`` loads this
  module and checks.
- **No expression language.** Settings are closed choices and plain values.
  Text templates fill named slots (``{symbol}``, ``{count}``) and nothing else.

Heavy imports (numpy, yfinance, stores) are inside the run functions, so the
schema validator can import this table cheaply.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

__all__ = ["ACTIONS", "CATEGORIES", "Action", "Fail", "Param", "Stop", "items_of", "validate_params"]


class Fail(Exception):
    """The step did not pass. On a branching step this takes the fail edge."""


class Stop(Exception):
    """End the run here, successfully."""


CATEGORIES: tuple[tuple[str, str], ...] = (
    ("triggers", "Triggers"),
    ("market", "Market data"),
    ("signals", "Signals & alerts"),
    ("news", "News & sentiment"),
    ("fundamentals", "Fundamentals & analysts"),
    ("filings", "SEC filings"),
    ("calendar", "Calendars & macro"),
    ("screeners", "Screeners"),
    ("technicals", "Technical analysis"),
    ("research", "Research & agents"),
    ("journal", "Journal & performance"),
    ("watchlist", "Watchlists"),
    ("logic", "Logic & flow"),
    ("transform", "Transform data"),
    ("output", "Output & notify"),
    ("maintenance", "Maintenance"),
    ("custom", "Custom & processes"),
)


@dataclass(frozen=True)
class Param:
    name: str
    type: str  # text textarea number integer symbol symbols select multiselect bool time workflow watchlist
    label: str
    required: bool = False
    default: Any = None
    options: tuple[str, ...] = ()
    help: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "label": self.label,
                "required": self.required, "default": self.default,
                "options": list(self.options), "help": self.help}


@dataclass(frozen=True)
class Action:
    id: str
    category: str
    label: str
    description: str
    run: Callable[[Any, dict[str, Any], dict[str, Any] | None], dict[str, Any]]
    params: tuple[Param, ...] = ()
    #: Has a pass and a fail exit on the canvas.
    branches: bool = False
    #: Changes something outside the run.
    writes: bool = False
    #: The param filled from each input item when "repeat for each" is on.
    each: str | None = None
    #: Needs an input step to do anything.
    needs_input: bool = False
    #: A judgement node runs a model (LLM Model Tiers). The compiled workflow
    #: declares the highest tier among its nodes, so the body map stays honest.
    model_tier: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "category": self.category, "label": self.label,
                "description": self.description, "params": [p.to_dict() for p in self.params],
                "branches": self.branches, "writes": self.writes, "each": self.each,
                "needs_input": self.needs_input, "model_tier": self.model_tier}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def out(text: str = "", structured: Any = None, items: list[Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"text": text[:4000], "structured": structured}
    if items is not None:
        body["items"] = items[:500]
    return body


def items_of(output: dict[str, Any] | None) -> list[Any]:
    """The list inside a step's output: ``items``, a list payload, or the first list in a dict."""
    if not output:
        return []
    if isinstance(output.get("items"), list):
        return output["items"]
    structured = output.get("structured")
    if isinstance(structured, list):
        return structured
    if isinstance(structured, dict):
        for value in structured.values():
            if isinstance(value, list):
                return value
    return []


def symbol_of(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip().upper() or None
    if isinstance(item, dict):
        for key in ("symbol", "ticker", "Symbol", "Ticker"):
            if item.get(key):
                return str(item[key]).strip().upper()
    return None


def get_field(obj: Any, path: str) -> Any:
    """Dotted keys into dicts, e.g. ``quote.change_pct``. Missing is None."""
    for part in (path or "").split("."):
        if not part:
            continue
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


def _rendered(value: Any, ctx: Any, data: dict[str, Any] | None) -> Any:
    """Fill slots in a setting that may also arrive as a list."""
    return render(value, ctx, data) if isinstance(value, str) else value


def _symbols(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    return [s for s in (symbol_of(v) for v in (value or [])) if s]


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op in ("==", "!="):
        same = str(actual).strip().lower() == str(expected).strip().lower()
        try:
            same = same or float(actual) == float(expected)
        except (TypeError, ValueError):
            pass
        return same if op == "==" else not same
    try:
        a, b = float(actual), float(expected)
    except (TypeError, ValueError):
        # Fail closed: a value that is not a number does not pass a comparison.
        return False
    if math.isnan(a):
        return False
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]


_SLOT = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render(template: str, ctx: Any, data: dict[str, Any] | None) -> str:
    """Fill ``{slot}`` names from the input. Unknown slots stay as typed.

    A regex over bare names, not ``str.format``: format strings allow
    ``{text.__class__}`` and indexing, which is an expression language by the
    back door.
    """
    data = data or {}
    items = items_of(data)
    structured = data.get("structured")
    slots: dict[str, Any] = {}
    if isinstance(structured, dict):
        slots.update({k: v for k, v in structured.items() if isinstance(v, (str, int, float))})
    today = ctx.now.astimezone(ctx.tz).date()
    slots.update(
        workflow=ctx.workflow.name,
        date=today.isoformat(),
        yesterday=(today - timedelta(days=1)).isoformat(),
        tomorrow=(today + timedelta(days=1)).isoformat(),
        week_ago=(today - timedelta(days=7)).isoformat(),
        week_ahead=(today + timedelta(days=7)).isoformat(),
        time=ctx.now.astimezone(ctx.tz).strftime("%H:%M"),
        count=len(items),
        # Generous: a written review flows through {text} into a note. Alerts cap
        # their own message length where they are stored.
        text=str(data.get("text") or "")[:50000],
        symbols=", ".join(s for s in (symbol_of(i) for i in items) if s),
        items="\n".join(f"- {_line(i)}" for i in items[:25]),
    )
    return _SLOT.sub(lambda m: str(slots[m.group(1)]) if m.group(1) in slots else m.group(0), template or "")


def _line(item: Any) -> str:
    """One readable line for an item in {items}: who, then the most telling field."""
    if not isinstance(item, dict):
        return str(item)
    who = symbol_of(item) or item.get("item") or item.get("company_name") or item.get("release_name") \
        or item.get("title") or item.get("name") or ""
    parts = []
    for key, fmt in (("headline", "{}"), ("title", "{}"), ("change_pct", "{:+}%"), ("percent_change", "{:+.1%}"),
                     ("form_type", "form {}"), ("filing_date", "filed {}"), ("earnings_date", "earnings {}"),
                     ("date", "{}"), ("close", "@ {}"), ("price", "@ {}"), ("value", "= {}")):
        value = item.get(key)
        if value in (None, "") or str(value) == str(who):
            continue
        try:
            parts.append(fmt.format(value))
        except (ValueError, TypeError):
            parts.append(str(value))
        if len(parts) == 2:
            break
    line = f"{who} {' · '.join(parts)}".strip()
    return line or json.dumps(item, default=str)[:160]


def _memory_dir():  # noqa: ANN202
    from pathlib import Path

    from genesis.config import load_config

    return Path(load_config().memory.db_path).expanduser().parent


def _bars(symbol: str, timeframe: str, count: int):  # noqa: ANN202
    from genesis.config import load_config
    from genesis.marketdata.build import build_source

    bars = build_source(load_config(), "default").source.fetch(symbol, timeframe, bars=count)
    if len(bars) == 0:
        raise Fail(f"no {timeframe} bars for {symbol}")
    return bars


def _quote(symbol: str) -> dict[str, Any]:
    from genesis.marketdata.quotes import day_quotes

    sym = symbol.strip().upper()
    quote = day_quotes([sym]).get(sym) or {"error": "no quote"}
    if "error" in quote:
        raise Fail(f"{sym}: {quote['error']}")
    return {"symbol": sym, **quote}


# ---------------------------------------------------------------------------
# market data & signals
# ---------------------------------------------------------------------------


def _market_quote(ctx, p, data):  # noqa: ANN001, ANN202
    q = _quote(p["symbol"])
    return out(f"{q['symbol']} {q['close']} ({q['change_pct']:+}%) as of {q['as_of']}", q)


def _watchlist_quotes(ctx, p, data):  # noqa: ANN001, ANN202
    from genesis.marketdata.quotes import day_quotes

    symbols = _watchlist_symbols(p["watchlist"])
    quotes = day_quotes(symbols)
    rows = [{"symbol": s, **quotes.get(s, {"error": "no quote"})} for s in symbols]
    good = [r for r in rows if "error" not in r]
    return out(f"{len(good)} of {len(rows)} quoted", {"quotes": rows}, rows)


def _bars_summary(ctx, p, data):  # noqa: ANN001, ANN202
    bars = _bars(p["symbol"], p.get("timeframe") or "1D", int(p.get("bars") or 100))
    close = float(bars.close[-1])
    first = float(bars.close[0])
    body = {"symbol": p["symbol"].upper(), "timeframe": bars.timeframe, "bars": len(bars),
            "close": round(close, 4), "high": round(float(bars.high.max()), 4),
            "low": round(float(bars.low.min()), 4),
            "change_pct": round((close - first) / first * 100, 2) if first else None,
            "last_bar": bars.times[-1].isoformat(), "source": bars.source}
    return out(f"{body['symbol']} {len(bars)} {bars.timeframe} bars, close {close:g}", body)


def _signal_price(ctx, p, data):  # noqa: ANN001, ANN202
    q = _quote(p["symbol"])
    op = ">" if p.get("direction", "above") == "above" else "<"
    hit = _compare(q["close"], op, p["level"])
    text = f"{q['symbol']} {q['close']} is {'' if hit else 'not '}{p.get('direction', 'above')} {p['level']:g}"
    if not hit:
        raise Fail(text)
    return out(text, q)


def _signal_move(ctx, p, data):  # noqa: ANN001, ANN202
    q = _quote(p["symbol"])
    move = float(q.get("change_pct") or 0)
    threshold = abs(float(p["percent"]))
    direction = p.get("direction", "either")
    hit = (move >= threshold if direction == "up" else move <= -threshold if direction == "down"
           else abs(move) >= threshold)
    text = f"{q['symbol']} moved {move:+.2f}% today (threshold {direction} {threshold:g}%)"
    if not hit:
        raise Fail(text)
    return out(text, q)


def _indicator_value(bars, name: str, period: int) -> float:  # noqa: ANN001
    from genesis.charting import indicators as ind

    if name == "rsi":
        series = ind.rsi(bars.close, period)
    elif name == "sma":
        series = ind.sma(bars.close, period)
    elif name == "ema":
        series = ind.ema(bars.close, period)
    elif name == "atr":
        series = ind.atr(bars, period)
    elif name == "adx":
        return float(ind.adx(bars, period))
    else:
        raise Fail(f"unknown indicator {name!r}")
    return float(series[-1])


def _signal_indicator(ctx, p, data):  # noqa: ANN001, ANN202
    period = int(p.get("period") or 14)
    bars = _bars(p["symbol"], p.get("timeframe") or "1D", max(period * 4, 60))
    name = p.get("indicator") or "rsi"
    value = _indicator_value(bars, name, period)
    hit = _compare(value, p.get("op") or "<", p["value"])
    body = {"symbol": p["symbol"].upper(), "indicator": name, "period": period,
            "value": round(value, 4), "close": round(float(bars.close[-1]), 4),
            "timeframe": bars.timeframe}
    text = f"{body['symbol']} {name.upper()}({period}) = {value:.2f} — {'' if hit else 'not '}{p.get('op', '<')} {p['value']:g}"
    if not hit:
        raise Fail(text)
    return out(text, body)


def _signal_ma_cross(ctx, p, data):  # noqa: ANN001, ANN202
    from genesis.charting import indicators as ind

    period = int(p.get("period") or 50)
    bars = _bars(p["symbol"], p.get("timeframe") or "1D", period + 30)
    avg = (ind.ema if p.get("average") == "ema" else ind.sma)(bars.close, period)
    if len(bars) < period + 2 or math.isnan(avg[-2]):
        raise Fail(f"not enough bars for a {period}-bar average")
    prev, now = float(bars.close[-2]), float(bars.close[-1])
    above = p.get("direction", "above") == "above"
    crossed = (prev <= avg[-2] and now > avg[-1]) if above else (prev >= avg[-2] and now < avg[-1])
    body = {"symbol": p["symbol"].upper(), "close": round(now, 4), "average": round(float(avg[-1]), 4)}
    text = f"{body['symbol']} {'crossed' if crossed else 'did not cross'} {'above' if above else 'below'} its {period} {p.get('average', 'sma').upper()}"
    if not crossed:
        raise Fail(text)
    return out(text, body)


def _signal_volume(ctx, p, data):  # noqa: ANN001, ANN202
    lookback = int(p.get("lookback") or 20)
    bars = _bars(p["symbol"], p.get("timeframe") or "1D", lookback + 5)
    if len(bars) < lookback + 1:
        raise Fail("not enough bars")
    base = float(bars.volume[-lookback - 1:-1].mean())
    ratio = float(bars.volume[-1]) / base if base else 0.0
    body = {"symbol": p["symbol"].upper(), "volume": float(bars.volume[-1]), "average": base,
            "multiple": round(ratio, 2)}
    text = f"{body['symbol']} volume {ratio:.1f}× its {lookback}-bar average"
    if ratio < float(p.get("multiple") or 2):
        raise Fail(text)
    return out(text, body)


def _signal_breakout(ctx, p, data):  # noqa: ANN001, ANN202
    lookback = int(p.get("lookback") or 20)
    bars = _bars(p["symbol"], p.get("timeframe") or "1D", lookback + 5)
    if len(bars) < lookback + 1:
        raise Fail("not enough bars")
    close = float(bars.close[-1])
    high = float(bars.high[-lookback - 1:-1].max())
    low = float(bars.low[-lookback - 1:-1].min())
    up = p.get("direction", "high") == "high"
    hit = close > high if up else close < low
    body = {"symbol": p["symbol"].upper(), "close": close, "range_high": high, "range_low": low}
    text = f"{body['symbol']} {close:g} {'broke' if hit else 'inside'} the {lookback}-bar {'high' if up else 'low'} ({high if up else low:g})"
    if not hit:
        raise Fail(text)
    return out(text, body)


def _bars_fresh(ctx, p, data):  # noqa: ANN001, ANN202
    bars = _bars(p["symbol"], p.get("timeframe") or "1D", 5)
    last = bars.times[-1]
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    age_h = (ctx.now - last).total_seconds() / 3600
    text = f"{p['symbol'].upper()} last {bars.timeframe} bar is {age_h:.1f}h old"
    if age_h > float(p.get("max_age_hours") or 36):
        raise Fail(text)
    return out(text, {"symbol": p["symbol"].upper(), "age_hours": round(age_h, 2)})


def _update_bars(ctx, p, data):  # noqa: ANN001, ANN202
    symbols = _symbols(p.get("symbols")) or [s for s in (symbol_of(i) for i in items_of(data)) if s]
    if not symbols:
        raise Fail("no symbols to update")
    done, failed = [], []
    for sym in symbols[:50]:
        try:
            bars = _bars(sym, p.get("timeframe") or "1D", int(p.get("bars") or 300))
            done.append({"symbol": sym, "bars": len(bars), "last": bars.times[-1].isoformat()})
        except Exception as exc:  # noqa: BLE001 - one bad symbol is a row, not the run
            failed.append({"symbol": sym, "error": str(exc)[:200]})
    if not done:
        raise Fail(f"no symbols updated: {failed[:3]}")
    return out(f"updated {len(done)} symbol(s), {len(failed)} failed",
               {"updated": done, "failed": failed}, done)


# ---------------------------------------------------------------------------
# watchlists
# ---------------------------------------------------------------------------


def _watchlist_store():  # noqa: ANN202
    from genesis.watchlist.store import WatchlistStore

    return WatchlistStore(path=_memory_dir() / "watchlists.db")


def _find_list(store: Any, name: str) -> dict[str, Any] | None:
    key = (name or "").strip().lower()
    return next((w for w in store.lists() if w["id"] == name or w["name"].lower() == key), None)


def _watchlist_symbols(name: str, group: str = "") -> list[str]:
    store = _watchlist_store()
    try:
        found = _find_list(store, name)
    finally:
        store.close() if hasattr(store, "close") else None
    if found is None:
        raise Fail(f"no watchlist called {name!r}")
    return [m["symbol"] for m in found["members"] if not group or m["group"] == group]


def _watchlist_read(ctx, p, data):  # noqa: ANN001, ANN202
    symbols = _watchlist_symbols(p["watchlist"], p.get("group") or "")
    return out(", ".join(symbols) or "empty", {"symbols": symbols}, symbols)


def _watchlist_change(add: bool):  # noqa: ANN202
    def run(ctx, p, data):  # noqa: ANN001, ANN202
        from genesis.company.symbols import normalise

        symbols = _symbols(p.get("symbols")) or [s for s in (symbol_of(i) for i in items_of(data)) if s]
        if not symbols:
            raise Fail("no symbols given or in the input")
        store = _watchlist_store()
        try:
            found = _find_list(store, p["watchlist"])
            if found is None:
                if not (add and p.get("create")):
                    raise Fail(f"no watchlist called {p['watchlist']!r}")
                list_id = store.create(p["watchlist"])
            else:
                list_id = found["id"]
            changed = []
            for sym in symbols[:100]:
                sym = normalise(sym)
                if add:
                    store.add(list_id, sym, group=p.get("group") or "")
                    changed.append(sym)
                elif store.remove(list_id, sym):
                    changed.append(sym)
        finally:
            store.close() if hasattr(store, "close") else None
        verb = "added to" if add else "removed from"
        return out(f"{len(changed)} {verb} {p['watchlist']}", {"symbols": changed}, changed)
    return run


# ---------------------------------------------------------------------------
# logic & flow
# ---------------------------------------------------------------------------


def _session_gate(ctx, p, data):  # noqa: ANN001, ANN202
    state = ctx.calendar.state(ctx.now).value
    allowed = p.get("sessions") or ["open"]
    if state not in allowed:
        raise Fail(f"market is {state}, not {'/'.join(allowed)}")
    return out(f"market is {state}", {"session": state})


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _day_gate(ctx, p, data):  # noqa: ANN001, ANN202
    today = DAYS[ctx.now.astimezone(ctx.tz).weekday()]
    allowed = p.get("days") or list(DAYS[:5])
    if today not in allowed:
        raise Fail(f"today is {today}")
    return out(f"today is {today}", {"day": today})


def _time_gate(ctx, p, data):  # noqa: ANN001, ANN202
    now = ctx.now.astimezone(ctx.tz).strftime("%H:%M")
    start, end = p.get("start") or "09:30", p.get("end") or "16:00"
    inside = start <= now <= end if start <= end else (now >= start or now <= end)
    if not inside:
        raise Fail(f"{now} ET is outside {start}–{end}")
    return out(f"{now} ET is inside {start}–{end}", {"time": now})


def _contains(ctx, p, data):  # noqa: ANN001, ANN202
    words = [w.strip().lower() for w in str(p.get("keywords") or "").split(",") if w.strip()]
    need_all = p.get("mode") == "all"

    def hits(value: Any) -> list[str]:
        blob = (value if isinstance(value, str) else json.dumps(value, default=str)).lower()
        found = [w for w in words if w in blob]
        return found if found and (len(found) == len(words) or not need_all) else []

    rows = items_of(data)
    if rows:
        # Keep the items that match, so the next node alerts on the headlines
        # that mentioned the words -- not on the whole feed.
        kept = [r for r in rows if hits(get_field(r, p["field"]) if p.get("field") else r)]
        if not kept:
            raise Fail(f"none of {len(rows)} items mention {', '.join(words)}")
        return out(f"{len(kept)} of {len(rows)} mention {', '.join(words)}", {"items": kept}, kept)

    if p.get("field"):
        value = get_field((data or {}).get("structured"), p["field"]) or get_field(data, p["field"]) or ""
    else:
        value = f"{(data or {}).get('text') or ''} {json.dumps((data or {}).get('structured'), default=str)}"
    found = hits(value)
    if not found:
        raise Fail(f"no match for {', '.join(words)}")
    return out(f"matched {', '.join(found)}", {"matched": found})


def _compare_field(ctx, p, data):  # noqa: ANN001, ANN202
    actual = get_field((data or {}).get("structured"), p["field"])
    if actual is None:
        actual = get_field(data, p["field"])
    if not _compare(actual, p.get("op") or ">", p.get("value")):
        raise Fail(f"{p['field']} = {actual!r}, not {p.get('op')} {p.get('value')}")
    return out(f"{p['field']} = {actual}", {"value": actual})


def _count_gate(ctx, p, data):  # noqa: ANN001, ANN202
    n = len(items_of(data))
    if not _compare(n, p.get("op") or ">=", p.get("value") or 1):
        raise Fail(f"{n} item(s), not {p.get('op')} {p.get('value')}")
    return out(f"{n} item(s)", {"count": n}, items_of(data))


def _digest_of(data: dict[str, Any] | None) -> str:
    body = {k: v for k, v in (data or {}).items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _changed(ctx, p, data):  # noqa: ANN001, ANN202
    digest = _digest_of(data)
    previous = ctx.previous_output(ctx.step.id)
    if previous and previous.get("hash") == digest:
        raise Fail("same as the last run")
    return {**(data or out()), "hash": digest}


def _cooldown(ctx, p, data):  # noqa: ANN001, ANN202
    minutes = float(p.get("minutes") or 60)
    last = ctx.last_passed_at(ctx.step.id)
    if last and ctx.now - last < timedelta(minutes=minutes):
        raise Fail(f"passed {int((ctx.now - last).total_seconds() // 60)} min ago; cooling down for {minutes:g}")
    return data or out("cooldown clear")


def _stop(ctx, p, data):  # noqa: ANN001, ANN202
    raise Stop(p.get("message") or "stopped")


def _fail(ctx, p, data):  # noqa: ANN001, ANN202
    raise Fail(render(p.get("message") or "failed", ctx, data))


def _process(ctx, p, data):  # noqa: ANN001, ANN202
    return ctx.run_process(p["workflow"], data)


# ---------------------------------------------------------------------------
# transform
# ---------------------------------------------------------------------------


def _take(ctx, p, data):  # noqa: ANN001, ANN202
    rows = items_of(data)
    n = int(p.get("count") or 5)
    kept = rows[-n:] if p.get("from") == "end" else rows[:n]
    return out(f"kept {len(kept)} of {len(rows)}", {"items": kept}, kept)


def _filter(ctx, p, data):  # noqa: ANN001, ANN202
    rows = items_of(data)
    op = p.get("op") or "contains"
    if op == "contains":
        needle = str(p.get("value") or "").lower()
        kept = [r for r in rows if needle in str(get_field(r, p.get("field") or "") if p.get("field") else r).lower()]
    else:
        kept = [r for r in rows if _compare(get_field(r, p["field"]), op, p.get("value"))]
    return out(f"kept {len(kept)} of {len(rows)}", {"items": kept}, kept)


def _sort(ctx, p, data):  # noqa: ANN001, ANN202
    rows = items_of(data)

    def key(r: Any) -> tuple[int, Any]:
        v = get_field(r, p["field"])
        try:
            return (0, float(v))
        except (TypeError, ValueError):
            return (1, str(v))

    ordered = sorted(rows, key=key, reverse=p.get("order") == "descending")
    return out(f"sorted {len(ordered)} by {p['field']}", {"items": ordered}, ordered)


def _pluck(ctx, p, data):  # noqa: ANN001, ANN202
    value = get_field((data or {}).get("structured"), p["field"])
    if value is None:
        value = get_field(data, p["field"])
    if value is None:
        raise Fail(f"no field {p['field']!r} in the input")
    items = value if isinstance(value, list) else None
    return out(str(value)[:1500] if not isinstance(value, (dict, list)) else json.dumps(value, default=str)[:1500],
               {"value": value}, items)


def _extract_symbols(ctx, p, data):  # noqa: ANN001, ANN202
    seen: list[str] = []
    for item in items_of(data):
        sym = symbol_of(item)
        if sym and sym not in seen:
            seen.append(sym)
    if not seen:
        raise Fail("no symbols in the input")
    return out(", ".join(seen), {"symbols": seen}, seen)


def _dedupe(ctx, p, data):  # noqa: ANN001, ANN202
    seen, kept = set(), []
    for r in items_of(data):
        k = json.dumps(get_field(r, p["field"]) if p.get("field") else r, sort_keys=True, default=str).lower()
        if k not in seen:
            seen.add(k)
            kept.append(r)
    return out(f"{len(kept)} unique", {"items": kept}, kept)


def _as_date(value: Any):  # noqa: ANN202
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Epoch seconds (news feeds) or milliseconds.
        seconds = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(seconds, UTC).date()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")[:25]).date()
    except ValueError:
        try:
            return datetime.fromisoformat(str(value)[:10]).date()
        except ValueError:
            return None


def _date_window(ctx, p, data):  # noqa: ANN001, ANN202
    today = ctx.now.astimezone(ctx.tz).date()
    start = today + timedelta(days=int(p.get("from_days") or 0))
    end = today + timedelta(days=int(p.get("to_days") or 0))
    rows = items_of(data)
    kept = [r for r in rows if (d := _as_date(get_field(r, p["field"]))) and start <= d <= end]
    return out(f"{len(kept)} of {len(rows)} dated {start}..{end}", {"items": kept}, kept)


def _earnings_dates(ctx, p, data):  # noqa: ANN001, ANN202
    import yfinance

    symbols = (_watchlist_symbols(p["watchlist"]) if p.get("watchlist") else _symbols(p.get("symbols"))) \
        or [s for s in (symbol_of(i) for i in items_of(data)) if s]
    if not symbols:
        raise Fail("no symbols — pick a watchlist, type symbols, or wire an input")
    rows, missing = [], []
    for sym in symbols[:50]:
        try:
            cal = yfinance.Ticker(sym).calendar or {}
            dates = cal.get("Earnings Date") or []
            first = dates[0] if isinstance(dates, list) and dates else dates or None
            if not first:
                missing.append(sym)
                continue
            rows.append({"symbol": sym, "earnings_date": str(first),
                         "eps_estimate": cal.get("Earnings Average"),
                         "revenue_estimate": cal.get("Revenue Average")})
        except Exception:  # noqa: BLE001 - a symbol with no calendar is a row state, not the run
            missing.append(sym)
    rows.sort(key=lambda r: r["earnings_date"])
    text = "\n".join(f"{r['symbol']} {r['earnings_date']}" for r in rows) or "no earnings dates found"
    return out(text, {"earnings": rows, "missing": missing}, rows)


def _template(ctx, p, data):  # noqa: ANN001, ANN202
    text = render(p.get("template") or "", ctx, data)
    return out(text, {"text": text, **({"count": len(items_of(data))} if data else {})}, items_of(data) or None)


# ---------------------------------------------------------------------------
# research & agents
# ---------------------------------------------------------------------------


def _dispatch(agent: str, task_type: str | None = None, build: Callable[[dict[str, Any]], dict[str, Any]] | None = None):  # noqa: ANN202
    def run(ctx, p, data):  # noqa: ANN001, ANN202
        args = build(p) if build else {k: v for k, v in p.items() if v not in (None, "", [])}
        # Third-party data reaches an agent as fenced text only. Parsed fields
        # are for deterministic nodes; an agent with a model reads the quote.
        handed = ({"text": (data or {}).get("text", ""), "untrusted": True}
                  if (data or {}).get("untrusted") else data)
        task_id = ctx.dispatch(agent, task_type or f"{agent}.run", {**args, "input": handed})
        return out(f"handed to {agent} — the result lands in its own store", {"task": task_id, "agent": agent})
    return run


def _research_read(ctx, p, data):  # noqa: ANN001, ANN202
    from genesis.research.store import ResearchStore

    store = ResearchStore(path=_memory_dir() / "research.db", vault=None)
    try:
        note = store.current(p.get("kind") or "topic", p["subject"])
    finally:
        store.close()
    if note is None:
        raise Fail(f"no {p.get('kind') or 'topic'} note on {p['subject']!r} yet")
    body = note.to_dict() if hasattr(note, "to_dict") else {"id": getattr(note, "id", None)}
    text = getattr(note, "summary", None) or getattr(note, "body", "") or ""
    return out(str(text), body)


# ---------------------------------------------------------------------------
# news
# ---------------------------------------------------------------------------


def _news_collect(ctx, p, data):  # noqa: ANN001, ANN202
    from genesis.news import open_store
    from genesis.news.collect import collect, default_symbols

    extra = _symbols(p.get("symbols")) or [s for s in (symbol_of(i) for i in items_of(data)) if s]
    queries = [q.strip() for q in str(p.get("queries") or "").split(",") if q.strip()] or None
    store = open_store()
    try:
        run = collect(store, [*default_symbols(), *extra], queries)
    finally:
        store.close()
    if not run["ok"]:
        raise Fail(f"news collection mostly failed: {'; '.join(run['errors'][:3])}")
    return out(f"{run['new']} new stories from {run['sources']} sources", run)


def _news_recent(ctx, p, data):  # noqa: ANN001, ANN202
    from genesis.news import open_store

    store = open_store()
    try:
        rows = store.list(hours=float(p.get("hours") or 24), symbols=_symbols(p.get("symbols")),
                          query=str(p.get("keywords") or "").replace(",", " "), limit=int(p.get("limit") or 50))
    finally:
        store.close()
    items = [{k: r[k] for k in ("id", "title", "publisher", "published", "symbols", "url", "summary")} for r in rows]
    text = "\n".join(f"- {r['published'][:16]} {r['publisher']}: {r['title']}" for r in items[:25])
    return out(text or "no stories in the window", {"count": len(items)}, items)


def brief_markdown(row: dict[str, Any]) -> str:
    """A stored news brief as a note: overview, stories, ideas, risks, and every source."""
    b = row.get("body") or {}
    lines: list[str] = []
    if b.get("overview"):
        lines += [f"> {b['overview']}", ""]
    if b.get("stories"):
        lines.append("## Stories")
        for s in b["stories"]:
            syms = ", ".join(s.get("symbols") or [])
            lines += ["", f"### {s['headline']}" + (f" — {syms}" if syms else "") + f" · {s.get('direction', 'neutral')}"]
            if s.get("what_happened"):
                lines.append(s["what_happened"])
            if s.get("why_it_matters"):
                lines.append(f"*Why it matters:* {s['why_it_matters']}")
        lines.append("")
    for heading, key in (("Themes", "themes"), ("Watch this week", "watch")):
        if b.get(key):
            lines += [f"## {heading}", *[f"- {x}" for x in b[key]], ""]
    if b.get("trade_ideas"):
        lines.append("## Trade ideas")
        lines.append("*Directions and reasons only — no sizes, stops or targets (Safety Invariants #3).*")
        for i in b["trade_ideas"]:
            syms = ", ".join(i.get("symbols") or [])
            lines.append(f"- **{i['idea']}** ({i.get('bias', 'watch')}{' · ' + syms if syms else ''}) — {i.get('rationale', '')}"
                         + (f" *Invalidated if:* {i['invalidation']}" if i.get("invalidation") else ""))
        lines.append("")
    if b.get("risks"):
        lines += ["## Risks", *[f"- {x}" for x in b["risks"]], ""]
    articles = b.get("articles") or []
    if articles:
        read = sum(1 for x in articles if x.get("read"))
        lines.append(f"## Sources — {len(articles)} selected of {b.get('considered', len(articles))}, {read} read in full")
        for x in articles:
            lines.append(f"{x['n']}. [{x['title']}]({x['url']}) — {x.get('publisher', '')}, {str(x.get('published', ''))[:16]}")
        lines.append("")
    meta = [f"model {b.get('model', '?')}", f"confidence {b.get('confidence', 0):.2f}"]
    if b.get("flags"):
        meta.append(f"flags: {', '.join(b['flags'])}")
    if b.get("degraded"):
        meta.append("degraded — some articles could not be read")
    lines += ["---", f"*{' · '.join(meta)} · brief {row.get('id', '')}*"]
    return "\n".join(lines)


def _news_brief(ctx, p, data):  # noqa: ANN001, ANN202
    """Read the window's top stories and write one brief — the News page's own `write_brief`."""
    from genesis.agents.research.news_catalyst import write_brief
    from genesis.config import load_config
    from genesis.llm.tiers import build_tier
    from genesis.news import open_store

    config = load_config()
    large = build_tier(config, "large")
    if large.backend is None:
        raise Fail(large.note or "no large-tier model is configured — set one in Settings → Model tiers")
    store = open_store()
    try:
        row = write_brief(
            store, large.backend, select_backend=build_tier(config, "small").backend,
            # Rendered like every other text setting, so `{symbols}` can name
            # whatever the step before it found. Without this a brief can only
            # ever cover a list typed by hand.
            hours=float(p.get("hours") or 72), symbols=_symbols(_rendered(p.get("symbols"), ctx, data)),
            focus=render(p.get("focus") or "", ctx, data), max_articles=int(p.get("max_articles") or 10),
            title=render(p.get("title") or "", ctx, data), refresh=bool(p.get("refresh", True)),
            requested_by=f"workflow:{ctx.workflow.name}",
        )
    except Exception as exc:  # noqa: BLE001 - a quiet weekend or a model outage is the fail edge
        raise Fail(getattr(exc, "reason", None) or f"{type(exc).__name__}: {exc}") from None
    b = row.get("body") or {}
    body = out(brief_markdown(row), {
        "brief": row.get("id"), "title": row.get("title"), "stories": len(b.get("stories") or []),
        "trade_ideas": len(b.get("trade_ideas") or []), "articles": len(b.get("articles") or []),
        "considered": b.get("considered"), "confidence": b.get("confidence"),
    }, b.get("stories") or [])
    # The whole brief, not `out`'s 4000-character cap: this text is the review.
    # Model text derived from third-party articles: fine for a note and an
    # alert, never handed on to another agent as data.
    return {**body, "text": brief_markdown(row), "untrusted": True}


def _tearsheet(ctx, p, data):  # noqa: ANN001, ANN202
    """Run the Performance Analyst *here*, and hand back the review as markdown.

    Deliberately not `_dispatch("performance-analyst")`. Dispatch is
    fire-and-forget: it queues the task and returns "handed to
    performance-analyst", so a note step chained after it writes that sentence
    into your notebook instead of the review. That is exactly why the weekly
    review never appeared in anyone's notes.

    The same shape as `news.brief`: call the agent's own function, return the
    text, let `output.note` save it. Synchronous because the workflow's next
    step needs the words, and a review over a week of a journal is arithmetic
    over rows on this disk -- it is the model narration, not the numbers, that
    takes a moment.
    """
    from genesis.agents.journal.performance_analyst import PerformanceAnalystAgent
    from genesis.config import load_config
    from genesis.journal.store import JournalStore
    from genesis.llm.tiers import build_tier

    config = load_config()
    store = JournalStore(path=config.memory.db_path.parent / "journal.db")
    try:
        agent = PerformanceAnalystAgent(store, backend=build_tier(config, "large").backend)
        review = agent.review(days=int(p.get("days") or 7), speak=bool(p.get("narrate", True)))
    except Exception as exc:  # noqa: BLE001 - an empty journal is the fail edge, not a crash
        raise Fail(getattr(exc, "reason", None) or f"{type(exc).__name__}: {exc}") from None
    finally:
        store.close()
    text = tearsheet_markdown(review)
    return {**out(text, review.to_dict()), "text": text}


def tearsheet_markdown(review: Any) -> str:
    """A Review as a note. The numbers first, the narration under them.

    Kept short on purpose: what belongs in a note is the honest headline, the
    sample it rests on, and any warning that the sample is too thin to conclude
    from. The full slice tables live in the journal, which is where you go when
    the headline makes you want them.
    """
    overall = review.overall
    lines = [f"**{review.period_from.date()} → {review.period_to.date()}**", ""]
    if overall.n == 0:
        lines.append("No completed trades in the period. Nothing to review.")
        return "\n".join(lines)
    lines += [
        f"- Net **{overall.net_r:+.1f}R** over {overall.qualifier()}",
        f"- Expectancy **{overall.expectancy_r:+.2f}R** per trade",
    ]
    if review.best is not None:
        lines.append(f"- Best: {review.best.sentence()}")
    if review.worst is not None:
        lines.append(f"- Worst: {review.worst.sentence()}")
    for warning in review.warnings:
        lines.append(f"- ⚠️ {warning}")
    if review.narrative:
        lines += ["", review.narrative]
    return "\n".join(lines)


def _news_ideas(ctx, p, data):  # noqa: ANN001, ANN202
    """Promote a brief's trade ideas into the one idea store.

    Chained after `news.brief`, whose output carries the brief id. Without this
    step the ideas a brief produces exist only as prose inside a note: nothing
    ranks them, nothing sizes them, and nothing can later say whether they were
    any good. With it they are `Idea` records like any other, and the plan, the
    gate's dry run and the weekly review all apply to them unchanged.

    Nothing here can place an order. It writes research notes.
    """
    import json

    from genesis.config import load_config
    from genesis.marketdata.universe import load as load_universe
    from genesis.news import open_store
    from genesis.news.ideas import promote_brief
    from genesis.research.store import ResearchStore

    brief_id = str(p.get("brief") or "").strip() or str(
        ((data or {}).get("structured") or {}).get("brief") or ""
    ).strip()
    if not brief_id:
        raise Fail("no brief to read — chain this after News brief, or name a brief id")

    news = open_store()
    try:
        row = news.brief(brief_id)
    finally:
        news.close()
    if not row:
        raise Fail(f"no brief {brief_id!r}")
    body = row["body"] if isinstance(row.get("body"), dict) else json.loads(row.get("body") or "{}")

    config = load_config()
    store = ResearchStore(path=config.memory.db_path.parent / "research.db",
                          vault=str(config.memory.vault_path))

    def setup_for(symbol: str, direction: str):  # noqa: ANN202
        """Price the idea from bars — the charting engine, not the model.

        `tier: none` all the way down: ATR, structure and levels are arithmetic
        over bars this system already holds. The brief supplies the direction
        and the reason; every number comes from the chart.
        """
        from genesis.research.setup import compute_setup

        return compute_setup(symbol, direction, config=config,
                             timeframe=str(p.get("timeframe") or "1D"))

    try:
        promoted = promote_brief(store, {**row, "body": body},
                                 trace_id=getattr(ctx, "trace_id", None),
                                 horizon_days=int(p.get("horizon_days") or 5),
                                 setup_for=None if p.get("price") is False else setup_for,
                                 # The symbols the brief is *about* but wrote no
                                 # trade for. Resolved against the tradeable
                                 # universe, never by asking a model.
                                 universe=load_universe(config),
                                 extracted=int(p.get("extract") or 0))
    finally:
        store.close()

    parts = [f"{len(promoted.ideas)} idea(s)"]
    if promoted.extracted:
        parts.append(f"{len(promoted.extracted)} from the text")
    if promoted.watching:
        parts.append(f"{len(promoted.watching)} watching")
    if promoted.dropped:
        # Counted out loud. A brief that produced four ideas and stored one is
        # a fact the operator should meet in the run, not discover in a panel.
        parts.append(f"{len(promoted.dropped)} dropped")
    return out(", ".join(parts) + " — open TI to see them", promoted.as_dict())


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------


def _alert(ctx, p, data):  # noqa: ANN001, ANN202
    cooldown = float(p.get("cooldown_minutes") or 0)
    last = ctx.last_alert_at(ctx.step.id)
    if cooldown and last and ctx.now - last < timedelta(minutes=cooldown):
        return out(f"alert suppressed — sent {int((ctx.now - last).total_seconds() // 60)} min ago", {"suppressed": True})
    title = render(p.get("title") or "{workflow}", ctx, data)
    body = render(p.get("message") or "{text}", ctx, data)
    alert_id = ctx.alert(title, body, p.get("urgency") or "if-present")
    return out(f"alert: {title}", {"alert": alert_id, "title": title, "message": body})


def _note(ctx, p, data):  # noqa: ANN001, ANN202
    from genesis.notebook.vault import registry

    vault = registry().open(None)
    path = render(p.get("path") or "", ctx, data).strip() or vault.daily_path(ctx.now)
    heading = render(p.get("heading") or "## {workflow} — {time} ET", ctx, data)
    text = render(p.get("template") or "{text}", ctx, data)
    if p.get("mode") == "replace":
        # A dated review re-run the same day replaces itself rather than stacking copies.
        vault.write(path, f"{heading}\n\n{text}\n", by="automation")
    else:
        vault.append(path, f"\n{heading}\n\n{text}\n")
    return out(f"wrote to {path}", {"path": path})


def _index_movers(ctx, p, data):  # noqa: ANN001, ANN202
    """The day's biggest movers in one index, both tails, from the index's own members.

    One call gives gainers *and* losers, which is why this is a node rather than
    two screens the workflow would then have to merge -- steps take one input.
    The membership and the weighting are the fund's own holdings file, never a
    model's recollection (``marketdata/index_map.py``).
    """
    from genesis.marketdata.index_map import UNIVERSES, index_map

    code = str(p.get("index") or "SPX").upper()
    if code not in UNIVERSES:
        raise Fail(f"unknown index {code}; one of {', '.join(UNIVERSES)}")
    payload = index_map(code)
    if "error" in payload:
        raise Fail(payload["error"])
    top = max(1, int(p.get("top") or 5))
    total = payload["total"]
    rows = [{**r, "side": side} for side, key in (("gainer", "gainers"), ("loser", "losers"))
            for r in total[key][:top]]
    if not rows:
        raise Fail(f"{code} had no movers to report")
    lines = "\n".join(f"{r['symbol']} {r['change_pct']:+.2f}% — {r['name']}" for r in rows)
    return out(f"{payload['index']} movers ({total['change_pct']:+.2f}% on the day):\n{lines}", {
        "index": code, "index_name": payload["index"], "change_pct": total["change_pct"],
        "advancers": total["advancers"], "decliners": total["decliners"],
        "market_state": payload["market_state"],
    }, rows)


def _observe(ctx, p, data):  # noqa: ANN001, ANN202
    """One durable fact into the journal, so a finding can become a lesson.

    An observation is the journal's non-trade record (Journal Family §Four
    record types) -- it is what the Insight Miner rests a lesson on. A note in
    the notebook is for a person to read; this is for the miner to aggregate,
    which is why a run that writes a note usually writes one of these too.
    """
    from genesis.config import load_config
    from genesis.journal.schema import Observation
    from genesis.journal.store import JournalStore

    kind = render(p.get("kind") or "", ctx, data).strip()
    subject = render(p.get("subject") or "", ctx, data).strip()
    if "." not in kind:
        raise Fail(f"kind {kind!r} must be namespaced, e.g. movers.daily")
    if not subject:
        raise Fail("an observation needs a subject -- the thing it is about")

    structured = data.get("structured") if isinstance(data, dict) else None
    detail: dict[str, Any] = {"workflow": ctx.workflow.name,
                              "summary": render(p.get("summary") or "{text}", ctx, data)[:4000]}
    # The note this run wrote, when there is one: the feed links the observation
    # and the note to each other rather than duplicating the text into both.
    if isinstance(structured, dict) and isinstance(structured.get("path"), str):
        detail["note"] = structured["path"]

    store = JournalStore(path=load_config().memory.db_path.parent / "journal.db")
    try:
        recorded = store.record(Observation(
            kind=kind, subject=subject, outcome=render(p.get("outcome") or "", ctx, data).strip(),
            source=f"automation:{ctx.workflow.id}", detail=detail,
        ))
    finally:
        store.close()
    return out(f"journalled {kind} on {subject}", {"observation": recorded.id, "kind": kind, "subject": subject})


# ---------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------

SYMBOL = Param("symbol", "symbol", "Symbol", required=True, help="A ticker — NVDA, SPY")
TIMEFRAME = Param("timeframe", "select", "Timeframe", default="1D", options=("5m", "15m", "1H", "4H", "1D", "1W"))
OP = Param("op", "select", "Is", default=">", options=(">", ">=", "<", "<=", "==", "!="))
WATCHLIST = Param("watchlist", "watchlist", "Watchlist", required=True)
DAYS_PARAM = Param("days", "integer", "Days back", default=30)

_A = Action
ACTIONS: dict[str, Action] = {a.id: a for a in (
    # market data
    _A("market.quote", "market", "Quote", "Last close and day change for a symbol.", _market_quote,
       (SYMBOL,), each="symbol"),
    _A("market.watchlist-quotes", "market", "Quote a watchlist", "Day change for every symbol in a watchlist.",
       _watchlist_quotes, (WATCHLIST,)),
    _A("market.earnings-dates", "calendar", "Upcoming earnings", "Next earnings date for a watchlist or symbols (Yahoo, no key).",
       _earnings_dates, (Param("watchlist", "watchlist", "Watchlist"),
                         Param("symbols", "symbols", "Or symbols", help="Blank = the watchlist, or the input's symbols"))),
    _A("market.bars", "market", "Price history summary", "Close, range and change over the last N bars.",
       _bars_summary, (SYMBOL, TIMEFRAME, Param("bars", "integer", "Bars", default=100)), each="symbol"),

    # signals
    _A("signal.price", "signals", "Price above / below", "Passes when the last price is above or below a level.",
       _signal_price, (SYMBOL, Param("direction", "select", "Direction", default="above", options=("above", "below")),
                       Param("level", "number", "Level", required=True)), branches=True, each="symbol"),
    _A("signal.move", "signals", "Big daily move", "Passes when today's % change exceeds a threshold.",
       _signal_move, (SYMBOL, Param("direction", "select", "Direction", default="either", options=("either", "up", "down")),
                      Param("percent", "number", "Percent", default=3, required=True)), branches=True, each="symbol"),
    _A("signal.indicator", "signals", "Indicator threshold", "RSI, SMA, EMA, ATR or ADX compared to a value.",
       _signal_indicator, (SYMBOL, TIMEFRAME,
                           Param("indicator", "select", "Indicator", default="rsi", options=("rsi", "sma", "ema", "atr", "adx")),
                           Param("period", "integer", "Period", default=14),
                           Param("op", "select", "Is", default="<", options=(">", ">=", "<", "<=")),
                           Param("value", "number", "Value", default=30, required=True)), branches=True, each="symbol"),
    _A("signal.ma-cross", "signals", "Moving-average cross", "Passes on the bar price crosses its moving average.",
       _signal_ma_cross, (SYMBOL, TIMEFRAME, Param("average", "select", "Average", default="sma", options=("sma", "ema")),
                          Param("period", "integer", "Period", default=50),
                          Param("direction", "select", "Cross", default="above", options=("above", "below"))),
       branches=True, each="symbol"),
    _A("signal.volume", "signals", "Volume spike", "Passes when volume is a multiple of its average.",
       _signal_volume, (SYMBOL, TIMEFRAME, Param("lookback", "integer", "Average over bars", default=20),
                        Param("multiple", "number", "Multiple", default=2)), branches=True, each="symbol"),
    _A("signal.breakout", "signals", "Range breakout", "Passes when price closes beyond the N-bar high or low.",
       _signal_breakout, (SYMBOL, TIMEFRAME, Param("lookback", "integer", "Range bars", default=20),
                          Param("direction", "select", "Break", default="high", options=("high", "low"))),
       branches=True, each="symbol"),

    # watchlists
    _A("watchlist.read", "watchlist", "Watchlist symbols", "The symbols in one of your watchlists.",
       _watchlist_read, (WATCHLIST, Param("group", "text", "Only this section"))),
    _A("watchlist.add", "watchlist", "Add to watchlist", "Add symbols (typed, or from the input) to a watchlist.",
       _watchlist_change(True), (WATCHLIST, Param("symbols", "symbols", "Symbols", help="Blank = the input's symbols"),
                                 Param("group", "text", "Section"), Param("create", "bool", "Create the list if missing", default=False)),
       writes=True),
    _A("watchlist.remove", "watchlist", "Remove from watchlist", "Remove symbols from a watchlist.",
       _watchlist_change(False), (WATCHLIST, Param("symbols", "symbols", "Symbols", help="Blank = the input's symbols")),
       writes=True),

    # news
    _A("news.collect", "news", "Collect news", "Fetch fresh headlines for the market, your watchlists and any extra symbols.",
       _news_collect, (Param("symbols", "symbols", "Extra symbols", help="Blank = the input's symbols, if any"),
                       Param("queries", "text", "Search topics", help="Comma separated; blank = market, Fed, economy")),
       writes=True),
    _A("news.recent", "news", "Recent headlines", "Stored stories from the last N hours, optionally filtered.",
       _news_recent, (Param("hours", "number", "Hours back", default=24, help="~64 covers Friday close to Sunday night"),
                      Param("symbols", "symbols", "Only these symbols"),
                      Param("keywords", "text", "Keywords"),
                      Param("limit", "integer", "Max stories", default=50))),
    _A("agent.news-brief", "news", "Write news brief", "News analyst picks what matters, reads it, and saves a brief to the News module.",
       _dispatch("news-catalyst", "news.brief", build=lambda p: {
           "hours": float(p.get("hours") or 24), "symbols": _symbols(p.get("symbols")),
           "focus": p.get("focus") or "", "max_articles": int(p.get("max_articles") or 8),
           "title": p.get("title") or "", "refresh": bool(p.get("refresh")), "requested_by": "workflow"}),
       (Param("hours", "number", "Hours back", default=24, help="Ignored when the input carries stories"),
        Param("symbols", "symbols", "Only these symbols"),
        Param("focus", "text", "Focus", help="e.g. what matters for next week's trading"),
        Param("max_articles", "integer", "Stories to read", default=8),
        Param("title", "text", "Title"),
        Param("refresh", "bool", "Collect fresh headlines first", default=True))),

    # research & agents
    _A("research.read", "research", "Read research note", "The current research note on a subject, from the directory.",
       _research_read, (Param("subject", "text", "Subject", required=True),
                        Param("kind", "select", "Kind", default="topic", options=("topic", "regime", "idea", "symbol")))),
    _A("news.brief", "news", "News brief (reads the articles)",
       "Refresh headlines, pick the top stories, read them in full, and write a brief with themes, trade ideas "
       "and risks. Runs the large model.",
       _news_brief, (Param("hours", "number", "Look back (hours)", default=72),
                     Param("max_articles", "integer", "Articles to read", default=10),
                     Param("focus", "text", "Focus", help="e.g. what matters for the week ahead"),
                     Param("symbols", "symbols", "Only these symbols"),
                     Param("title", "text", "Title", help="Slots allowed: {date}"),
                     Param("refresh", "bool", "Collect fresh headlines first", default=True)),
       branches=True, writes=True, model_tier="large"),
    _A("agent.research", "research", "Research a topic", "Topic Researcher searches, reads and writes a sourced note.",
       _dispatch("topic-researcher"), (Param("subject", "text", "Subject", required=True),
                                       Param("depth", "select", "Depth", default="quick", options=("quick", "deep")),
                                       Param("tags", "text", "Tags"))),
    _A("agent.summarise", "research", "Summarise research", "Fuse stored notes on a subject into one synopsis.",
       _dispatch("topic-researcher", "research.summarise"), (Param("subject", "text", "Subject", required=True),
                                                             Param("tags", "text", "Tags"))),
    _A("agent.regime", "research", "Market regime read", "Market Analyst's top-down read of indexes and sectors.",
       _dispatch("market-analyst")),
    _A("agent.ideas", "research", "Synthesize trade ideas", "Idea Synthesizer ranks ideas from gathered research.",
       _dispatch("idea-synthesizer", build=lambda p: {"symbols": _symbols(p.get("symbols")), "max_ideas": int(p.get("max_ideas") or 5)}),
       (Param("symbols", "symbols", "Symbols"), Param("max_ideas", "integer", "Max ideas", default=5))),
    _A("agent.chart-markup", "technicals", "Mark up a chart", "Chart Markup computes levels and structure for a symbol.",
       _dispatch("chart-markup"), (SYMBOL, TIMEFRAME, Param("lookback_bars", "integer", "Bars", default=250)), each="symbol"),
    _A("agent.multi-timeframe", "technicals", "Multi-timeframe read", "Multi Timeframe scores alignment across timeframes.",
       _dispatch("multi-timeframe", build=lambda p: {"symbol": p["symbol"], "timeframes": [t.strip() for t in str(p.get("timeframes") or "1W,1D,1H").split(",")], **({"direction": p["direction"]} if p.get("direction") else {})}),
       (SYMBOL, Param("timeframes", "text", "Timeframes", default="1W,1D,1H"),
        Param("direction", "select", "Proposed direction", options=("", "long", "short"))), each="symbol"),
    _A("agent.data-viz", "research", "Answer with a chart", "Data Viz builds a chart that answers a question.",
       _dispatch("data-viz"), (Param("question", "textarea", "Question", required=True),)),

    # journal
    _A("agent.digest", "journal", "Daily digest", "Digest writes the morning or evening brief.",
       _dispatch("digest"), (Param("kind", "select", "Brief", default="morning", options=("morning", "evening")),)),
    _A("agent.performance", "journal", "Performance tearsheet", "Performance Analyst's tearsheet over a window.",
       _dispatch("performance-analyst"), (DAYS_PARAM,)),
    # The same review, run here rather than queued, so the step after it can
    # write the words to a note. `agent.performance` hands off and returns a
    # receipt; this returns the review.
    _A("news.ideas", "news", "Promote brief ideas",
       "Turn a brief's trade ideas into real ideas — ranked, sizeable, measurable. Chain after News brief.",
       _news_ideas, (Param("brief", "text", "Brief id", help="Blank = the brief from the step before"),
                     Param("horizon_days", "integer", "How long an idea stays live", default=5),
                     Param("timeframe", "select", "Chart to price it from", default="1D",
                           options=("1D", "4h", "1h")),
                     Param("price", "boolean", "Compute entry, stop and targets", default=True),
                     Param("extract", "integer", "Also read the text for symbols (0 = only its trade ideas)",
                           default=4, help="Resolved against the tradeable universe, never by a model")),
       writes=True),
    _A("journal.tearsheet", "journal", "Performance review (text)",
       "The Performance Analyst's review over a window, as text a note can hold.",
       _tearsheet, (Param("days", "integer", "Days back", default=7),
                    Param("narrate", "boolean", "Include the written read", default=True))),
    _A("agent.insights", "journal", "Mine insights", "Insight Miner looks for patterns in your own history.",
       _dispatch("insight-miner"), (DAYS_PARAM,)),
    _A("agent.drift", "journal", "Backtest vs live drift", "Compare live results with what the backtest promised.",
       _dispatch("drift"), (DAYS_PARAM,)),

    # logic
    _A("logic.session", "logic", "Only in market session", "Continue only in the chosen market sessions.",
       _session_gate, (Param("sessions", "multiselect", "Sessions", default=["open"],
                             options=("premarket", "open", "afterhours", "closed", "holiday")),), branches=True),
    _A("logic.days", "logic", "Only on days", "Continue only on the chosen weekdays (ET).",
       _day_gate, (Param("days", "multiselect", "Days", default=list(DAYS[:5]), options=DAYS),), branches=True),
    _A("logic.time-window", "logic", "Only between times", "Continue only inside a time window (ET).",
       _time_gate, (Param("start", "time", "From", default="09:30"), Param("end", "time", "Until", default="16:00")), branches=True),
    _A("logic.contains", "logic", "Text contains", "Continue when the input mentions keywords.",
       _contains, (Param("keywords", "text", "Keywords (comma separated)", required=True),
                   Param("mode", "select", "Match", default="any", options=("any", "all")),
                   Param("field", "text", "In field (blank = all text)")), branches=True, needs_input=True),
    _A("logic.compare", "logic", "Compare a field", "Continue when a field of the input compares to a value.",
       _compare_field, (Param("field", "text", "Field", required=True, help="e.g. change_pct or quote.close"), OP,
                        Param("value", "text", "Value", required=True)), branches=True, needs_input=True),
    _A("logic.count", "logic", "Count items", "Continue when the input has enough (or few enough) items.",
       _count_gate, (Param("op", "select", "Count is", default=">=", options=(">", ">=", "<", "<=", "==")),
                     Param("value", "integer", "Value", default=1)), branches=True, needs_input=True),
    _A("logic.changed", "logic", "Only if changed", "Continue only when the input differs from the last run.",
       _changed, (), branches=True, needs_input=True),
    _A("logic.cooldown", "logic", "Cooldown", "Continue at most once per N minutes.",
       _cooldown, (Param("minutes", "integer", "Minutes", default=60),), branches=True),
    _A("logic.stop", "logic", "Stop", "End the run here as a success.", _stop,
       (Param("message", "text", "Note"),)),
    _A("logic.fail", "logic", "Fail with message", "End the run as a failure with your message.", _fail,
       (Param("message", "text", "Message", default="{workflow} failed"),)),

    # transform
    _A("data.take", "transform", "Take first / last N", "Keep N items from the start or end.", _take,
       (Param("count", "integer", "N", default=5), Param("from", "select", "From", default="start", options=("start", "end"))),
       needs_input=True),
    _A("data.filter", "transform", "Filter items", "Keep items whose field matches.", _filter,
       (Param("field", "text", "Field"), Param("op", "select", "Test", default="contains",
                                              options=("contains", ">", ">=", "<", "<=", "==", "!=")),
        Param("value", "text", "Value", required=True)), needs_input=True),
    _A("data.sort", "transform", "Sort items", "Order items by a field.", _sort,
       (Param("field", "text", "Field", required=True),
        Param("order", "select", "Order", default="descending", options=("descending", "ascending"))), needs_input=True),
    _A("data.pluck", "transform", "Get a field", "Pull one field out of the input.", _pluck,
       (Param("field", "text", "Field", required=True),), needs_input=True),
    _A("data.date-window", "transform", "Keep dates in window", "Keep items whose date falls between today+from and today+to days.",
       _date_window, (Param("field", "text", "Date field", required=True, help="e.g. date, earnings_date, filing_date"),
                      Param("from_days", "integer", "From (days from today)", default=0),
                      Param("to_days", "integer", "To (days from today)", default=7)), needs_input=True),
    _A("data.symbols", "transform", "Extract symbols", "Turn the input's items into a symbol list.", _extract_symbols,
       (), needs_input=True),
    _A("data.dedupe", "transform", "Remove duplicates", "Drop repeated items, optionally by one field.", _dedupe,
       (Param("field", "text", "By field"),), needs_input=True),
    _A("data.template", "transform", "Compose text", "Write text with {count} {symbols} {items} {text} {date} slots.",
       _template, (Param("template", "textarea", "Template", required=True, default="{count} matches: {symbols}"),)),

    # output
    _A("output.alert", "output", "Send alert", "Post an alert to the dashboard; voice speaks it per its urgency.",
       _alert, (Param("title", "text", "Title", default="{workflow}"),
                Param("message", "textarea", "Message", default="{text}"),
                Param("urgency", "select", "Urgency", default="if-present", options=("always", "if-present", "never")),
                Param("cooldown_minutes", "integer", "Cooldown (min)", default=0)), writes=True),
    _A("output.note", "output", "Write to notebook", "Append to a note — today's inbox note by default.",
       _note, (Param("path", "text", "Note path", help="Blank = today's 00-Inbox note"),
               Param("heading", "text", "Heading", default="## {workflow} — {time} ET"),
               Param("template", "textarea", "Text", default="{text}"),
               Param("mode", "select", "If the note exists", default="append", options=("append", "replace"))),
       writes=True),

    _A("market.index-movers", "market", "Index movers",
       "The day's top gainers and losers in an index, from the fund's own holdings.",
       _index_movers, (Param("index", "select", "Index", default="SPX",
                             options=("SPX", "NDX", "DJIA", "SML")),
                       Param("top", "integer", "How many each way", default=5))),
    _A("journal.observe", "output", "Record an observation",
       "Write one durable fact to the journal, where the Insight Miner can rest a lesson on it.",
       _observe, (Param("kind", "text", "Kind", required=True, default="research.finding",
                        help="Namespaced noun.verb — movers.daily, level.outcome"),
                  Param("subject", "text", "Subject", required=True, default="{date}",
                        help="The thing it is about — a ticker, a date, an id"),
                  Param("outcome", "text", "Outcome", help="Categorical result, if there is one"),
                  Param("summary", "textarea", "Summary", default="{text}")), writes=True),

    # maintenance
    _A("maint.update-bars", "maintenance", "Update price history", "Fill the market data store for symbols.",
       _update_bars, (Param("symbols", "symbols", "Symbols", help="Blank = the input's symbols"), TIMEFRAME,
                      Param("bars", "integer", "Bars", default=300)), writes=True),
    _A("maint.bars-fresh", "maintenance", "Check data freshness", "Fail when a symbol's latest bar is too old.",
       _bars_fresh, (SYMBOL, TIMEFRAME, Param("max_age_hours", "number", "Max age (hours)", default=36)),
       branches=True, each="symbol"),

    # custom
    _A("flow.process", "custom", "Run a process", "Run another workflow here, as one step, and use its result.",
       _process, (Param("workflow", "workflow", "Process", required=True),), branches=True),
)}


def validate_params(action: Action, params: dict[str, Any], *, each: bool = False) -> None:
    """Refuse unknown or missing settings at save — a typo is a silent no-op otherwise."""
    known = {p.name: p for p in action.params}
    unknown = sorted(set(params) - set(known))
    if unknown:
        raise ValueError(f"{action.id}: unknown setting(s) {', '.join(unknown)}")
    for p in action.params:
        value = params.get(p.name)
        if value in (None, "", []):
            if p.required and not (each and action.each == p.name):
                raise ValueError(f"{action.id}: {p.label} is required")
            continue
        if p.type in ("number", "integer"):
            try:
                float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{action.id}: {p.label} must be a number") from None
        if p.type == "select" and p.options and str(value) not in p.options:
            raise ValueError(f"{action.id}: {p.label} must be one of {', '.join(p.options)}")
        if p.type == "multiselect" and p.options:
            bad = [v for v in (value if isinstance(value, list) else [value]) if v not in p.options]
            if bad:
                raise ValueError(f"{action.id}: {p.label} has unknown {', '.join(map(str, bad))}")


@dataclass
class Context:
    """What an action may touch. Built by the runner; nothing else gets in."""

    workflow: Any
    step: Any
    now: datetime
    tz: Any
    calendar: Any
    dispatch: Callable[[str, str, dict[str, Any]], str | None]
    alert: Callable[[str, str, str], str]
    previous_output: Callable[[str], dict[str, Any] | None]
    last_passed_at: Callable[[str], datetime | None]
    last_alert_at: Callable[[str], datetime | None]
    run_process: Callable[[str, dict[str, Any] | None], dict[str, Any]]
    extra: dict[str, Any] = field(default_factory=dict)


def numbers(params: dict[str, Any], action: Action) -> dict[str, Any]:
    """Coerce number settings and fill defaults, so run functions read plain values."""
    outp = {}
    for p in action.params:
        value = params.get(p.name, p.default)
        if value in (None, "") and p.default is not None:
            value = p.default
        if p.type == "number" and value not in (None, ""):
            value = float(value)
        if p.type == "integer" and value not in (None, ""):
            value = int(float(value))
        outp[p.name] = value
    return outp
