# Spec: Genesis Markdown/20-Agents/Journal/Journal Family.md
"""The Journal Family: six agents that make the system learn.

From your trades, from its own predictions, and from its own health. The loop:

    trade -> Trade Journal -> entry (thesis, charts, R, adherence)
                  |
                  v
        Performance Analyst -> edge by setup / session / symbol / size
                  |
                  v
            Insight Miner -> lessons -----> Idea Synthesizer
                  |                    \\--> Pre-Trade Risk Engine (informs limits)
        Backtest Vs Live Drift
                  |
              Watchdog / Digest

> The loop closes when a lesson changes a future decision. A journal that is only
> ever written is a diary; a journal that is read back into the decision process
> is an edge.

Two family-wide properties, both from the note:

**Automatic, not aspirational.** The entry is complete when the trade closes.
The human is asked once, later, and may say nothing.

**Honest, not flattering.** These agents report what happened. A weekly review
that always finds something encouraging is worthless, and the prompts forbid
softening. Encouragement is not the product; accuracy is.

Reflex or judgement, per Biological Design:

* ``trade-journal`` -- mostly reflex. Formatting and arithmetic; the model only
  transcribes.
* ``performance-analyst`` -- judgement over deterministic slices.
* ``insight-miner`` -- judgement over deterministic detectors. It never
  *discovers* a pattern; it words one.
* ``drift`` -- judgement over a z-score it did not compute.
* ``watchdog`` -- **reflex**, ``tier: none``. The component that answers "is the
  system healthy" must not depend on a language model being up.
* ``digest`` -- summarisation, with the length rule checked rather than asked.
"""

from genesis.agents.journal.digest import DigestAgent
from genesis.agents.journal.drift import DriftAgent
from genesis.agents.journal.insight_miner import InsightMinerAgent
from genesis.agents.journal.performance_analyst import PerformanceAnalystAgent
from genesis.agents.journal.trade_journal import TradeJournalAgent
from genesis.agents.journal.watchdog import WatchdogAgent

__all__ = [
    "DigestAgent",
    "DriftAgent",
    "InsightMinerAgent",
    "PerformanceAnalystAgent",
    "TradeJournalAgent",
    "WatchdogAgent",
]
