# Investment Desk v0.1 — integration plan

## Why this branch exists

This repository already contains a substantial Market Radar / Paper Lab stack.
The goal is not to rebuild it from scratch or replace working components.
This branch turns the existing system into a broader personal Investment Desk for Korean equities while preserving the current explainability-first design.

## Existing capabilities to preserve

- Kiwoom REST API foundation and MCP integration
- Market regime classification with evidence
- Sector/theme leadership and trading-value analysis
- Real-time candidate tracking and persistence
- Telegram/news/DART catalyst evidence with identity guards
- Chart-state and reversal-warning logic
- 5/15/30-minute prospective candidate outcome journal
- Mobile/PWA dashboard
- Paper Trading Lab with explicit entry/exit rules
- MFE/MAE, giveback and immediate-failure statistics
- Automatic Paper Lab feedback with sample-size gates
- No automatic live-rule mutation

## Design principles

1. Data and deterministic rules decide eligibility; LLM agents explain, challenge and synthesize.
2. Every conclusion must keep its source/evidence trail.
3. New strategy rules are versioned experiments, never silent overwrites.
4. Paper / demo validation comes before live execution.
5. Live buy orders require explicit user approval in the first production phase.
6. Risk limits, duplicate-order protection and kill switches are deterministic code.
7. The system records both taken and rejected candidates so decision quality can be audited.

## Target architecture

Data layer
- Kiwoom quotes, orderbook, trading value, investor flow
- DART disclosures and earnings/fundamental data
- Telegram/news catalysts
- Macro inputs relevant to KRX
- Portfolio and decision journal

Research desk
- Market Regime
- Sector / Flow
- Catalyst / News
- Fundamental / Earnings
- Technical / Chart
- Quant / Screener
- Bear / Counter-thesis
- Audit / Evidence

Decision layer
- Portfolio Manager
- Risk Engine
- Candidate decision record
- User approval queue

Validation lab
- Historical backtest
- Walk-forward / out-of-sample
- Fee, tax and slippage assumptions
- Prospective Paper Lab
- Strategy-version comparison

Execution layer
- Demo first
- Approved buy orders
- Deterministic exits / protective orders where supported
- Fill tracking, correction/cancel handling
- Daily reconciliation

Learning / audit
- Entry thesis vs outcome
- Rejected-candidate tracking
- MFE/MAE and regime-conditioned performance
- Agent/rule calibration reports
- No self-modification without a new version and validation gate

## v0.1 work order

### A. Current-system audit
Map services, tables, scheduled jobs, data sources and UI routes already present under `market_radar/`.

### B. Unified decision record
Create a durable record that links:
- candidate
- market regime
- sector/theme
- catalyst evidence
- chart state
- fundamental snapshot
- risk checks
- final user decision
- later outcome

### C. Research agents
Add structured outputs for:
- Fundamental/Earnings
- Bear/Counter-thesis
- Audit/Evidence

Agents must not place orders or mutate live rules.

### D. Risk and portfolio layer
Add:
- max single-name exposure
- sector exposure
- total gross exposure
- daily loss budget
- event-risk flags
- duplicate-order protection
- kill switch state

### E. Backtest lab
Add reusable strategy definitions with:
- version
- universe
- entry/exit rules
- fees/tax/slippage
- train/test windows
- walk-forward results
- MDD, win rate, expectancy, profit factor and turnover

### F. Kiwoom demo execution
Connect approved decisions to the Kiwoom demo environment only.
Production execution remains disabled until validation criteria are met.

## First milestone

The first usable milestone is not full auto-trading.

It is a single dashboard that answers:

1. What changed overnight / before the Korean open?
2. What regime is the market in?
3. Which sectors/themes have actual money flow?
4. Which stocks survived screening and why?
5. What is the bull case?
6. What is the bear case?
7. What evidence is verified vs inferred?
8. What risk budget is available?
9. What would invalidate the idea?
10. What happened to comparable prior candidates?

That milestone will become the base for paper validation and later semi-automated execution.
