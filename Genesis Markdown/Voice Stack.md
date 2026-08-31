ased on your Genesis Agent vault — the 30-agent fleet, the local wake gate, confirm approval mode, verbosity levels, and the LLM-free halt path — here's the vocabulary.

Wake words & phrases

Primary wake word: Genesis (on-device, must fire before audio leaves the machine, detectable anywhere in a sentence).

Natural wake phrases (wake word anywhere in the utterance):
1. "Genesis."
2. "Hey Genesis."
3. "Genesis, you there?"
4. "Genesis, wake up."
5. "Morning, Genesis."
6. "Okay Genesis, let's go."
7. "Genesis, I'm back."
8. "Talk to me, Genesis."
9. "Give me the semis setup, Genesis." (trailing wake word — must work per Voice Stack)
10. "Genesis, what've you got?"

Follow-up window (no wake word needed for ~4 s after a reply): "and what about SPY?", "give me the full version", "what's the stop?", "confirm that", "never mind".

Hard-coded, pre-intent phrases (recognized before any LLM):
- "Genesis, halt" → Kill Switch (cancel-all, mode → halt)
- "Genesis, stop" / "stop" → cuts TTS mid-word, never swallowed as echo
- "Genesis, flatten everything" → Kill Switch with flatten
- "Genesis, pause" → suspend agent cadence
- "Genesis, mute" → stop unprompted speech

---

100 phrases, commands & questions

Morning brief / regime (Digest + Market Analyst)

1. "Give me the morning brief."
2. "What's the regime today?"
3. "How are futures looking pre-market?"
4. "What's the read on indices and breadth?"
5. "Where's the VIX and what's it telling you?"
6. "Which sectors are leading and lagging right now?"
7. "What's the rates picture doing to equities?"
8. "Is this a risk-on or risk-off tape?"
9. "Anything change overnight I should know about?"
10. "Summarize yesterday's session and the overnight."
11. "What's the dollar doing and does it matter today?"
12. "Are correlations behaving or is something broken?"

News & catalysts (News And Catalyst + Sentiment)

13. "What's on the economic calendar today?"
14. "When is CPI and what's the consensus?"
15. "Who reports earnings after the close?"
16. "Any filings or 8-Ks on my watchlist names?"
17. "What's the catalyst on NVDA this week?"
18. "Why is TSLA down four percent?"
19. "What's the sentiment picture on semis?"
20. "Show me put/call and funding — any divergence?"
21. "Is options flow confirming or fading this move?"
22. "Flag anything with headline risk into the close."
23. "Any Fed speakers today?"
24. "What moved the most on no news?"

Screening & idea generation (Screener + Idea Synthesizer)

25. "Run my saved scans."
26. "Run the breakout scan on the whole universe."
27. "What's setting up long today?"
28. "Give me the top five ranked ideas."
29. "What's your highest-confidence idea right now?"
30. "Any short setups worth looking at?"
31. "Show me pullbacks to the 20-day in leading sectors."
32. "What's near a 52-week high with volume?"
33. "Screen for tight consolidations under resistance."
34. "Anything in energy worth a look?"
35. "Give me the full version on the top idea."
36. "Why is NVDA ranked above AMD?"
37. "What did the screener drop from yesterday's list?"
38. "Rank these by risk-adjusted expectancy."

Charting & levels (Chart Markup + Multi Timeframe + Pattern Recognition + Level Watcher)

39. "Mark up the NVDA daily."
40. "What are the key levels on SPY?"
41. "Where's support and resistance on QQQ?"
42. "Run a multi-timeframe on AAPL."
43. "What's the timeframe alignment score on MSFT?"
44. "What pattern is this in META?"
45. "Is the AMZN breakout structure clean?"
46. "Put a chart of the semis index on the dashboard."
47. "Where's invalidation on the NVDA long?"
48. "Watch 121 on NVDA and tell me when it touches."
49. "Alert me if SPY loses 545."
50. "What levels are live on my active ideas?"
51. "Draw the range on TSLA and give me both edges."

Strategy & backtesting (Strategy Author + Backtest Runner + Optimizer + Risk Metrics)

52. "Turn this into a testable strategy: buy pullbacks to the rising 20-day, stop below the prior swing."
53. "Backtest that on five years."
54. "Show me the equity curve."
55. "What's the Sharpe and max drawdown on that?"
56. "How many trades and what's the win rate?"
57. "Run a walk-forward optimization on the lookback parameter."
58. "Is this overfit?"
59. "Give me Sortino and Calmar on this curve."
60. "Compare this strategy long-only versus long-short."
61. "Export the PineScript."
62. "What's the worst losing streak this system had?"
63. "How does it perform in high-vol regimes only?"

Sizing & risk (Portfolio And Allocation + Pre-Trade Risk Engine + Prop Firm Guard)

64. "How much size on NVDA at a 118.40 stop?"
65. "What's my risk budget left for today?"
66. "What's my current heat across open positions?"
67. "If I take this trade, what's my total portfolio risk?"
68. "Size this to 0.3 percent of equity."
69. "Are we near any hard risk limit?"
70. "What's my correlation exposure to semis right now?"
71. "Kelly-cap the sizing on these three ideas."
72. "Would this trade breach a prop-firm rule?"
73. "How close am I to the daily loss limit?"

Execution (Order Manager + Risk Engine + Accountant)

74. "Propose a long on NVDA, 120 shares, stop 118.40."
75. "Confirm NVDA one twenty."
76. "Place a bracket on AAPL with a two-R target."
77. "Move my NVDA stop to breakeven."
78. "Trail the MSFT stop by one ATR."
79. "Take partials on half the TSLA position."
80. "Cancel the AMD order."
81. "Cancel all working orders."
82. "Flatten the NVDA position."
83. "What did I get filled at?"
84. "Re-propose that trade with a fresh price."

Positions & P&L (Position And PnL Accountant + Execution Quality)

85. "What are my open positions?"
86. "What's my P&L today?"
87. "What's my unrealized on NVDA?"
88. "What's my total exposure, long and short?"
89. "How's my slippage versus arrival today?"
90. "Did reconciliation pass this morning?"
91. "What's my biggest winner and biggest loser open?"

Journal & review (Trade Journal + Performance Analyst + Insight Miner + Drift)

92. "Journal that trade with the thesis: semis breakout, sector leading."
93. "How's my edge by setup this month?"
94. "Which session do I trade best?"
95. "What's my expectancy on breakout trades versus pullbacks?"
96. "Any behavioral patterns I should hear about?"
97. "Is live tracking the backtest or drifting?"
98. "Give me the weekly performance review."

System, health & control (Watchdog + Kill Switch + config)

99. "Is everything healthy? Any agent down?"
100. "Switch to terse for the rest of the session."