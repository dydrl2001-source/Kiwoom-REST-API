# Paper Trading Lab

Paper Lab is a prospective rule-validation layer for Market Radar. It is not an order system and it does not call OpenAI.

## Scope

- One normalized unit per experiment. No cash allocation, quantity sizing or portfolio weighting.
- No brokerage order endpoint, account balance, account number or credential use.
- No commissions, tax, slippage, queue priority or fill probability.
- No historical backfill. A paper trade can begin only after this service is running and a fresh SOR quote is observed.

## Paper entry v1

A paper entry requires all of the following:

1. Active Radar candidate episode.
2. Current attention score >= 70.
3. During the previous 120 seconds there are at least 3 candidate observations and the minimum score is also >= 70.
4. Candidate type is not 조건 미완성.
5. SOR exchange timestamp is fresh within 120 seconds.
6. Latest chart state is not TREND_DAMAGE or BREAKOUT_FAIL.
7. No current TOP_WARNING with composite score >= 70.
8. No already-open paper experiment for that stock/episode.
9. At most 5 concurrent experiments.

These are experiment defaults, not recommended real-market thresholds.

## Paper exit v1

An open paper experiment is closed when one of these conditions is observed:

- Radar candidate disappears or becomes stale for 90 seconds.
- Attention score falls below 55.
- Latest chart state becomes TREND_DAMAGE or BREAKOUT_FAIL.
- Composite TOP_WARNING reaches 70 or higher.
- 30 minutes have elapsed since paper entry.

Exit uses an observed SOR reference price when available. If no recent observed price is available, the record is CLOSED_NO_PRICE and is excluded from return summaries.

## Metrics

The Home Paper Lab displays open experiments, observed return, MFE/MAE, entry reasons, exit reasons, and 30-day summary statistics. These are observed price paths, not realized returns.

## Audit

radar_paper_events records PAPER_ENTRY and PAPER_EXIT events. The baseline rule version is paper-v1-observation.
## Automatic feedback

`paper_feedback_engine.py` analyzes only completed prospective Paper Lab observations.
It does not change environment variables or live entry/exit thresholds.

Feedback is gated by sample size:

- type-level interpretation: at least 20 completed observations per candidate type;
- rule-level calibration: at least 30 completed observations overall;
- smaller samples remain `표본 축적`.

The feedback panel reports overall median observed return, positive-observation ratio, median MFE/MAE, giveback rate, immediate-failure rate, candidate-type summaries, entry-score bands, and exit-reason counts.

Possible rule labels are `표본 축적`, `현재값 유지`, and `수정 검토`. A `수정 검토` result is only an experiment candidate. Any new threshold must be introduced as a new rule version and compared prospectively rather than overwriting the existing baseline.
