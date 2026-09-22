# Spec: Genesis Markdown/20-Agents/Research/Agent — Screener.md §Conversation
"""A conversation that ends in a scan. The model interprets; code filters.

The small tier's one job is *translation*: work out what the trader is after
("cheap", "quality compounders", "beaten-down dividend payers"), write that as
criteria over the closed field catalogue, say how each vague word was read, and
ask back when an answer would genuinely change the list. It never sees the
snapshot rows and never decides which companies match -- :mod:`scan` does, so
the list is the same every time the same criteria run.

**Honing in is a conversation.** Each turn carries the previous scan, so "only
tech", "loosen the P/E to 25" or "drop the dividend" edit it rather than start
over. The history comes from the Ask Genesis conversation store; ⌘K and voice
have none, and a sentence there is a fresh scan.

**Typed parity.** ``scr pe_trailing<20 sector=technology`` builds the same scan
with no model, and ``scr refresh`` rebuilds the snapshot. With no small tier
configured this is the whole screener, and the reply says so.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from genesis.commands import CommandResult
from genesis.errors import DegradedError, GenesisError
from genesis.llm.parse import json_object
from genesis.screener.scan import (
    NUMERIC_OPS, TEXT_OPS, Scan, ScanError, describe, expression, parse_expression, run, terms, validate,
)
from genesis.screener.snapshot import (
    FIELDS, SECTORS, TEXT_FIELDS, Snapshot, build_snapshot, load_current, load_snapshot, save_current,
)

__all__ = ["SYSTEM", "history_from", "interpret", "respond"]

log = logging.getLogger(__name__)

#: A scan this big is not an answer, it is the index; one this small may be a
#: threshold set too tight. Either way the reply offers to hone in.
TOO_MANY = 40
HISTORY_TURNS = 6


def _catalogue() -> str:
    numeric = "\n".join(f"- {name} ({unit}): {meaning}" for name, (unit, meaning, _) in FIELDS.items())
    text = "\n".join(f"- {name}: {meaning}" for name, meaning in TEXT_FIELDS.items())
    return (
        f"NUMERIC FIELDS (ops: {', '.join(NUMERIC_OPS)}; 'between' takes [low, high]):\n{numeric}\n\n"
        f"TEXT FIELDS (ops: {', '.join(TEXT_OPS)}; 'in' takes a list):\n{text}\n\n"
        f"SECTOR NAMES (exact): {', '.join(SECTORS)}"
    )


SYSTEM = f"""You are the screener analyst inside Genesis, a trading terminal. The trader \
talks to you in plain English about the kind of S&P 500 company they want. You turn \
what they MEAN into a scan over a fixed data snapshot. Code runs the scan; you never \
pick companies yourself and never name tickers as results.

UNIVERSE: the ~500 current S&P 500 members, one row each of yfinance fundamentals, \
refreshed nightly. Units are exactly as listed: percents are percent numbers \
(revenue_growth 15 means 15%), sizes are billions of dollars.

{_catalogue()}

HOW TO INTERPRET
1. First decide the investment idea behind the words, then choose fields. Write it \
in "understood" as one plain sentence, e.g. "Profitable tech companies trading \
below a market multiple that are still growing revenue."
2. Vague words get conventional, stated readings. Always list each one in \
"readings" so the trader can correct you. Starting points, adjust to context:
   - cheap / value / undervalued: pe_forward < 15 (or pe_trailing < 15), and for \
financials price_to_book < 1.5
   - reasonably priced growth (GARP): peg between 0 and 1.5 with earnings_growth > 10
   - growth / growing fast: revenue_growth > 15 (high growth: > 25)
   - quality / durable: roe > 15, margin_operating > 15, debt_to_equity < 100
   - profitable: margin_net > 0 (absent pe_trailing also signals losses)
   - cash machines: fcf_yield > 5
   - income / dividend payers: dividend_yield > 3, payout_ratio < 75 for "safe"
   - defensive / low volatility: beta < 0.8
   - beaten down / near lows: from_52w_high < -30; momentum / leaders: change_52w > 30
   - heavily shorted: short_float > 8
   - analysts like it: analyst_rating <= 2 with analyst_count >= 5; upside: target_upside > 20
   - large / mega cap inside the S&P: market_cap_b > 200; smaller S&P names: market_cap_b < 30
   - semis, banks, software, etc.: industry contains the word, or the sector
3. If the trader gives a number, use their number exactly.
4. REFINING: when a scan is on screen, a message that adjusts it ("only tech", \
"loosen the P/E", "drop the dividend", "refine the current screen: ...") edits THAT \
scan: keep every criterion they did not mention; change, add or remove only what they \
asked. A message describing a different idea replaces it entirely.
5. ASKING BACK: always return the best scan you can, then ask ONE short question when \
a choice would materially change the list and no convention settles it (e.g. \
"undervalued vs its own history or vs the market?" is NOT answerable here - say so \
instead). Good questions offer 2-4 concrete "choices" the trader can tap, each a \
short refinement phrase like "only Technology", "P/E under 12", "add dividend > 2%". \
Don't ask when the request is already specific. If the request is too vague for any \
field ("find me good stocks"), return scan null and ask what they are looking for, \
with style choices (value, growth, quality, income, momentum).
6. NEVER invent a field, a sector name or an operator. If part of the request cannot \
be expressed with these fields (insider buying, earnings dates, guidance, price \
patterns, news, multi-year history, anything outside the S&P 500), put that part in \
"unsupported" with the reason and scan the rest. Do not quietly swap in a proxy; a \
proxy is allowed only when you list it in readings and say it is a proxy.
7. If the message is not about finding or filtering companies at all (a chart, a \
single company question, market commentary), return intent "not_screen".
8. sort: pick the field that best expresses "best first" for the idea (cheapest: \
pe_forward asc; fastest growing: revenue_growth desc). limit defaults to 50.

Reply with ONE JSON object and nothing else:
{{"intent": "screen" | "not_screen",
 "understood": "one sentence",
 "scan": {{"criteria": [{{"field": "...", "op": "...", "value": ...}}],
          "sort": {{"field": "...", "direction": "asc" | "desc"}} | null,
          "limit": 50}} | null,
 "readings": [{{"phrase": "the trader's words", "as": "field op value", "why": "short"}}],
 "unsupported": [{{"phrase": "...", "why": "..."}}],
 "question": "one short question" | null,
 "choices": ["short refinement", "..."]}}"""


def history_from(turns: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """The trailing run of screener exchanges in a saved conversation.

    Turns are stored as operator/genesis pairs. Only the unbroken tail of
    ``screen*`` replies counts, so asking for a chart in the middle ends the
    screening thread rather than dragging it into the next unrelated sentence.
    """
    pairs = [(turns[i]["text"], turns[i + 1]) for i in range(0, len(turns) - 1, 2)
             if turns[i]["role"] == "operator" and turns[i + 1]["role"] == "genesis"]
    tail: list[tuple[str, dict[str, Any]]] = []
    for operator_text, reply in reversed(pairs):
        if not str(reply.get("command") or "").startswith("screen") or reply.get("command") == "screen.not_screen":
            break
        tail.append((operator_text, reply))
    return list(reversed(tail))[-HISTORY_TURNS:]


def _prompt(text: str, history: list[tuple[str, dict[str, Any]]], current: dict[str, Any] | None = None) -> str:
    lines = []
    for operator_text, reply in history:
        lines.append(f"TRADER: {operator_text}")
        screen = _screen_data(reply)
        if screen.get("scan"):
            lines.append(f"PREVIOUS SCAN: {json.dumps(screen['scan'])} -> {screen.get('count')} matches")
        lines.append(f"YOU SAID: {reply.get('text') or ''}")
    # The panel can edit the scan between chat turns; the edit is what the
    # trader is looking at, so it is what "only tech" refines.
    if current and current.get("scan"):
        lines.append(f"SCAN ON THE TRADER'S SCREEN NOW (what a refinement edits): {json.dumps(current['scan'])}")
    context = "\n".join(lines)
    return (f"CONVERSATION SO FAR:\n{context}\n\n" if context else "") + f"TRADER NOW: {text}"


def _screen_data(reply: dict[str, Any]) -> dict[str, Any]:
    raw = (reply.get("data") or {}).get("screen")
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}


def interpret(
    text: str, history: list[tuple[str, dict[str, Any]]], backend: Any, current: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Scan | None]:
    """One model call, plus one repair call if the scan names something that does not exist."""
    prompt = _prompt(text, history, current)
    for attempt in range(2):
        out = json_object(
            backend.complete(prompt, system=SYSTEM, max_tokens=1200, temperature=0.0).text,
            who="the screener model",
        )
        if out.get("intent") == "not_screen" or not out.get("scan"):
            return out, None
        try:
            return out, validate(out["scan"])
        except ScanError as exc:
            if attempt:
                raise DegradedError(f"the screener model kept proposing fields that do not exist: {exc}") from exc
            prompt += (f"\n\nYOUR LAST SCAN WAS REJECTED: {exc}. Use only the listed fields, "
                       "operators and sector names; move anything inexpressible to unsupported.")
    raise AssertionError("unreachable")


def _small_backend() -> Any:
    from genesis.config import load_config
    from genesis.llm.tiers import build_tier

    built = build_tier(load_config(), "small")
    if built.backend is None:
        raise DegradedError(
            f"no small-tier model ({built.note or 'not configured'}) -- type the scan instead, "
            "e.g. scr pe_forward<15 revenue_growth>10 sector=technology"
        )
    return built.backend


def _result(
    scan: Scan, snapshot: Snapshot, *, via: str, text: str,
    remember: Callable[[dict[str, Any]], None], out: dict[str, Any] | None = None,
) -> CommandResult:
    out = out or {}
    result = run(scan, snapshot)
    count, universe = result["count"], result["universe"]
    question, choices = out.get("question"), list(out.get("choices") or [])
    if not question and count == 0:
        question = "Nothing matches. Which threshold should I loosen?"
    elif not question and count > TOO_MANY:
        question = f"{count} is a lot to look through. Narrow it by sector, size or valuation?"
        choices = choices or ["only Technology", "market cap over $100B", "forward P/E under 20"]

    head = f"{count} of {universe} S&P 500 companies match."
    if out.get("understood"):
        head = f"{str(out['understood']).rstrip('.')}. {head}"
    if result["degraded"]:
        head += f" The snapshot is stale ({snapshot.as_of or 'never built'}) -- run scr refresh."
    unsupported = out.get("unsupported") or []
    if unsupported:
        head += " I couldn't express: " + "; ".join(f"{u.get('phrase')} ({u.get('why')})" for u in unsupported) + "."
    spoken = f"{head} {question}" if question else head

    missing = ", ".join(f"{n} without {f}" for f, n in result["missing"].items())
    payload = {**result, "scan": scan.to_dict(), "described": describe(scan), "expression": expression(scan), "terms": terms(scan),
               "understood": out.get("understood"), "asked": text,
               "readings": out.get("readings") or [], "unsupported": unsupported,
               "question": question, "choices": choices, "via": via}
    remember(payload)
    return CommandResult(
        True, f"screen.{via}", spoken,
        f"{describe(scan)} · snapshot {snapshot.as_of}" + (f" · excluded {missing}" if missing else ""),
        {"screen": json.dumps(payload, default=str)},
    )


def respond(
    text: str,
    history: list[tuple[str, dict[str, Any]]] | None = None,
    *,
    backend_fn: Callable[[], Any] = _small_backend,
    snapshot_fn: Callable[[], Snapshot] = load_snapshot,
    refresh_fn: Callable[[], dict[str, Any]] = build_snapshot,
    remember: Callable[[dict[str, Any]], None] = save_current,
    recall: Callable[[], dict[str, Any] | None] = load_current,
) -> CommandResult:
    """One chat turn. Never raises: a failure is a CommandResult that says why."""
    try:
        manual = re.match(r"^\s*scr\b\s*(.*)$", text, re.IGNORECASE | re.DOTALL)
        if manual and manual.group(1).strip().lower() == "refresh":
            report = refresh_fn()
            if not report["ok"]:
                raise DegradedError(
                    f"only {report['fetched']} of {report['members']} members came back; kept the old snapshot"
                )
            return CommandResult(
                True, "screen.refresh",
                f"Snapshot rebuilt: {report['fetched']} of {report['members']} S&P 500 companies.",
                f"{report['elapsed_s']}s · failed: {', '.join(report['failed']) or 'none'}",
            )

        snapshot = snapshot_fn()
        if not snapshot.rows:
            raise DegradedError("there is no S&P 500 snapshot yet -- run scr refresh (about a minute)")

        if manual:
            expr = manual.group(1).strip()
            if not expr:
                fields = ", ".join([*FIELDS, *TEXT_FIELDS])
                return CommandResult(True, "screen.help", "Type a scan, or just describe what you want.",
                                     f"scr pe_forward<15 revenue_growth>10 sector=technology sort:-roe top:20 · fields: {fields}")
            return _result(validate(parse_expression(expr)), snapshot, via="typed", text=text, remember=remember)

        out, scan = interpret(text, history or [], backend_fn(), recall())
        if out.get("intent") == "not_screen":
            return CommandResult(False, "screen.not_screen", "That isn't a screen.", "")
        if scan is None:
            question = out.get("question") or "What kind of company are you looking for?"
            payload = {"scan": None, "question": question, "choices": out.get("choices") or [],
                       "unsupported": out.get("unsupported") or [], "readings": [], "via": "model"}
            return CommandResult(True, "screen.clarify", question, "", {"screen": json.dumps(payload)})
        return _result(scan, snapshot, via="model", text=text, remember=remember, out=out)
    except ScanError as exc:
        return CommandResult(False, "screen.invalid", f"That scan doesn't work: {exc}", "; ".join(exc.problems))
    except GenesisError as exc:
        return CommandResult(False, "screen", exc.spoken_summary or f"The screener couldn't run: {exc.reason}", exc.reason)
    except Exception as exc:  # noqa: BLE001
        log.exception("screener turn crashed")
        return CommandResult(False, "screen", "The screener hit an error.", f"{type(exc).__name__}: {exc}")
