# Spec: Genesis Markdown/60-UI/Automation.md §Templates
"""Ready-made workflows: open one in WB, check its settings, save it as your own.

Templates are code, not rows. They are reviewed in a diff like a cadence is,
and opening one creates an unsaved, disabled copy -- nothing here schedules
anything until the operator saves and enables it (Safety Invariants #9).

Every template is validated as a :class:`Workflow` at import, so a template that
names a node, a setting or a tool the runtime would refuse fails loudly here,
not on the canvas. ``tests/automation/test_templates.py`` goes further: every
tool is an enabled server in the catalogue, every agent is a built agent, every
process a template names is itself a template.

The tool arguments below were read from each server's live schema on
2026-09-13 -- e.g. the gainers screener needs ``provider: yfinance`` (no key) and
reports ``percent_change`` as a fraction, so 5% is ``0.05``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from genesis.automation.workflow import TRIGGER_INPUT, Workflow

__all__ = ["TEMPLATES", "Template", "by_id"]

WATCHLIST = "Stocks"
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]


@dataclass(frozen=True)
class Template:
    id: str
    job: str
    name: str
    description: str
    body: dict[str, Any]
    #: What to check before enabling — the settings most likely to need your values.
    setup: tuple[str, ...] = ()
    process: bool = False
    workflow: Workflow = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workflow", Workflow.model_validate(self.body))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "job": self.job, "name": self.name, "description": self.description,
                "setup": list(self.setup), "process": self.process, "body": self.body}


# -- building blocks ---------------------------------------------------------


def action(step_id: str, name: str, **params: Any) -> dict[str, Any]:
    return {"id": step_id, "kind": "action", "action": name, "params": params}


def tool(step_id: str, capability: str, **args: Any) -> dict[str, Any]:
    return {"id": step_id, "kind": "gather", "capability": capability, "args": args}


def stop(step_id: str, message: str) -> dict[str, Any]:
    return action(step_id, "logic.stop", message=message)


def layout(steps: list[dict[str, Any]], start: str | None) -> dict[str, dict[str, int]]:
    """Left to right along `next`; a fail branch drops to the lane below."""
    by_id = {s["id"]: s for s in steps}
    at: dict[str, dict[str, int]] = {"trigger": {"x": 0, "y": 120}}
    lanes = [0]

    def place(step_id: str | None, col: int, lane: int) -> None:
        while step_id and step_id not in at:
            at[step_id] = {"x": 270 * col, "y": 120 + 150 * lane}
            step = by_id[step_id]
            if step.get("on_fail"):
                lanes[0] += 1
                place(step["on_fail"], col + 1, lanes[0])
            step_id, col = step.get("next"), col + 1

    place(start, 1, 0)
    return at


def chain(*steps: dict[str, Any]) -> list[dict[str, Any]]:
    """Wire steps in order through `next`, unless a step already says where it goes.

    Steps wrapped in :func:`branch` are fail-edge leaves and stay off the main line.
    """
    out = [dict(s) for s in steps]
    main = [s for s in out if not s.get("branch")]
    for here, after in zip(main, main[1:]):
        here.setdefault("next", after["id"])
    for s in out:
        s.pop("branch", None)
    return out


def branch(step: dict[str, Any]) -> dict[str, Any]:
    """A step that only runs from a fail edge — not part of the main line."""
    return {**step, "branch": True}


def flow(tid: str, name: str, trigger: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    start = steps[0]["id"] if steps else None
    return {"id": tid, "name": name, "trigger": trigger, "start": start, "steps": steps,
            "layout": layout(steps, start)}


def weekday_gate(step_id: str = "weekdays", days: list[str] | None = None) -> list[dict[str, Any]]:
    return [
        {**action(step_id, "logic.days", days=days or WEEKDAYS), "on_fail": f"{step_id}-skip"},
        branch(stop(f"{step_id}-skip", "not a scheduled day")),
    ]


def daily(at: str) -> dict[str, Any]:
    return {"type": "cron", "at": at}


def market_hours(minutes: int) -> dict[str, Any]:
    return {"type": "market-open", "interval_sec": minutes * 60}


def closed(hours: int) -> dict[str, Any]:
    return {"type": "market-closed", "interval_sec": hours * 3600}


ON_DEMAND = {"type": "on-demand"}
PRE = "Pre-market prep"
INTRA = "Intraday monitoring"
CLOSE = "After the close"
NIGHT = "Overnight & weekly"
REVIEW = "Reviews"
PROC = "Reusable processes"


# -- the templates -----------------------------------------------------------

TEMPLATES: tuple[Template, ...] = (
    Template(
        "morning-news-synopsis", PRE, "Morning news synopsis",
        "Weekdays 07:00: pull Tesla headlines; with enough news, Topic Researcher writes a sourced synopsis "
        "to the research directory; with none, you get a quiet-morning alert.",
        flow("morning-news-synopsis", "Morning news synopsis", daily("07:00"), chain(
            *weekday_gate(),
            tool("news", "news.company", symbol="TSLA", count=20),
            {**action("enough", "logic.count", op=">=", value=3), "input": "news", "on_fail": "quiet"},
            branch(action("quiet", "output.alert", title="No Tesla news this morning",
                          message="Fewer than 3 headlines came back.", urgency="never")),
            action("synopsis", "agent.research", subject="Tesla news today", depth="quick"),
            {**action("tell", "output.alert", title="Tesla brief on the way",
                      message="{count} headlines — Topic Researcher is writing today's synopsis."),
             "input": "enough"},
        )),
        setup=("Change TSLA on the news node to the company you follow.",
               "Needs the tool gateway (genesis serve) — Topic Researcher searches the web."),
    ),
    Template(
        "gap-and-catalyst-scan", PRE, "Gap and catalyst scan",
        "08:45 in pre-market: the biggest gainers over 5%, top ten, alerted and written to today's inbox note.",
        flow("gap-and-catalyst-scan", "Gap and catalyst scan", daily("08:45"), chain(
            {**action("premarket", "logic.session", sessions=["premarket"]), "on_fail": "not-premarket"},
            branch(stop("not-premarket", "not pre-market (weekend or holiday)")),
            tool("gainers", "screen.gainers", provider="yfinance", limit=50),
            {**action("over-5", "data.filter", field="percent_change", op=">", value="0.05"), "input": "gainers"},
            {**action("top-10", "data.take", count=10), "input": "over-5"},
            {**action("count", "logic.count", op=">=", value=1), "input": "top-10", "on_fail": "no-gaps"},
            branch(stop("no-gaps", "nothing gapping over 5%")),
            {**action("alert", "output.alert", title="Pre-market gappers: {symbols}", message="{items}"),
             "input": "count"},
            {**action("log", "output.note", heading="## Gappers — {time} ET", template="{items}"), "input": "count"},
        )),
        setup=("The screener reports percent_change as a fraction: 0.05 = 5%.",),
    ),
    Template(
        "earnings-week-heads-up", PRE, "Earnings week heads-up",
        "Weekdays 07:30: next earnings dates for your watchlist; alerts on anything reporting in the next 7 days.",
        flow("earnings-week-heads-up", "Earnings week heads-up", daily("07:30"), chain(
            *weekday_gate(),
            action("dates", "market.earnings-dates", watchlist=WATCHLIST),
            {**action("this-week", "data.date-window", field="earnings_date", from_days=0, to_days=7),
             "input": "dates"},
            {**action("any", "logic.count", op=">=", value=1), "input": "this-week", "on_fail": "none"},
            branch(stop("none", "no earnings in the next 7 days")),
            {**action("alert", "output.alert", title="Earnings this week: {symbols}", message="{items}"),
             "input": "any"},
        )),
        setup=(f"Uses the '{WATCHLIST}' watchlist — pick yours.",),
    ),
    Template(
        "economic-calendar-brief", PRE, "Economic calendar brief",
        "Weekdays 06:30: today's scheduled US data releases from FRED, written to today's inbox note.",
        flow("economic-calendar-brief", "Economic calendar brief", daily("06:30"), chain(
            *weekday_gate(),
            tool("releases", "macro.release-calendar", realtime_start="{date}", realtime_end="{week_ahead}",
                 include_release_dates_with_no_data=True, sort_order="asc", limit=200),
            {**action("today", "data.date-window", field="date", from_days=0, to_days=0), "input": "releases"},
            {**action("unique", "data.dedupe", field="release_name"), "input": "today"},
            {**action("brief", "data.template", template="Today's releases ({count}):\n{items}"), "input": "unique"},
            {**action("log", "output.note", heading="## Economic calendar — {date}", template="{text}"),
             "input": "brief"},
        )),
        setup=("{date} and {week_ahead} are filled in when it runs.",),
    ),
    Template(
        "watchlist-oversold-alert", INTRA, "Watchlist oversold alert",
        "Every 15 min in market hours: hourly RSI(14) under 30 for any watchlist symbol, at most one alert per 2 hours.",
        flow("watchlist-oversold-alert", "Watchlist oversold alert", market_hours(15), chain(
            action("symbols", "watchlist.read", watchlist=WATCHLIST),
            {**action("oversold", "signal.indicator", timeframe="1H", indicator="rsi", period=14, op="<", value=30),
             "input": "symbols", "each": True, "on_fail": "none"},
            branch(stop("none", "nothing oversold")),
            {**action("cooldown", "logic.cooldown", minutes=120), "on_fail": "cooling"},
            branch(stop("cooling", "alerted within 2 hours")),
            {**action("alert", "output.alert", title="{count} oversold: {symbols}", message="{text}"),
             "input": "oversold"},
        )),
        setup=(f"Uses the '{WATCHLIST}' watchlist.", "Change 1H / 30 for a different read."),
    ),
    Template(
        "price-level-alert", INTRA, "Price level alert",
        "Every 5 min in market hours: tells you when NVDA trades above 250 — once per 4 hours.",
        flow("price-level-alert", "Price level alert", market_hours(5), chain(
            {**action("level", "signal.price", symbol="NVDA", direction="above", level=250), "on_fail": "not-yet"},
            branch(stop("not-yet", "not through the level")),
            {**action("alert", "output.alert", title="NVDA through 250", message="{text}", cooldown_minutes=240),
             "input": "level"},
        )),
        setup=("Set your symbol, direction and level.",),
    ),
    Template(
        "big-mover-watch", INTRA, "Big mover watch",
        "Every 10 min in market hours: any watchlist symbol moving 4% either way — alerted when the list changes.",
        flow("big-mover-watch", "Big mover watch", market_hours(10), chain(
            action("symbols", "watchlist.read", watchlist=WATCHLIST),
            {**action("movers", "signal.move", direction="either", percent=4), "input": "symbols", "each": True,
             "on_fail": "quiet"},
            branch(stop("quiet", "no big movers")),
            {**action("new", "logic.changed"), "input": "movers", "on_fail": "same"},
            branch(stop("same", "same movers as last check")),
            {**action("alert", "output.alert", title="Movers: {symbols}", message="{text}"), "input": "movers"},
        )),
        setup=(f"Uses the '{WATCHLIST}' watchlist.",),
    ),
    Template(
        "breakout-scanner", INTRA, "Breakout scanner",
        "Every 30 min in market hours: closes above the 20-day high on 2× volume, alerted and collected in a "
        "'Breakouts' watchlist.",
        flow("breakout-scanner", "Breakout scanner", market_hours(30), chain(
            action("symbols", "watchlist.read", watchlist=WATCHLIST),
            {**action("breakout", "signal.breakout", timeframe="1D", lookback=20, direction="high"),
             "input": "symbols", "each": True, "on_fail": "none"},
            branch(stop("none", "no breakouts")),
            {**action("volume", "signal.volume", timeframe="1D", lookback=20, multiple=2),
             "input": "breakout", "each": True, "on_fail": "thin"},
            branch(stop("thin", "breakouts, but not on volume")),
            {**action("alert", "output.alert", title="Breakouts on volume: {symbols}", message="{text}",
                      cooldown_minutes=180), "input": "volume"},
            {**action("collect", "watchlist.add", watchlist="Breakouts", create=True), "input": "volume"},
        )),
        setup=(f"Scans the '{WATCHLIST}' watchlist; writes to 'Breakouts' (created if missing).",),
    ),
    Template(
        "headline-keyword-watch", INTRA, "Headline keyword watch",
        "Every 15 min in market hours: market headlines mentioning downgrades, guidance, the SEC, halts, lawsuits "
        "or recalls — alerted only when new ones appear.",
        flow("headline-keyword-watch", "Headline keyword watch", market_hours(15), chain(
            tool("news", "news.market", category="general"),
            {**action("keywords", "logic.contains", keywords="downgrade, guidance, sec, halt, lawsuit, recall",
                      field="headline"), "input": "news", "on_fail": "nothing"},
            branch(stop("nothing", "no matching headlines")),
            {**action("new", "logic.changed"), "input": "keywords", "on_fail": "seen"},
            branch(stop("seen", "already alerted on these")),
            {**action("alert", "output.alert", title="{count} headlines to read", message="{items}"),
             "input": "keywords"},
        )),
        setup=("Edit the keyword list to your own triggers.",),
    ),
    Template(
        "end-of-day-wrap", CLOSE, "End-of-day wrap",
        "Weekdays 16:30: your watchlist ranked by the day's move, written to today's inbox note, then a "
        "one-day performance tearsheet.",
        flow("end-of-day-wrap", "End-of-day wrap", daily("16:30"), chain(
            *weekday_gate(),
            action("quotes", "market.watchlist-quotes", watchlist=WATCHLIST),
            {**action("ranked", "data.sort", field="change_pct", order="descending"), "input": "quotes"},
            {**action("board", "data.template", template="Today's board ({date}):\n{items}"), "input": "ranked"},
            {**action("log", "output.note", heading="## Close — {date}", template="{text}"), "input": "board"},
            action("tearsheet", "agent.performance", days=1),
        )),
        setup=(f"Uses the '{WATCHLIST}' watchlist.", "The Digest already writes its own 16:30 recap."),
    ),
    Template(
        "daily-movers", CLOSE, "Daily movers",
        "Weekdays 16:10: the S&P 500's five biggest gainers and losers, the news behind them read and "
        "summarised, written to a dated note in 'Daily Movers' and journalled as an observation.",
        flow("daily-movers", "Daily movers", daily("16:10"), chain(
            *weekday_gate(),
            action("movers", "market.index-movers", index="SPX", top=5),
            {**action("symbols", "data.symbols"), "input": "movers"},
            {**action("brief", "news.brief", hours=12, max_articles=10, symbols="{symbols}",
                      title="Daily movers — {date}",
                      focus="Why did these names move today? One paragraph per name, and say when the "
                            "news does not explain the move."), "input": "symbols"},
            {**action("note", "output.note", path="Daily Movers/{date}", mode="replace",
                      heading="# Daily movers — {date}", template="{text}"), "input": "brief"},
            {**action("journal", "journal.observe", kind="movers.daily", subject="{date}",
                      summary="S&P 500 top five movers each way, with the news behind them."),
             "input": "note"},
            {**action("alert", "output.alert", title="Daily movers — {symbols}", message="{text}"),
             "input": "movers"},
        )),
        setup=("The note replaces itself on a re-run, so the same day never stacks copies.",
               "The brief runs the large model and its text is third-party reporting — read it, "
               "do not feed it to another agent.",
               "Change the index on the movers node for Nasdaq-100, Dow or small caps."),
    ),
    Template(
        "insider-and-filing-sweep", CLOSE, "Insider and filing sweep",
        "Weekdays 18:00: every SEC filing in the last day for your watchlist — 8-Ks, Form 4 insider trades and "
        "the rest — alerted when there is something new and logged to the inbox.",
        flow("insider-and-filing-sweep", "Insider and filing sweep", daily("18:00"), chain(
            *weekday_gate(),
            action("symbols", "watchlist.read", watchlist=WATCHLIST),
            {**tool("filings", "filings.recent", days=1, limit=20), "input": "symbols", "each": True,
             "each_arg": "identifier"},
            # The SEC server returns recent filings regardless of `days` when given a
            # company (seen live 2026-09-13), so the window is enforced here.
            {**action("recent", "data.date-window", field="filing_date", from_days=-1, to_days=0),
             "input": "filings"},
            {**action("any", "logic.count", op=">=", value=1), "input": "recent", "on_fail": "none"},
            branch(stop("none", "no new filings")),
            {**action("new", "logic.changed"), "input": "any", "on_fail": "seen"},
            branch(stop("seen", "nothing new since last sweep")),
            {**action("alert", "output.alert", title="{count} new SEC filings on your watchlist", message="{items}"),
             "input": "any"},
            {**action("log", "output.note", heading="## SEC filings — {date}", template="{items}"), "input": "any"},
        )),
        setup=(f"Uses the '{WATCHLIST}' watchlist. Set form_type to 8-K or 4 on the filings node to narrow it.",),
    ),
    Template(
        "data-refresh", NIGHT, "Data refresh",
        "Once a day while the market is closed: fill daily price history for your watchlist, then alert on any "
        "symbol whose data is still stale.",
        flow("data-refresh", "Data refresh", closed(24), chain(
            action("symbols", "watchlist.read", watchlist=WATCHLIST),
            {**action("update", "maint.update-bars", timeframe="1D", bars=300), "input": "symbols"},
            {**action("fresh", "maint.bars-fresh", timeframe="1D", max_age_hours=96), "input": "update",
             "each": True, "on_fail": "stale"},
            branch(action("stale", "output.alert", title="Stale price data", message="{text}")),
        )),
        setup=(f"Uses the '{WATCHLIST}' watchlist. 96h tolerates a long weekend.",),
    ),
    Template(
        "weekly-review", NIGHT, "Weekly review",
        "Sundays 10:00: a week's performance review written to Reviews/ in your notebook, plus "
        "backtest-vs-live drift and a month of insight mining.",
        flow("weekly-review", "Weekly review", daily("10:00"), chain(
            # The cron is daily — `Cadence` has no weekday — so Sunday lives
            # here, in the gate, and this is the only place it is expressed.
            *weekday_gate("sunday", ["sun"]),
            # `journal.tearsheet`, not `agent.performance`: dispatch is
            # fire-and-forget and returns a receipt, so a note step after it
            # saves "handed to performance-analyst" instead of the review.
            action("review", "journal.tearsheet", days=7),
            {**action("save", "output.note", mode="replace",
                      path="Reviews/{date} Weekly review.md",
                      heading="# Weekly review — {date}", template="{text}"),
             "input": "review"},
            action("drift", "agent.drift", days=7),
            action("insights", "agent.insights", days=30),
            {**action("tell", "output.alert", title="Weekly review saved",
                      message="Reviews/{date} Weekly review.md — drift and insight passes are queued behind it."),
             "input": "review"},
        )),
        setup=("Journal agents report honestly when there are no trades yet.",
               "The review lands in Reviews/ in your notebook; drift and insights land in the journal."),
    ),
    Template(
        "housekeeping", NIGHT, "Housekeeping",
        "Sundays 03:00: re-index the trading corpus and rebuild the spec vault map.",
        flow("housekeeping", "Housekeeping", daily("03:00"), chain(
            *weekday_gate("sunday", ["sun"]),
            {"id": "corpus", "kind": "refresh", "target": "corpus-index"},
            {"id": "vault-map", "kind": "refresh", "target": "vault-map"},
        )),
        setup=("The corpus index needs the external SSD mounted.",),
    ),
    Template(
        "weekend-news-review", REVIEW, "Weekend news review",
        "Sundays 17:00: refreshes headlines, reads the weekend's top stories in full, and writes a market synopsis "
        "with themes, trade ideas and risks to Reviews/ in your notebook (Journal page).",
        flow("weekend-news-review", "Weekend news review", daily("17:00"), chain(
            # The cron is daily — `Cadence` has no weekday — so Sunday is a
            # gate, exactly as the weekly review does it. 17:00 ET is an hour
            # before the futures open: late enough to have the whole weekend's
            # news, early enough to still be a plan rather than a reaction.
            *weekday_gate("sunday", ["sun"]),
            {**action("brief", "news.brief", hours=72, max_articles=12, refresh=True,
                      focus="market-moving news and trade setups for the week ahead",
                      title="Weekend news review — {date}"), "on_fail": "no-brief"},
            branch({**action("no-brief", "output.alert", title="Weekend news review could not be written",
                             message="{text}", urgency="if-present"), "input": "brief"}),
            {**action("save", "output.note", path="Reviews/{date} Weekend news review.md", mode="replace",
                      heading="# Weekend news review — {date}", template="{text}"), "input": "brief"},
            # The brief's trade ideas become real ideas here. Without this step
            # they are prose in a note: nothing ranks them, nothing sizes them
            # through the gate, and nothing can say later whether they worked.
            {**action("ideas", "news.ideas", horizon_days=5, extract=4), "input": "brief"},
            {**action("tell", "output.alert", title="Weekend news review saved",
                      message="{stories} stories, {trade_ideas} trade ideas from {articles} articles — "
                              "Reviews/{date} Weekend news review.md. Open TI for the ideas."),
             "input": "brief"},
        )),
        setup=("Runs the large model (Settings → Model tiers).",
               "Sunday 17:00 ET, an hour before the futures open. Change the hour on the trigger node, or the day "
               "on the first gate.",
               "72 hours of headlines covers Friday's close through Sunday evening."),
    ),
    # -- processes: reusable blocks, run as one step from any workflow --------
    Template(
        "scan-a-list-for-setups", PROC, "Scan a list for setups",
        "Give it symbols: keeps those with daily RSI under 35 on 1.5× volume, returns them as a list. Fails "
        "(takes the caller's fail edge) when nothing qualifies.",
        flow("scan-a-list-for-setups", "Scan a list for setups", ON_DEMAND, chain(
            {**action("oversold", "signal.indicator", timeframe="1D", indicator="rsi", period=14, op="<", value=35),
             "input": TRIGGER_INPUT, "each": True},
            {**action("volume", "signal.volume", timeframe="1D", lookback=20, multiple=1.5), "input": "oversold",
             "each": True},
            {**action("result", "data.template", template="{count} setups: {symbols}"), "input": "volume"},
        )),
        setup=("Use it from a workflow: Watchlist symbols → Run a process (this).",),
        process=True,
    ),
    Template(
        "alert-and-log", PROC, "Alert and log",
        "Give it anything: sends an alert and writes the same text to today's inbox note.",
        flow("alert-and-log", "Alert and log", ON_DEMAND, chain(
            {**action("compose", "data.template", template="{text}"), "input": TRIGGER_INPUT},
            {**action("alert", "output.alert", title="Genesis: {count} item(s)", message="{text}"), "input": "compose"},
            {**action("log", "output.note", heading="## Alert — {time} ET", template="{text}"), "input": "compose"},
        )),
        process=True,
    ),
    Template(
        "market-open-gate", PROC, "Market open gate",
        "Passes only in the regular session between 09:35 and 15:50 ET — put it first in anything that shouldn't "
        "fire in the opening or closing minutes.",
        flow("market-open-gate", "Market open gate", ON_DEMAND, chain(
            action("session", "logic.session", sessions=["open"]),
            action("window", "logic.time-window", start="09:35", end="15:50"),
        )),
        process=True,
    ),
)


def by_id(template_id: str) -> Template | None:
    return next((t for t in TEMPLATES if t.id == template_id), None)
