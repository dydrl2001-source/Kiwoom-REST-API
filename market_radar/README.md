# Market Radar

## Goal
Combine Kiwoom market microstructure, Telegram catalysts, sector flow, and chart-state analysis into one explainable intraday radar.

## Decision order
1. Market regime
2. Leading sector/theme
3. Stock attention (realtime query rank)
4. Actual money flow (trading value)
5. Catalyst/event context (Telegram)
6. Chart state (Mimosa-style structure)

## Market regime axes
- Trend: rising / range-or-mixed / falling / unknown
- Flow: leader-concentrated / rotational-distributed / broad-distributed / large-cap-concentrated / transition
- Sentiment: strong / normal / weak / unknown

The regime engine must show evidence rather than a black-box score:
- Top20 realtime-query turnover
- Top5/Top10 trading-value concentration
- Top-sector and Top3-sector trading-value share
- Number of sectors in query Top20
- Large-cap share of Top20 trading value
- Positive-stock breadth and average change rate
- Data freshness

## Stabilization
Do not flip the displayed regime on one noisy snapshot.
A candidate label must repeat 3 times before becoming the stable label.

## Self-feedback rule
Initial thresholds are provisional.
After at least 10 trading days of intraday history, replace fixed thresholds with time-of-day rolling percentiles and review misclassifications against:
- leader persistence
- sector rotation frequency
- rank turnover
- follow-through next 5/15/30 minutes

## Radar row
rank | rank acceleration | stock | change % | trading value | market cap | trading value / market cap | official sector | market theme | catalyst | catalyst status | chart state

## Source separation
Keep these concepts separate:
- official_sector: Kiwoom/market classification
- market_theme: inferred market theme
- catalyst: source-backed Telegram/news event
- chart_state: price/volume structure, not a recommendation

## Chart-state roadmap
- leader trend
- intact pullback
- M contraction
- M breakout test
- previous-high approach
- supply-zone test
- supply absorption
- new high
- breakout hold
- breakout fail
- trend damage

## No black-box recommendation
The first version should not output a single buy score.
It should expose evidence and state transitions so the user can inspect why the market/stock was classified that way.
