# Genesis Agent — Voice Tasks & Multi-Asset Command Catalog

## Purpose

This document expands the Genesis voice stack into an operational command vocabulary for the full multi-agent fleet. The existing Voice Stack establishes Genesis as the voice interface, local wake gate, follow-up window, hard-coded safety controls, and conversational entry point for research, charting, strategy, risk, execution, journaling, and system health. fileciteturn1file0L1-L25

This document adds structured tasks for the five primary agent groups:

- **Charting**
- **Research**
- **Execution**
- **Journal**
- **Strategy**

The commands are designed to support multiple asset classes rather than treating equities as the only market. Genesis should understand the requested asset class, instrument, timeframe, session, strategy, and task intent before routing work to the appropriate agents.

The voice layer should remain an interface to the agent system, not a replacement for deterministic controls. Safety-critical execution and risk decisions remain outside the LLM path.

---

# 1. Asset-Class Vocabulary

Genesis should recognize explicit and implicit references to the following asset classes.

### Equities

Examples:
- SPY
- QQQ
- NVDA
- AAPL
- TSLA
- AMD
- MSFT

Example questions:

- "What's the setup on NVDA?"
- "Compare NVDA and AMD."
- "Which large-cap tech names are strongest today?"

### Equity Index Futures

Examples:
- ES / E-mini S&P 500
- NQ / E-mini Nasdaq
- YM / Dow
- RTY / Russell 2000
- MES / Micro S&P
- MNQ / Micro Nasdaq

Example questions:

- "How are ES and NQ trading relative to yesterday's close?"
- "Which index future has the cleanest structure?"
- "Is NQ confirming the move in QQQ?"

### Forex

Examples:
- EUR/USD
- GBP/USD
- USD/JPY
- AUD/USD
- USD/CAD
- DXY

Example questions:

- "What's the dollar doing against the yen?"
- "Show me the EUR/USD daily structure."
- "Is DXY strength confirming the move in equities?"

### Commodities

Examples:
- Gold / GC
- Silver / SI
- Crude Oil / CL
- Natural Gas / NG
- Copper / HG

Example questions:

- "What's the setup in gold?"
- "Is crude breaking out or failing?"
- "Compare gold and silver momentum."

### Fixed Income / Rates

Examples:
- US 2-Year
- US 10-Year
- US 30-Year
- TLT
- Treasury futures such as ZN, ZB

Example questions:

- "What's the 10-year yield doing?"
- "Is the rates move supportive of tech?"
- "Compare TLT against the 10-year yield."

### Crypto

Examples:
- BTC/USD
- ETH/USD
- SOL/USD
- BTC futures
- ETH futures

Example questions:

- "What's the structure on Bitcoin?"
- "Is ETH outperforming BTC?"
- "Does crypto risk appetite agree with equities?"

### Options

Genesis should recognize options as a derivative layer attached to an underlying instrument.

Examples:

- SPY calls
- QQQ puts
- NVDA vertical spreads
- AAPL covered calls
- index options

Example questions:

- "What is the options flow saying on NVDA?"
- "Compare implied volatility with realized volatility."
- "Where is the largest open interest around SPY?"

---

# 2. Charting Agent Tasks

The Charting group is responsible for technical structure, levels, patterns, timeframe relationships, and chart state.

### Basic chart tasks

1. "Mark up the daily chart on NVDA."
2. "Show me the weekly structure on SPY."
3. "Give me support and resistance on QQQ."
4. "Draw the current range on ES."
5. "Mark the overnight high and low on NQ."
6. "Show me today's opening range on TSLA."
7. "Where are the major levels on gold?"
8. "Mark the weekly levels on Bitcoin."
9. "Show me the 10-year yield structure."
10. "Put EUR/USD on the dashboard."

### Multi-timeframe tasks

11. "Run a multi-timeframe analysis on NVDA."
12. "Is the weekly trend aligned with the daily?"
13. "What does the four-hour chart say versus the daily?"
14. "Give me the timeframe alignment score on NQ."
15. "Is Bitcoin bullish across the major timeframes?"
16. "Where does the intraday structure disagree with the weekly?"
17. "Which timeframe is currently controlling the setup?"

### Pattern recognition

18. "What pattern is forming on AMD?"
19. "Is this a valid breakout structure?"
20. "Is ES forming a failed breakout?"
21. "Does gold have a clean range expansion?"
22. "Is BTC forming a higher-low continuation?"
23. "Is EUR/USD breaking down or just testing support?"
24. "Find compression patterns across my watchlist."
25. "Find failed breakouts across the index futures."

### Levels and alerts

26. "Watch 120 on NVDA."
27. "Alert me if SPY loses 545."
28. "Tell me when ES retests yesterday's high."
29. "Watch the prior week's high on gold."
30. "Alert me if BTC breaks the weekly range."
31. "What levels are live on my active ideas?"
32. "Which active setups are approaching invalidation?"

### Cross-asset chart questions

33. "Compare SPY, QQQ, and NQ structure."
34. "Compare gold and the dollar."
35. "Compare BTC against the Nasdaq."
36. "Does crude confirm the move in energy equities?"
37. "Is TLT confirming the rates move?"
38. "Which asset has the cleanest breakout structure right now?"

---

# 3. Research Agent Tasks

The Research group gathers information, catalysts, macro context, market structure, fundamentals, sentiment, and cross-asset relationships.

### Market and macro research

39. "Give me the macro brief."
40. "What's driving markets today?"
41. "What's changed overnight?"
42. "What are the major macro catalysts today?"
43. "What economic releases matter today?"
44. "What is the market pricing for the next Fed decision?"
45. "What is the rates market signaling?"
46. "Is the dollar creating a headwind for risk assets?"
47. "Are correlations behaving normally?"

### Company research

48. "Give me the latest catalyst on NVDA."
49. "What's changed fundamentally for AMD?"
50. "Summarize the latest earnings report for AAPL."
51. "Any new filings on my watchlist?"
52. "What are analysts focused on for TSLA?"
53. "What's the bull case and bear case for MSFT?"
54. "Find material news affecting semiconductors."

### Cross-asset research

55. "Is the dollar strength consistent with the move in yields?"
56. "Are rates confirming or contradicting the equity rally?"
57. "Is gold behaving like a risk-off asset today?"
58. "Is Bitcoin trading more like a risk asset or a macro hedge?"
59. "Does crude confirm strength in energy equities?"
60. "Are small caps confirming large-cap strength?"
61. "Which asset classes are leading risk appetite?"
62. "Find divergences between equities, rates, commodities, FX, and crypto."

### Comparative research

63. "Compare NVDA, AMD, and AVGO."
64. "Compare SPY and QQQ leadership."
65. "Compare gold, silver, and copper."
66. "Compare BTC and ETH momentum."
67. "Compare energy equities with crude oil."
68. "Compare the dollar against major risk assets."
69. "Rank these markets by catalyst strength."

### Research questions for trade candidates

70. "What could invalidate the thesis on NVDA?"
71. "What is the strongest argument against this trade?"
72. "What catalyst could move this market today?"
73. "What information would change the setup?"
74. "Is there headline risk I should know about?"
75. "What am I missing from this thesis?"
76. "Find evidence that contradicts the current setup."

---

# 4. Strategy Agent Tasks

The Strategy group converts ideas into explicit, testable rules and evaluates their historical behavior.

### Strategy creation

77. "Turn this setup into a testable strategy."
78. "Build a breakout strategy from this chart."
79. "Create a pullback strategy using the rising 20-day."
80. "Define the entry, invalidation, target, and exit rules."
81. "Turn this discretionary setup into objective rules."
82. "Create separate long and short rules."
83. "Create a strategy for trend-following gold."
84. "Create a mean-reversion strategy for index futures."
85. "Create a momentum strategy for crypto."

### Backtesting

86. "Backtest this strategy over five years."
87. "Backtest it separately by asset class."
88. "Compare the strategy on SPY, QQQ, and IWM."
89. "Test it on ES and NQ separately."
90. "Test the strategy during high-volatility periods."
91. "Test it during low-volatility periods."
92. "Show me the equity curve."
93. "Show me the drawdown curve."
94. "How many trades did it generate?"
95. "What was the win rate and expectancy?"

### Robustness

96. "Is this strategy overfit?"
97. "Run a walk-forward test."
98. "Test different entry thresholds."
99. "Test different stop distances."
100. "Test different holding periods."
101. "Show me sensitivity to the lookback."
102. "Does the edge survive higher transaction costs?"
103. "Does the edge survive slippage?"
104. "Compare in-sample versus out-of-sample performance."

### Cross-asset strategy questions

105. "Does this strategy work better on equities or futures?"
106. "Does the setup work on commodities?"
107. "Does the same edge exist in FX?"
108. "Does the strategy transfer to crypto?"
109. "Which asset class has the highest risk-adjusted expectancy?"
110. "Where does this strategy fail?"
111. "Which market regime produces the best results?"

### Strategy comparison

112. "Compare breakout versus pullback expectancy."
113. "Compare trend following versus mean reversion."
114. "Compare long-only versus long-short."
115. "Compare the strategy with and without a volatility filter."
116. "Compare fixed sizing against volatility-adjusted sizing."
117. "Which version has the best drawdown-adjusted return?"

---

# 5. Execution Agent Tasks

The Execution group handles proposals, approved orders, order lifecycle, fills, position state, and execution quality. Voice commands that can cause market action must remain subject to the system's deterministic risk and approval architecture.

### Proposal tasks

118. "Propose a long on NVDA at this level."
119. "Build a trade proposal for ES."
120. "Propose a short on EUR/USD."
121. "Create a bracket proposal for gold."
122. "What would the order look like if I risk 0.25 percent?"
123. "Show me the proposed entry, stop, target, and size."

### Confirmation

124. "Confirm NVDA one twenty."
125. "Confirm the ES trade."
126. "Approve the proposed order."
127. "Reject that proposal."
128. "Read the order back to me before confirmation."

### Position and order management

129. "What working orders do I have?"
130. "Cancel the AMD order."
131. "Cancel all working orders."
132. "Move my NVDA stop to breakeven."
133. "Trail the MSFT stop by one ATR."
134. "Take partials on half the TSLA position."
135. "Flatten the NVDA position."
136. "What did I get filled at?"
137. "What is my current position in ES?"
138. "Did the order fill completely or partially?"

### Execution quality

139. "How was my execution quality today?"
140. "What was my average slippage?"
141. "Compare fills against arrival price."
142. "Which broker executions were weakest?"
143. "Did any orders experience abnormal latency?"
144. "Show me rejected, cancelled, and partially filled orders."

### Cross-asset execution questions

145. "What's the liquidity like in this market?"
146. "Compare expected slippage between SPY and NQ."
147. "Is this instrument liquid enough for my intended size?"
148. "What changes if I execute during the regular session versus overnight?"
149. "How does the spread compare with my normal execution conditions?"

---

# 6. Journal Agent Tasks

The Journal group records trades, decisions, context, outcomes, behavioral patterns, and differences between expected and realized performance.

### Trade journaling

150. "Journal this trade."
151. "Journal the thesis before I enter."
152. "Record why I took this trade."
153. "Record the invalidation level."
154. "Record the market regime."
155. "Record the catalyst."
156. "Attach this chart to the journal entry."
157. "Mark this as a breakout setup."

### Post-trade review

158. "Review my last trade."
159. "Did I follow the plan?"
160. "Was the entry according to my setup?"
161. "Did I move the stop emotionally?"
162. "Was the exit consistent with the strategy?"
163. "What would I have done differently?"
164. "Compare what I expected with what actually happened."

### Performance analysis

165. "How is my edge by setup this month?"
166. "What's my expectancy on breakout trades?"
167. "What's my expectancy on pullbacks?"
168. "Which asset class am I trading best?"
169. "Which market am I consistently losing money in?"
170. "Which session do I trade best?"
171. "What's my average winner versus average loser?"
172. "What's my longest losing streak?"
173. "Show me my performance by day of week."

### Behavioral questions

174. "Am I cutting winners short?"
175. "Am I letting losers run?"
176. "Do I perform worse after a loss?"
177. "Do I overtrade during certain sessions?"
178. "Am I taking trades outside my strategy?"
179. "Is my live behavior drifting from my tested strategy?"
180. "What behavioral pattern has changed recently?"

---

# 7. Cross-Agent Tasks

These commands intentionally require multiple agent groups to collaborate.

### Charting + Research

181. "Chart NVDA and tell me whether the news supports the technical setup."
182. "Find the catalyst and map the technical levels around it."
183. "Compare the macro backdrop with the current ES structure."
184. "Is the BTC breakout supported by broader risk appetite?"

### Research + Strategy

185. "Find the strongest macro themes and turn them into testable trade ideas."
186. "Does the current market regime favor my strategy?"
187. "Find historical examples of this catalyst and how markets reacted."
188. "Which strategies have performed best under today's macro conditions?"

### Charting + Strategy

189. "Turn this chart pattern into objective rules."
190. "Backtest the setup shown on the chart."
191. "Find other instruments showing the same structure."
192. "Rank these charts by historical expectancy."

### Strategy + Risk

193. "What position size is appropriate for this strategy?"
194. "How does portfolio correlation change if I take all three trades?"
195. "Compare the drawdown impact of adding this strategy."
196. "Which strategy provides the best return for the current risk budget?"

### Research + Charting + Strategy

197. "Find the strongest setup across all asset classes, explain the catalyst, show the chart, and tell me whether the setup has historical edge."
198. "Scan equities, futures, FX, commodities, and crypto for aligned setups."
199. "Find cross-asset divergences that could become trade candidates."
200. "Give me the five best opportunities, with technical structure, catalyst, invalidation, and historical expectancy."

### Full Genesis analysis

201. "Give me the full analysis on this trade."
202. "Run the entire research-to-execution workflow, but stop before proposing an order."
203. "Challenge this thesis from every angle."
204. "What would have to be true for this trade to work?"
205. "What would prove this thesis wrong?"
206. "Show me the strongest evidence for and against the trade."
207. "Give me the complete trade dossier."

---

# 8. Multi-Asset Market Questions

These are intentionally broader questions that require Genesis to reason across asset classes.

### Risk-on / risk-off

208. "Is the whole market risk-on or risk-off?"
209. "Which asset class is leading the risk move?"
210. "Are equities, credit, commodities, and crypto confirming each other?"
211. "Where is the biggest cross-asset divergence?"
212. "Is the dollar contradicting the equity move?"

### Rates and equities

213. "Are Treasury yields confirming the equity rally?"
214. "What does the yield curve imply for today's trade?"
215. "Which sectors are most sensitive to the rates move?"
216. "Is QQQ vulnerable if yields continue higher?"

### Dollar and commodities

217. "Is dollar strength pressuring gold?"
218. "Is crude moving because of the dollar or fundamentals?"
219. "What commodity-dollar relationships are breaking down?"
220. "Which commodities have the strongest relative momentum?"

### Crypto and traditional markets

221. "Is Bitcoin confirming the Nasdaq?"
222. "Is crypto leading or lagging risk appetite?"
223. "Does ETH have independent strength?"
224. "Are crypto and equities becoming more or less correlated?"

### Relative strength

225. "Rank all asset classes by relative strength."
226. "Find the strongest asset against the weakest."
227. "Which markets are showing unusual relative strength?"
228. "Find the biggest divergences today."

---

# 9. Agent Handoff Questions

Genesis should be able to expose why a task moved between agent groups.

Examples:

229. "Why did you send this to the research agent?"
230. "Which agent created this setup?"
231. "What information did the charting agent provide?"
232. "What did the strategy agent conclude?"
233. "What did the journal agent learn from previous trades?"
234. "Show me the chain of agents involved."
235. "Which agent rejected this idea?"
236. "What evidence caused the strategy score to change?"
237. "Show me every agent that touched this task."

---

# 10. Task-Oriented Follow-Ups

The existing Voice Stack supports a short follow-up window without repeating the wake word. fileciteturn1file0L17-L19 Extend that concept to active tasks.

After Genesis says:

> "I found three candidates."

The user can say:

- "Show me the first one."
- "Why not the second?"
- "Chart it."
- "Research it."
- "Backtest it."
- "What's the invalidation?"
- "Compare it with NVDA."
- "What happens if I use half the risk?"
- "Journal this."
- "Build a proposal."
- "Don't execute it."
- "Send it to strategy."
- "What does research disagree with?"
- "Show me the evidence."

The active task context should persist across these follow-ups until the task completes, is explicitly cancelled, or the conversational context expires.

---

# 11. Compound Task Templates

Genesis should recognize compound commands as multi-agent tasks.

### Discovery

> "Find the best long setup across equities, futures, commodities, FX, and crypto."

Suggested routing:

`Research → Charting → Strategy → Risk`

### Thesis validation

> "I like this NVDA breakout. Research the catalyst, validate the chart, test the setup, and tell me what could invalidate it."

Suggested routing:

`Research + Charting → Strategy → Risk`

### Trade preparation

> "Prepare this ES trade with the technical thesis, historical expectancy, position size, and proposed order, but don't send it."

Suggested routing:

`Charting → Research → Strategy → Risk → Execution Proposal`

### Post-trade

> "Review my BTC trade from yesterday and compare what happened with the original thesis."

Suggested routing:

`Journal → Charting → Research → Strategy`

### Portfolio review

> "Review my portfolio across equities, futures, and crypto and tell me where my largest concentration and correlation risks are."

Suggested routing:

`Execution/Accountant → Risk → Research → Journal`

---

# 12. Voice Routing Principle

Voice commands should be interpreted into a structured task before execution.

Conceptually:

```text
VOICE
  ↓
WAKE GATE
  ↓
INTENT
  ↓
TASK
  ↓
ASSET / INSTRUMENT
  ↓
AGENT GROUP
  ↓
AGENT(S)
  ↓
RESULT
  ↓
VERIFICATION
  ↓
VOICE RESPONSE
```

For compound tasks:

```text
VOICE
  ↓
TASK PLANNER
  ↓
┌─────────────┬─────────────┬─────────────┐
↓             ↓             ↓
RESEARCH      CHARTING      STRATEGY
↓             ↓             ↓
└─────────────┴─────────────┘
              ↓
            RISK
              ↓
        EXECUTION PROPOSAL
              ↓
          USER CONFIRM
              ↓
       DETERMINISTIC GATE
              ↓
        APPROVED ACTION
```

The planner should never bypass the deterministic safety architecture for the sake of conversational convenience.

---

# 13. Questions Genesis Should Ask Back

When a task is ambiguous, Genesis should ask the minimum question necessary to safely route it.

Examples:

### Missing instrument

User:
> "Chart the breakout."

Genesis:
> "Which instrument?"

### Missing timeframe

User:
> "Where's support?"

Genesis:
> "Which timeframe: intraday, daily, or weekly?"

### Missing strategy horizon

User:
> "Backtest this."

Genesis:
> "What lookback period should I use?"

### Missing execution details

User:
> "Buy NVDA."

Genesis should not infer an executable order. It should request the necessary trade parameters and produce a proposal subject to the risk architecture.

### Multiple asset classes

User:
> "What's strongest?"

Genesis:
> "Do you want equities only, or should I compare equities, futures, FX, commodities, and crypto?"

---

# 14. Core Design Goal

The voice system should make Genesis feel like one coherent intelligence while preserving the fact that specialized agents perform different functions.

The user should be able to speak naturally:

> "Genesis, find me the strongest setup."

And Genesis should be able to coordinate:

```text
          GENESIS
             │
      TASK / INTENT
             │
     ┌───────┼────────┐
     ↓       ↓        ↓
 RESEARCH CHARTING STRATEGY
     │       │        │
     └───────┼────────┘
             ↓
           RISK
             ↓
      USER DECISION
             ↓
         EXECUTION
             ↓
          JOURNAL
```

The objective is not to expose the complexity of the fleet in every conversation. The objective is to let the user speak in natural trading language while Genesis routes the task to the correct agents, maintains context, exposes the evidence and reasoning path when requested, and preserves the deterministic boundaries around risk and execution.

The existing Voice Stack remains the authority for wake behavior, hard-coded control phrases, conversational follow-ups, and baseline voice vocabulary; this document extends that vocabulary into a structured multi-agent task layer. fileciteturn1file0L21-L30
