# Spec: Genesis Markdown/10-Architecture/Voice Stack.md
"""A hundred utterances for the intent eval.

Written as a trader's day rather than as test strings: the ambient half is the
kind of thing actually said in a room with a microphone in it — half-sentences,
opinions, a phone call, someone else's meeting — because that is what the
"zero actions from ten minutes of ambient conversation" criterion is really
asking about.

Four groups, each with the property being measured:

``DIRECTED``    wake word in every sentence position, per Voice Stack's
                *"wake anywhere"* requirement. Must be actionable.
``AMBIENT``     no wake word. Must never be actionable. Deliberately seeded
                with the words that would fool a keyword matcher — *stop*,
                *halt*, *cancel*, *flatten* — used in ordinary sentences.
``FOLLOW_UP``   short continuations with no wake word, inside the window.
``STOP``        the reflex phrases. Must fire, every time, before anything else.
``HEAVY_WITHOUT_WAKE``
                the deliberate asymmetry: "stop" cuts speech bare, but "halt"
                and "flatten" require the wake word, because both are ordinary
                words in market talk and a kill switch that fires on overheard
                conversation is worse than one that needs repeating.
"""

from __future__ import annotations

# -- addressed, wake word leading ---------------------------------------------

DIRECTED_LEADING = [
    "Genesis, what time does the market open",
    "Genesis, what's my exposure right now",
    "Genesis, how did semis close yesterday",
    "Genesis, screen the semiconductor sector for longs",
    "Genesis, show me NVDA on the daily",
    "Genesis, what's the drawdown on the book this month",
    "Genesis, mark up support and resistance on gold",
    "Genesis, is the market open",
    "Genesis, what's my P and L today",
    "Genesis, backtest that idea over five years",
    "Genesis, what did the screener find this morning",
    "Genesis, give me the pre-market brief",
    "Genesis, how many positions am I carrying",
    "Genesis, what's the daily loss limit set to",
    "Genesis, run the energy scan",
]

# -- addressed, wake word mid-sentence ----------------------------------------

DIRECTED_MEDIAL = [
    "okay Genesis what's the setup on AMD",
    "so Genesis how are we looking on risk",
    "right Genesis pull up the equity curve",
    "hey Genesis what's the ATR on NQ",
    "alright Genesis screen financials for me",
    "and Genesis what did news say about AVGO",
    "hold on Genesis show me the fleet status",
    "now Genesis what's my correlated exposure",
    "quickly Genesis what's the close today",
    "actually Genesis run that scan again",
]

# -- addressed, wake word trailing -- the case Voice Stack calls out ----------

DIRECTED_TRAILING = [
    "give me the semis setup, Genesis",
    "what's my open risk, Genesis",
    "pull up the chart on SPY, Genesis",
    "how did that trade work out, Genesis",
    "run the screener, Genesis",
    "what's the regime read this week, Genesis",
    "show me the journal for Tuesday, Genesis",
    "what's the position sizing on that, Genesis",
    "check the calendar for tomorrow, Genesis",
    "how much heat am I carrying, Genesis",
]

DIRECTED = DIRECTED_LEADING + DIRECTED_MEDIAL + DIRECTED_TRAILING

# -- the room talking ---------------------------------------------------------

AMBIENT_CONVERSATION = [
    "I think semiconductors are extended here",
    "did you see what AVGO did after the print",
    "the whole complex has been bid since Tuesday",
    "I'm not sure I trust this breakout",
    "we should have taken profits on Friday",
    "my read is that rates are the driver here",
    "he was saying the same thing last week",
    "let me get back to you after lunch",
    "the coffee machine is broken again",
    "I'll send you the deck this afternoon",
    "she thinks the setup is cleaner on the weekly",
    "no I meant the other account",
    "can you hear me okay on this line",
    "we're doing dinner at seven",
    "the kids have a thing on Thursday",
    "it's been a rough month for momentum names",
    "I sized that one too big honestly",
    "the desk was leaning short into the number",
    "yeah exactly, that's what I keep saying",
    "let's pick this up on Monday",
]

#: The ones that would fool a keyword matcher. Every sentence here contains a
#: reflex word used in ordinary speech, and every one must stay ambient. The
#: cost of getting these wrong is asymmetric and immediate: a false halt is a
#: system that stops trading because you mentioned stopping.
AMBIENT_WITH_REFLEX_WORDS = [
    "what's the stop on that trade",
    "where would you put your stop",
    "I moved my stop up to breakeven",
    "we should stop doing these Monday calls",
    "the bus stop is right outside",
    "they halted the stock at the open",
    "trading was halted for volatility",
    "cancel my three o'clock please",
    "I had to cancel the order at the restaurant",
    "he wants to flatten the org chart",
    "the curve flattened out after the print",
    "just kill the noise on that channel",
    "my phone died, hold on",
    "she stopped by the desk earlier",
    "the halt rules changed last year",
]

AMBIENT = AMBIENT_CONVERSATION + AMBIENT_WITH_REFLEX_WORDS

# -- short continuations inside the follow-up window --------------------------

FOLLOW_UP = [
    "and what about SPY",
    "what's the stop",
    "give me the full version",
    "how about energy",
    "why that level",
    "and the close",
    "what's the size",
    "say that again",
    "on the weekly",
    "how confident",
]

# -- the reflex phrases -------------------------------------------------------

STOP = [
    # Bare — these cut speech with no wake word, because you will say them
    # while it is talking over you.
    "stop",
    "stop it",
    "stop stop stop",
    "cancel that",
    "shut up",
    "quiet",
    # Addressed — the heavy reflexes, which require the wake word.
    "Genesis stop",
    "Genesis, cancel that",
    "Genesis halt",
    "Genesis, halt everything",
    "flatten everything, Genesis",
    "Genesis, flatten the book",
    "Genesis, kill switch",
    "Genesis, emergency stop",
    "Genesis, shut it down",
]

#: Must **not** fire. The same heavy phrases with no wake word: overheard
#: market talk, not an instruction. This asymmetry is the reason the kill
#: switch can live on a bare keyword match at all.
HEAVY_WITHOUT_WAKE = [
    "halt",
    "the stock is in a halt",
    "flatten everything",
    "kill switch",
    "emergency stop procedures",
    "shut it down for the night",
]

TOTAL = (
    len(DIRECTED) + len(AMBIENT) + len(FOLLOW_UP) + len(STOP) + len(HEAVY_WITHOUT_WAKE)
)
