# Spec: Genesis Markdown/10-Architecture/Biological Design.md §reflex arc
"""What Genesis can be told to do, and how a sentence becomes an action.

This is the layer that was missing between "the voice stack can hear you" and
"something happens". :mod:`genesis.voice.reflex` already covers the five safety
reflexes -- halt, flatten, stop, pause, mute -- which bypass everything because
they must fire in milliseconds and must never be talked out of firing. This
module covers the rest of what a person actually says to a trading assistant.

**No model, deliberately.** ``LLM Model Tiers`` and Biological Design's reflex
arc both point the same way: *"open TradingView"* is not a judgement. It is a
fixed phrase mapping to a fixed action, and routing it through a language model
would add a second of latency, a token cost, an API dependency, and a small but
nonzero chance of the system deciding to do something else. Pattern matching is
not a shortcut here -- it is the correct mechanism, and it is why this works
with no API key and gives the same answer every time.

The escape hatch matters too: anything this module does *not* match is passed
up to the orchestrator, which may use a model. So the deterministic layer takes
the common, safety-adjacent and latency-sensitive cases, and judgement gets
what is genuinely judgement.

**Read-only, all of it.** Nothing here places an order. Opening a chart,
looking up a company, launching a desktop app -- afferent, every one. The
efferent path is Phase 7 and has its own approval gate; there is deliberately
no command in this table that could reach it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from genesis.errors import DegradedError, GenesisError

__all__ = [
    "COMMANDS",
    "Command",
    "CommandResult",
    "Match",
    "dispatch",
    "match_command",
]

log = logging.getLogger(__name__)

#: Apostrophes are DELETED rather than spaced, so "what's" becomes "whats"
#: rather than "what s" -- the second splits one word into two and no pattern
#: written for English matches it.
_APOSTROPHE = re.compile(r"['’]")
#: `_ < >` survive so a typed scan (`scr pe_trailing<20`) reaches the screener intact.
_PUNCT = re.compile(r"[^a-z0-9\s.\-^=:_<>]+")
_SPACE = re.compile(r"\s+")

#: Filler a speech-to-text engine happily transcribes and nobody means.
#: Stripped before matching so "genesis, um, open trading view please" hits the
#: same rule as "open tradingview".
#:
#: Deliberately SHORT. An earlier version also stripped "you", "can", "could"
#: and "would", which broke "what are you doing" into "what are doing" -- the
#: words are filler in "could you open X" and load-bearing in "what are you
#: doing", and no static list can tell those apart. Leaving them in costs
#: nothing, because every pattern uses `re.search` and tolerates words it does
#: not care about.
_FILLER = frozenset({"um", "uh", "er", "please", "hey", "ok", "okay"})

#: The wake word, stripped if the utterance opens with it. Tap-to-speak does
#: not require it -- the tap IS the addressing -- but people say it anyway.
_WAKE = "genesis"


def normalise(text: str) -> str:
    """Lowercase, depunctuated, filler-free. The form every rule matches on."""
    lowered = _PUNCT.sub(" ", _APOSTROPHE.sub("", (text or "").lower()))
    words = [w for w in _SPACE.sub(" ", lowered).strip().split(" ") if w]
    if words and words[0] == _WAKE:
        words = words[1:]
    return " ".join(w for w in words if w not in _FILLER)


@dataclass(frozen=True)
class CommandResult:
    """What happened, in a form both a screen and a speaker can use.

    ``spoken`` is separate from ``detail`` because they are different
    registers: a speaker wants one short sentence, a screen can take a table.
    Deriving one from the other always produces something bad at both.
    """

    ok: bool
    command: str
    spoken: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Match:
    """A matched command and the arguments pulled out of the sentence."""

    command: "Command"
    args: dict[str, str]
    phrase: str


@dataclass(frozen=True)
class Command:
    """One thing Genesis can be told to do.

    ``patterns`` are regexes against the normalised text. Named groups become
    ``args``. Ordered most-specific-first within the table, because "chart
    NVDA" and "what is NVDA" must not race.
    """

    name: str
    patterns: tuple[str, ...]
    run: Callable[[dict[str, str]], CommandResult]
    help: str = ""
    #: Spoken back the moment the command is recognised, before it runs. A
    #: launch takes seconds and silence reads as failure.
    ack: str | None = None
    #: A last word on the extracted args. ``False`` means "not this command"
    #: and matching moves on -- for a pattern that is right about the verb and
    #: can be wrong about the object.
    accepts: Callable[[dict[str, str]], bool] | None = None

    def match(self, text: str) -> Match | None:
        for pattern in self.patterns:
            hit = re.search(pattern, text)
            if hit:
                args = {k: v for k, v in hit.groupdict().items() if v}
                if self.accepts is not None and not self.accepts(args):
                    return None
                return Match(self, args, hit.group(0))
        return None


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------


def _open_tradingview(args: dict[str, str]) -> CommandResult:
    """Launch the TradingView desktop app, or report that it is already up.

    Uses the existing CDP module rather than a bare ``Popen``: it knows the
    binary's location, the ``ELECTRON_RUN_AS_NODE`` trap that makes a launch
    fail in a way that impersonates a missing app, and the remote-debugging
    port that everything else in the charting family needs to be open.
    """
    from genesis.tradingview import cdp

    # `version()` is the browser-level liveness check: it answers only when the
    # app is up AND the debugging port is open, which is exactly the condition
    # that makes launching unnecessary. Probing must never be the thing that
    # fails, so any error here just means "not up" and we launch.
    try:
        info = cdp.version()
        return CommandResult(
            True, "open_tradingview",
            "TradingView is already open.",
            f"Already answering on the CDP port — {info.get('Browser', 'unknown build')}.",
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        cdp.launch_desktop()
    except FileNotFoundError as exc:
        raise DegradedError(
            f"TradingView Desktop is not installed where Genesis expects it: {exc}"
        ) from exc
    except GenesisError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DegradedError(f"could not launch TradingView: {exc}") from exc

    return CommandResult(
        True, "open_tradingview", "Opening TradingView.",
        "Launched with the remote debugging port open.",
    )


def _chart(args: dict[str, str]) -> CommandResult:
    """Draw a marked-up chart. Deterministic all the way down -- no model."""
    from genesis.charting.compose import compose_default
    from genesis.charting.levels import compute_levels
    from genesis.charting.render import render
    from genesis.charting.structure import read_structure
    from genesis.config import load_config
    from genesis.marketdata.build import build_source
    from genesis.marketdata.source import resolve_symbol

    symbol = args["symbol"].upper()
    timeframe = args.get("timeframe") or "1D"
    config = load_config()
    symbol_id = resolve_symbol(symbol)

    built = build_source(config, "chart_markup")
    try:
        bars = built.source.fetch(symbol_id, timeframe)
    finally:
        built.store.close()
        built.budget.close()

    spec = compose_default(bars, compute_levels(bars), read_structure(bars))
    out = (
        config.memory.vault_path.expanduser()
        / "20-Charts"
        / f"{symbol_id.replace(':', '_')}_{timeframe}.png"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    render(bars, spec, path=out)

    return CommandResult(
        True, "chart",
        f"{symbol} {timeframe} charted. Last {bars.last:,.2f}.",
        f"{len(bars)} bars · {len(spec.levels())} levels · {bars.source} tier {bars.tier}",
        {"symbol": symbol_id, "timeframe": timeframe, "path": str(out),
         "last": f"{bars.last:.2f}", "source": bars.source, "tier": bars.tier},
    )


def _company(args: dict[str, str]) -> CommandResult:
    """Everything known about an issuer. Cached, so a repeat is instant."""
    from genesis.company.profile import resolve, summarise

    symbol = args["symbol"].upper()
    result = resolve(symbol)
    summary = summarise(result.profile)

    # "Apple Inc." already ends in a period; appending another gives
    # "Apple Inc..", which a speech synthesiser reads as a stumble.
    name = str(summary.get("name") or symbol).rstrip(".")
    bits = []
    if summary.get("price"):
        bits.append(f"{float(summary['price']):,.2f}")
    if summary.get("market_cap"):
        cap = float(summary["market_cap"])
        for cut, suffix in ((1e12, "trillion"), (1e9, "billion"), (1e6, "million")):
            if cap >= cut:
                bits.append(f"{cap / cut:.1f} {suffix} market cap")
                break
    if summary.get("pe_trailing"):
        bits.append(f"PE {float(summary['pe_trailing']):.0f}")

    # Guarded rather than relying on precedence: with no numbers this used to
    # render "Apple Inc..", which is what a profile whose market group had
    # expired actually produced.
    spoken = f"{name}. " + ", ".join(bits) + "." if bits else f"{name}."
    if not bits:
        spoken = f"{name}. I have the filings but no current price."
    return CommandResult(
        True, "company", spoken,
        f"{len(result.profile)} fields · {'cached' if result.from_cache else 'fetched'}"
        f" · {', '.join(summary['_sources'])}",
        {k: str(v) for k, v in summary.items() if not k.startswith("_")},
    )


def _canvas(args: dict[str, str]) -> CommandResult:
    """Open a research canvas on a subject. No model, and none needed.

    *"Show me what you found on Gann"* is a graph lookup, not a judgement:
    a label search over the [[Knowledge Graph]] and a canvas seeded from what
    comes back. Routing it through a model would add a second of latency and a
    chance of it deciding to do something else.

    The empty answer is a real answer and is spoken as one. A canvas that opens
    with nothing on it, saying so, is much better than silence -- it tells you
    the difference between *"no agent has researched this"* and *"the button is
    broken"*, which are the two things a person is actually wondering.
    """
    from genesis.config import load_config
    from genesis.memory.graph import KnowledgeGraph
    from genesis.research.canvas import CanvasStore

    from genesis.company.resolve import resolve_subject
    from genesis.screener.snapshot import load_snapshot

    subject = args["subject"].strip()
    memory = load_config().memory.db_path.parent
    store = CanvasStore(
        path=memory / "canvas.db", graph=KnowledgeGraph(path=memory / "graph.db")
    )
    # "Adobe" is searched as ADBE: the graph labels companies and their findings
    # by ticker, and a name search would open an empty canvas on a known company.
    query = subject
    try:
        rows = load_snapshot().rows
        ticker, _ = resolve_subject(subject, rows)
        if any(r.get("symbol") == ticker for r in rows):
            query = ticker
    except Exception:  # noqa: BLE001 - not a company: search the words as said
        pass
    canvas_id = store.open_for(query, title=subject, created_by="orchestrator")
    view = store.view(canvas_id).to_dict()
    count = len(view["nodes"])

    if not count:
        return CommandResult(
            True, "canvas",
            f"I have nothing on {subject} yet. The canvas is open and empty.",
            "Nothing in the knowledge graph matched. Research it first and it "
            "will appear here.",
            {"canvas_id": canvas_id, "nodes": "0", "subject": subject},
        )
    kinds: dict[str, int] = {}
    for node in view["nodes"]:
        kinds[node["type"]] = kinds.get(node["type"], 0) + 1
    parts = ", ".join(
        f"{n} {k}{('es' if k.endswith('s') else 's') if n > 1 else ''}" for k, n in sorted(kinds.items())
    )
    return CommandResult(
        True, "canvas",
        f"Opened a canvas on {subject}: {parts}.",
        f"{count} nodes, {len(view['edges'])} recorded links · canvas {canvas_id}",
        {"canvas_id": canvas_id, "nodes": str(count),
         "edges": str(len(view["edges"])), "subject": subject},
    )


def _notebook(args: dict[str, str]) -> CommandResult:
    """Open the notebook, optionally on a note — creating it if it is new.

    A title with no matching file is not a failure: this is the same authoring
    loop as clicking an unresolved ``[[link]]``, so the note is created and
    opened. *"note Gann cycles"* should leave you typing, not reading an error.

    Deterministic throughout. Finding a file by name is a directory lookup, and
    a model asked to do it would occasionally invent a path.
    """
    from genesis.notebook.links import LinkIndex
    from genesis.notebook.vault import registry

    vault = registry().open()
    title = (args.get("title") or "").strip()
    if not title:
        return CommandResult(
            True, "notebook", "Notebook open.",
            f"{vault.name} — {vault.root}", {"vault": vault.name},
        )

    index = LinkIndex(vault)
    hit = index.resolve(title)
    if hit.ambiguous:
        # Surfaced, never guessed — Operating Model §4.
        return CommandResult(
            True, "notebook",
            f"Several notes are called {title}. Which one?",
            " · ".join(hit.candidates),
            {"vault": vault.name, "candidates": ", ".join(hit.candidates)},
        )
    if hit.resolved:
        return CommandResult(
            True, "notebook", f"Opening {title}.", hit.path,
            {"vault": vault.name, "note_path": hit.path},
        )
    note = vault.create(f"{title}.md", f"# {title}\n\n")
    return CommandResult(
        True, "notebook", f"New note: {title}.", note.path,
        {"vault": vault.name, "note_path": note.path, "created": "true"},
    )


def _note_that(args: dict[str, str]) -> CommandResult:
    """Append a line to today's inbox note. The fastest possible capture.

    `00-Inbox/` is where [[Obsidian Vault Schema]] puts raw capture, and the
    agents read it. Spoken or typed, the same path — [[Operating Model]] §3.
    """
    from datetime import UTC, datetime

    from genesis.notebook.vault import registry

    vault = registry().open()
    text = args["text"].strip()
    stamp = datetime.now(UTC).strftime("%H:%M")
    note = vault.append(vault.daily_path(), f"- {stamp} — {text}")
    return CommandResult(
        True, "note_that", "Noted.", note.path,
        {"vault": vault.name, "note_path": note.path},
    )


def _search_notes(args: dict[str, str]) -> CommandResult:
    from genesis.notebook.vault import registry

    vault = registry().open()
    query = args["text"].strip()
    hits = vault.search(query, limit=20)
    if not hits:
        return CommandResult(
            True, "search_notes", f"Nothing in the notebook about {query}.",
            f"{vault.name} — searched every note", {"vault": vault.name, "hits": "0"},
        )
    plural = "s" if len(hits) > 1 else ""
    return CommandResult(
        True, "search_notes",
        f"{len(hits)} note{plural} mention {query}. First is {hits[0]['name']}.",
        " · ".join(h["path"] for h in hits[:5]),
        {"vault": vault.name, "hits": str(len(hits)), "note_path": hits[0]["path"],
         "query": query},
    )


def _screen(args: dict[str, str]) -> CommandResult:
    """Screen the S&P 500. No conversation here -- Ask Genesis adds that (see ``server.app``)."""
    from genesis.screener.chat import respond

    return respond(args["text"])


#: Words that point at the last screen rather than name tickers.
_SCREEN_REF = re.compile(r"\b(?:these|those|them|results?|screen|scan|matches)\b")
#: Glue between tickers in "NVDA AMD and TSM stocks" -- never a symbol.
_NOT_TICKERS = frozenset({"and", "&", "stocks", "tickers", "symbols", "names", "the", "a"})


def _watchlist(args: dict[str, str]) -> CommandResult:
    """Save tickers -- or the last screen's matches -- into a watchlist.

    The trader's own data, same door as the WL panel (`watchlist_routes`), so
    no approval gate: nothing here reaches an order path. A named list that
    exists is added to; otherwise a new one is created, auto-named from the
    screen it came from or from its first tickers.
    """
    from genesis.company.symbols import UnknownSymbol, normalise as canon
    from genesis.server.watchlist_routes import _store

    what = args.get("what", "").strip()
    name = args.get("name", "").strip()
    if not what or _SCREEN_REF.search(what):
        from genesis.screener.snapshot import load_current

        current = load_current() or {}
        symbols = [m["symbol"] for m in current.get("matches") or []]
        if not symbols:
            raise DegradedError("there is no screen to save -- run a screen or name the tickers")
        auto = str(current.get("understood") or current.get("described") or "Screen").rstrip(".")[:48]
        rejected: list[str] = []
    else:
        symbols, rejected = [], []
        for token in what.split():
            if token in _NOT_TICKERS:
                continue
            try:
                symbols.append(canon(token))
            except UnknownSymbol:
                rejected.append(token)
        if not symbols:
            raise DegradedError(f"no usable tickers in {what!r}")
        auto = " · ".join(symbols[:3]) + (f" +{len(symbols) - 3}" if len(symbols) > 3 else "")

    store = _store()
    existing = next((l for l in store.lists() if name and l["name"].lower() == name.lower()), None)
    if existing:
        list_id, title, verb = existing["id"], existing["name"], "Added"
    else:
        title = (name[:1].upper() + name[1:]) if name else auto
        list_id, verb = store.create(title), "Saved"
    symbols = list(dict.fromkeys(symbols))
    for sym in symbols:
        store.add(list_id, sym)
    plural = "s" if len(symbols) > 1 else ""
    spoken = f"{verb} {len(symbols)} ticker{plural} to watchlist {title}."
    if rejected:
        spoken += f" Skipped {', '.join(rejected)} -- not tickers."
    return CommandResult(
        True, "watchlist", spoken, " ".join(symbols),
        {"watchlist": list_id, "name": title, "symbols": ",".join(symbols)},
    )


#: Trailing words that describe the ask, not the company.
_ANALYSE_TAIL = re.compile(
    r"\s+(?:(?:and|then)\s+(?:save|put|write|give).*|as an investment|for me|stock|shares|"
    r"(?:a\s+)?(?:good\s+)?(?:investment|buy)|undervalued|overvalued|fairly valued|worth buying|"
    r"cheap|expensive|worth|again|fresh)$"
)


def _analyse_subject(raw: str) -> str:
    subject = raw.strip()
    while (trimmed := _ANALYSE_TAIL.sub("", subject)) != subject:
        subject = trimmed
    return re.sub(r"^(?:the\s+)?(?:company|stock|shares\s+of)\s+", "", subject)


#: More words than a company name has. "Archer-Daniels-Midland" is one word;
#: "adobe and its earnings has the price deviated" is a question.
_MAX_NAME_WORDS = 4


def _one_company(args: dict[str, str]) -> bool:
    """Is the object of "analyse ..." a single company, or a compound question?

    A compound question -- *"analyse Adobe and its earnings, has the price
    drifted from fair value"* -- is several pieces of work. The command table
    cannot split it and would search for a company called all of that, so it
    declines and the sentence goes to the planner, which can. Deterministic:
    a word count, never a model.
    """
    return 0 < len(_analyse_subject(args.get("subject", "")).split()) <= _MAX_NAME_WORDS


def _analyse(args: dict[str, str]) -> CommandResult:
    """Run Agent — Fundamental on one company and save the note to the vault.

    The same agent the planner dispatches for ``research.company``; this is the
    door that does not need the router to guess (Operating Model §1). The model
    call is the large tier, so this takes tens of seconds -- ``ack`` says so.
    """
    from genesis.agents.research.fundamental import FundamentalAgent
    from genesis.config import load_config
    from genesis.llm.tiers import build_tier
    from genesis.company.resolve import resolve_subject
    from genesis.research.findings import asks_for_fresh, fresh_enough
    from genesis.research.store import ResearchStore

    fresh = asks_for_fresh(args["subject"])
    subject = _analyse_subject(args["subject"])
    config = load_config()
    store = ResearchStore(path=config.memory.db_path.parent / "research.db", vault=config.memory.vault_path)

    # A read from this morning answers the same question this afternoon. Resolution
    # errors are left for the agent to raise, in its own words.
    try:
        ticker, _ = resolve_subject(subject)
    except Exception:  # noqa: BLE001
        ticker = None
    cached = store.current("symbol", ticker) if ticker and not fresh else None
    if cached is not None and fresh_enough(cached):
        return CommandResult(
            True, "analyse",
            f"As of {cached.created:%b %-d, %H:%M} UTC: {cached.summary} "
            f"Say analyse {ticker} again to rerun it.",
            cached.vault_path(),
            {"note_path": cached.vault_path(), "note_id": cached.id, "symbol": cached.subject,
             "verdict": str(cached.data.get("verdict") or ""),
             "degraded": "false", "reused": "true"},
        )
    note, how = FundamentalAgent(store, backend=build_tier(config, "large").backend).analyse(subject)
    spoken = f"{note.summary} Saved to your notes as {note.subject}."
    if how:
        spoken = f"Resolved {how}. {spoken}"
    if note.degraded:
        spoken += " It's marked degraded."
    return CommandResult(
        True, "analyse", spoken, note.vault_path(),
        {"note_path": note.vault_path(), "note_id": note.id, "symbol": note.subject,
         "verdict": str(note.data.get("verdict") or ""), "degraded": str(note.degraded).lower()},
    )


def _status(args: dict[str, str]) -> CommandResult:
    """What is Genesis doing? The honest answer is usually 'nothing'."""
    return CommandResult(
        True, "status",
        "Idle. Nothing running.",
        "Genesis acts when asked. No autonomous loop is enabled.",
    )


#: The table. Ordered: the first command whose pattern matches wins, so
#: specific phrasings must precede general ones.
#:
#: Symbols are captured loosely (`[a-z0-9.\-^=:]{1,24}`) and validated by the
#: action, not the pattern -- a regex that only accepted known tickers would
#: silently fail to match a real one rather than saying "I don't know that
#: symbol", and the second is a far better failure.
COMMANDS: tuple[Command, ...] = (
    Command(
        name="open_tradingview",
        patterns=(
            r"\b(?:open|launch|start|bring up)\s+(?:up\s+)?trading\s*view\b",
            r"\btrading\s*view\s+(?:open|up)\b",
        ),
        run=_open_tradingview,
        help="open tradingview",
        ack="Opening TradingView.",
    ),
    # Before `chart` and `company`, and the patterns are tight for that reason:
    # "show me what you found on X" must not be eaten by the company lookup's
    # "look up X", and "canvas NVDA" must not become a chart.
    # Before `chart` and `company`: "note that NVDA looks heavy" is a note, and
    # both of those would happily eat the tail of it.
    # Before `screen`, `chart` and `company`: "save these stocks to a watchlist"
    # is not a scan, and "add NVDA to my semis watchlist" is not a chart.
    Command(
        name="watchlist",
        patterns=(
            r"\b(?:save|add|put|store)\s+(?P<what>.*?)\s*(?:to|into|in|as)\s+(?:a\s+|my\s+|the\s+)?"
            r"(?:new\s+)?watch\s*list(?:\s+(?:called|named|titled)\s+(?P<name>.+))?$",
            r"\b(?:save|add|put|store)\s+(?P<what>.*?)\s*(?:to|into|in)\s+(?:my\s+|the\s+)"
            r"(?P<name>.+?)\s+watch\s*list$",
            r"\b(?:create|make|start|new)\s+(?:a\s+)?(?:new\s+)?watch\s*list"
            r"(?:\s+(?:called|named)\s+(?P<name>.+?))?(?:\s+(?:with|of|for|from)\s+(?P<what>.+))?$",
        ),
        run=_watchlist,
        help="save these to a watchlist",
        ack="Saving the watchlist.",
    ),
    # Before `note_that`, `screen` and `company`: "analyse NVDA and save it to my
    # notes" is an analysis, and "what is NVDA worth" is not a profile lookup.
    Command(
        name="analyse",
        patterns=(
            r"\b(?:analy[sz]e|evaluate|do (?:an?\s+)?(?:\S+\s+)?analysis (?:on|of)|"
            r"(?:company|stock|investment|fundamental|value)\s+analysis\s+(?:on|of|for)|"
            r"(?:fair|intrinsic)\s+value\s+(?:of|for)|valuation\s+(?:of|for)|"
            r"due diligence on|deep dive (?:on|into))\s+(?P<subject>.+)$",
            r"\bis\s+(?P<subject>\S+(?:\s+\S+)?)\s+(?:a\s+good\s+investment|a\s+buy|undervalued|"
            r"overvalued|fairly\s+valued|worth\s+buying)\b.*$",
            r"\bwhat\s+is\s+(?P<subject>\S+(?:\s+\S+)?)\s+(?:really\s+)?worth\b.*$",
        ),
        run=_analyse,
        accepts=_one_company,
        help="analyse NVDA",
        ack="Analysing — this takes about a minute.",
    ),
    Command(
        name="note_that",
        patterns=(
            r"\bnote\s+(?:that|down)\s+(?P<text>.+)$",
            r"\b(?:make|take|jot down)\s+a\s+note\s*[:,]?\s*(?P<text>.+)$",
        ),
        run=_note_that,
        help="note that NVDA looks heavy into earnings",
        ack="Noting that.",
    ),
    Command(
        name="search_notes",
        patterns=(
            r"\bsearch\s+(?:my\s+)?(?:notes|notebook)\s+(?:for\s+)?(?P<text>.+)$",
            r"\bfind\s+(?:my\s+)?notes?\s+(?:on|about|for)\s+(?P<text>.+)$",
        ),
        run=_search_notes,
        help="search notes for gann",
        ack="Searching your notes.",
    ),
    Command(
        name="notebook",
        patterns=(
            r"\b(?:open|show|show me|bring up)\s+(?:the\s+|my\s+)?"
            r"(?:notebook|notes)(?:\s+(?:on|about|for)\s+(?P<title>.+))?$",
            r"\b(?:open|new)\s+note\s+(?P<title>.+)$",
            r"^note(?:book)?$",
        ),
        run=_notebook,
        help="open note Gann cycles",
        ack="Opening the notebook.",
    ),
    Command(
        name="canvas",
        patterns=(
            r"\b(?:open|show|show me|bring up)\s+(?:a\s+|the\s+)?"
            r"(?:research\s+)?(?:canvas|graph|board)\s+"
            r"(?:on|for|about|of)\s+(?P<subject>.+)$",
            r"\bshow me what you(?:'ve| have)?\s+(?:found|got|know|learned)\s+"
            r"(?:on|about)\s+(?P<subject>.+)$",
            r"\bwhat do you know about\s+(?P<subject>.+)$",
            r"\b(?:canvas|graph)\s+(?P<subject>.+)$",
        ),
        run=_canvas,
        help="show me what you found on Gann",
        ack="Opening the canvas.",
    ),
    # Before `chart` and `company`. A sentence about *which companies* is a
    # screen; the interpreter hands back `screen.not_screen` when it is not,
    # and the server passes that on to the analyst.
    Command(
        name="screen",
        patterns=(
            r"^(?P<text>scr\b.*)$",
            r"^(?P<text>.*\b(?:screen|scan)\b.*)$",
            r"^(?P<text>.*\b(?:find|show|list|give|get)\s+(?:me\s+)?(?:\S+\s+){0,6}?"
            r"(?:stocks|companies|names|equities)\b.*)$",
            r"^(?P<text>.*\b(?:which|what)\s+(?:\S+\s+){0,6}?(?:stocks|companies)\b.*)$",
            # No verb at all: "stocks well below their 52 week high" reached the
            # analyst, which has no screener and said so. A noun plus a
            # qualifier is a screen; so is a short noun phrase ("cheap tech
            # stocks"). Over-catching costs one small-tier call -- the
            # interpreter answers `not_screen` and the server hands it on.
            r"^(?P<text>.*\b(?:stocks|companies|names|equities|shares)\s+(?:\S+\s+){0,3}?"
            r"(?:with|that|which|where|whose|below|above|under|over|near|trading|paying|at|"
            r"down|up|off|beaten|growing|yielding)\b.*)$",
            r"^(?P<text>(?:\S+\s+){1,4}(?:stocks|companies|equities))$",
        ),
        run=_screen,
        help="find profitable tech companies growing revenue over 20%",
        ack="Screening the S&P 500.",
    ),
    Command(
        name="chart",
        patterns=(
            r"\b(?:chart|draw|show me a chart of|pull up a chart of)\s+"
            r"(?P<symbol>[a-z0-9.\-^=:]{1,24})"
            r"(?:\s+(?:on\s+)?(?:the\s+)?(?P<timeframe>1m|5m|15m|30m|1h|4h|"
            r"1d|1w|1mo|daily|hourly|weekly|monthly))?\b",
        ),
        run=_chart,
        help="chart NVDA [daily]",
        ack="Charting.",
    ),
    Command(
        name="company",
        patterns=(
            # `research` is deliberately NOT a verb here. "research W.D. Gann"
            # matched this pattern and resolved to a ticker lookup for "w.d" --
            # Operating Model §4's "nobody knows the ticker" failure, arrived at
            # by a regex instead of by a model. Not everything is a symbol, and
            # a research request now falls through to the planner, which has a
            # topic researcher to give it to.
            # The symbol ENDS the sentence, and is not an article.
            #
            # Unanchored, this matched the first word after "what is" —
            # so *"what is a stock split"* looked up `A` (Agilent) and
            # *"what is the market doing"* looked up `MARKET`. Both answered
            # confidently with a company nobody asked about, which is
            # Operating Model §4's "nobody knows the ticker" failure arrived
            # at by a regex: ambiguity guessed instead of surfaced.
            #
            # A question that continues past the symbol is not a lookup, and
            # belongs to the orchestrator. Losing "what is NVDA trading at"
            # to the reasoner is the right trade -- it has tools and a price
            # is not a profile.
            r"\b(?:whats|what is|tell me about|look ?up|profile)\s+"
            r"(?:the\s+)?(?:company\s+)?"
            r"(?!(?:a|an|the|it|this|that|there|they|we|going|happening)$)"
            r"(?P<symbol>[a-z0-9.\-^=:]{1,24})$",
            r"\b(?P<symbol>[a-z0-9.\-]{1,24})\s+(?:profile|fundamentals|overview)\b",
        ),
        run=_company,
        help="what is NVDA",
        ack="Looking that up.",
    ),
    Command(
        name="status",
        patterns=(r"\b(?:status|what are you doing|what'?s running|are you busy)\b",),
        run=_status,
        help="status",
    ),
)


def match_command(text: str, commands: Sequence[Command] = COMMANDS) -> Match | None:
    """First command whose pattern matches the normalised utterance."""
    normalised = normalise(text)
    if not normalised:
        return None
    for command in commands:
        hit = command.match(normalised)
        if hit is not None:
            return hit
    return None


def dispatch(text: str, commands: Sequence[Command] = COMMANDS) -> CommandResult:
    """Sentence in, action out. Raises nothing a caller has to guess about.

    An unmatched utterance is **not** an error -- it is the boundary of the
    deterministic layer, and the honest response is to say so and hand it up
    rather than to guess at an action. Guessing is the failure mode that makes
    a voice assistant frightening rather than useful.
    """
    hit = match_command(text, commands)
    if hit is None:
        return CommandResult(
            False, "unmatched",
            "I didn't catch a command in that.",
            "Try: " + " · ".join(c.help for c in commands if c.help),
            {"heard": text, "normalised": normalise(text)},
        )
    try:
        return hit.command.run(hit.args)
    except GenesisError as exc:
        # A typed failure is the honest answer. Never a fabricated success.
        return CommandResult(
            False, hit.command.name,
            exc.spoken_summary or f"That didn't work: {exc.reason}",
            exc.reason,
            {"failure_class": exc.failure_class},
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("command %s crashed", hit.command.name)
        return CommandResult(
            False, hit.command.name,
            "Something went wrong running that.",
            f"{type(exc).__name__}: {exc}",
        )
