# Spec: Genesis Markdown/20-Agents/Research/Research Family.md
"""The Research Family — the agents that build the system's picture of the world.

None of them can spend money. They produce beliefs, not orders.
"""

from genesis.agents.research.idea_synthesizer import IdeaSynthesizerAgent
from genesis.agents.research.market_analyst import MarketAnalystAgent
from genesis.agents.research.topic_researcher import TopicResearcherAgent

__all__ = ["IdeaSynthesizerAgent", "MarketAnalystAgent", "TopicResearcherAgent"]
