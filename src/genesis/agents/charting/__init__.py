# Spec: Genesis Markdown/20-Agents/Charting/Charting Family.md
"""The Charting Family: five agents around one shared object.

Four of them are the note's own -- Chart Markup produces a [[Markup Spec]],
Pattern Recognition annotates it, Multi Timeframe composes several, Level
Watcher subscribes to it. The fifth, Data Viz, owns everything that is a chart
but not a *price* chart: ranked bars, macro series, comparisons, correlation.

The shared object is the design. Everything here either produces a spec or
consumes one, so the family composes without any agent calling another -- which
is Agent Contract rule 1, and it holds here structurally rather than by
discipline: no module in this package imports another agent.

Reflex or judgement, per Biological Design:

* ``chart-markup`` -- judgement. Selects and explains; never computes a price.
* ``pattern-recognition`` -- judgement, cross-checked by a reflex. The rules
  engine is the skeptic, and it wins ties.
* ``multi-timeframe`` -- judgement over several deterministic reads.
* ``level-watcher`` -- **reflex**. ``tier: none``, no model in the path, must
  run when every backend is down. Giving it a model would be the bug.
* ``data-viz`` -- judgement about *form*; the numbers come from tools.
"""

from genesis.agents.charting.chart_markup import ChartMarkupAgent
from genesis.agents.charting.data_viz import DataVizAgent
from genesis.agents.charting.level_watcher import LevelWatcherAgent
from genesis.agents.charting.multi_timeframe import MultiTimeframeAgent
from genesis.agents.charting.pattern_recognition import PatternRecognitionAgent

__all__ = [
    "ChartMarkupAgent",
    "DataVizAgent",
    "LevelWatcherAgent",
    "MultiTimeframeAgent",
    "PatternRecognitionAgent",
]
