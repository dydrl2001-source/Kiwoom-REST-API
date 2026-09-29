# AI Brokerage Incident & Recovery Runbook

This runbook covers the local Market Radar / AI Brokerage research stack.

Scope: Paper / Shadow / read-only data collection only.
No live broker-order recovery action exists in this branch.

## 1. Operating states

### RUN
- raw safety conditions are healthy
- no recovery latch is active
- new Shadow entries may be opened

### DEGRADED
- one or more warning conditions exist
- new Shadow entries may continue
- operator should inspect the warning before increasing research exposure

### HALT
- a hard safety trigger exists, or
- a previous HALT incident is still recovery-latched, or
- persisted Risk Control status is missing/stale while fail-safe is required

HALT blocks new Shadow entries.

Existing positions are never silently changed. Rebalance output proposes HOLD / REDUCE / EXIT_SHADOW actions for review.

## 2. Hard HALT examples

- DAILY_LOSS_LIMIT
- CRITICAL_FEED_ERROR
- CRITICAL_FEED_STALE
- PORTFOLIO_RISK_BREACH
- EXECUTION_IS_DEGRADED
- EXECUTION_REJECT_SPIKE
- PORTFOLIO_CORRELATION_SPIKE
- MANUAL_HALT
- RISK_CONTROL_STATUS_STALE
- RISK_CONTROL_STATUS_MISSING
- RECOVERY_LATCH

Warnings such as low BOOK coverage or moderately elevated execution cost normally produce DEGRADED rather than HALT.

## 3. Immediate incident response

### Step 1 — confirm effective vs raw state

Open:

AI 증권사 → Portfolio Control & Live Readiness

Check:

- Raw Kill Switch
- Effective Kill Switch
- incident ID
- recovery state
- hard trigger codes
- feed ages
- Daily Shadow P/L
- risk utilization
- round-trip IS
- execution rejection rate
- correlation state

A common recovery pattern is:

Raw RUN → Effective HALT

This means the original problem has cleared but the recovery latch is intentionally still blocking new Shadow entries.

### Step 2 — inspect current incident from CLI

From market_radar/local:

~~~bash
docker compose exec risk-control-worker \
  python /app/risk_recovery_cli.py status
~~~

Expected fields:

- state
- raw state
- incident ID
- recovery state
- healthy streak / required streak
- acknowledgement status
- halted_at / recovered_at

### Step 3 — inspect relevant service logs

~~~bash
docker compose logs --tail=200 risk-control-worker
docker compose logs --tail=200 resilience-audit-worker
docker compose logs --tail=200 kiwoom-feed
docker compose logs --tail=200 orderbook-collector
docker compose logs --tail=200 chart-feed
docker compose logs --tail=200 market-regime
docker compose logs --tail=200 shadow-execution-engine
~~~

Do not clear the incident before the root condition is understood.

## 4. Trigger-specific checks

### CRITICAL_FEED_STALE / ERROR

Check the named feed.

For Kiwoom:
- credentials / token
- KIWOOM_MODE
- network response
- most recent kiwoom_feed_status.last_success_at

For chart/regime:
- upstream Kiwoom/DB freshness
- worker logs
- latest status-table timestamps

Recovery condition:
- feed returns to a healthy non-WAITING state
- freshness remains inside configured threshold for the required healthy streak

### ORDERBOOK_STALE / BOOK_COVERAGE_LOW

Check:

~~~bash
docker compose logs --tail=200 orderbook-collector
~~~

Confirm:
- target_count > 0 when there are active AI/Paper/Shadow names
- saved_count > 0
- ka10004 responses are being persisted
- venue suffix is correct for the configured research mode

Low BOOK coverage is normally DEGRADED, not a hard HALT.

### DAILY_LOSS_LIMIT

Do not reset or edit historical Shadow P/L.

Review:
- completed Shadow trades for the KST date
- execution drag / IS
- whether losses are concentrated in one strategy/theme
- whether Rebalance proposes reductions/exits

Recovery is not achieved by deleting trades or changing the threshold during the incident.

### EXECUTION_IS_DEGRADED / REJECT_SPIKE

Review:
- BOOK_V2 coverage
- spread distribution
- partial fills / rejects
- Paper→Shadow drag
- current liquidity regime
- whether PROXY_V1 fallback is dominating

Do not lower the IS/rejection threshold merely to clear the incident.

### PORTFOLIO_RISK_BREACH / CORRELATION_SPIKE

Review:
- current Shadow open risk
- theme and strategy-family concentration
- allocation correlation matrix
- Rebalance REDUCE / EXIT_SHADOW proposals

## 5. Manual HALT

To intentionally freeze new Shadow entries:

Set in .env:

~~~text
RISK_MANUAL_HALT=1
~~~

Recreate the processes that evaluate/display the environment:

~~~bash
docker compose up -d --force-recreate \
  radar-api risk-control-worker shadow-execution-engine
~~~

To begin recovery later:

1. set RISK_MANUAL_HALT=0
2. recreate the same services
3. verify Raw state returns to RUN
4. complete recovery-latch procedure below

Manual HALT does not create a live broker action.

## 6. Recovery latch

Default policy:

~~~text
RISK_RECOVERY_HEALTHY_STREAK=3
RISK_RECOVERY_REQUIRE_ACK=1
~~~

A HALT incident does not return immediately to RUN when the raw trigger disappears.

Required recovery sequence:

1. root cause is fixed
2. Raw Kill Switch becomes RUN
3. RUN remains healthy for the configured consecutive observations
4. operator acknowledges the current incident ID
5. Risk Control worker verifies both conditions
6. Effective state changes to RUN
7. Shadow engine may open new positions again

DEGRADED observations do not count toward the healthy streak.

## 7. Acknowledge an incident

First read the current incident ID:

~~~bash
docker compose exec risk-control-worker \
  python /app/risk_recovery_cli.py status
~~~

Then acknowledge that exact incident:

~~~bash
docker compose exec risk-control-worker \
  python /app/risk_recovery_cli.py ack \
  --incident <CURRENT_INCIDENT_ID>
~~~

The CLI validates:

- current effective state is HALT
- an incident ID exists
- supplied ID matches the current incident
- acknowledgement has not already been recorded

The CLI cannot force RUN.

After acknowledgement, the latch remains HALT until the healthy-streak requirement is also met.

There is intentionally no force-run, clear-halt, or skip-checks command.

## 8. Resilience Audit

The resilience-audit-worker runs non-destructive checks periodically.

It does not:
- stop services
- corrupt data
- alter market observations
- create broker orders
- mutate Shadow positions

It does:

1. run synthetic safety scenarios through the deterministic Kill Switch
2. verify expected RUN / DEGRADED / HALT outcomes
3. verify the synthetic recovery-latch sequence
4. replay persisted Risk Control snapshots
5. detect unsafe historical HALT → RUN transitions

Dashboard:

AI 증권사 → Resilience Lab

Expected healthy result:

~~~text
Audit PASS
Chaos 12/12
Replay PASS or NO_HISTORY
~~~

Scenario count may increase as new safety cases are added.

## 9. Service restart / recovery verification

After a service crash or host restart:

~~~bash
docker compose ps
~~~

Confirm the following are running:

- postgres
- radar-api
- kiwoom-feed
- chart-feed
- market-regime
- ai-brokerage-worker
- orderbook-collector
- risk-control-worker
- resilience-audit-worker
- shadow-execution-engine
- capital-allocation-worker

Then verify:

1. Risk Control status timestamp is fresh
2. Order Book status timestamp is fresh
3. Resilience Audit is PASS
4. Raw Kill Switch is RUN
5. Effective Kill Switch is RUN, or a known recovery latch explains HALT
6. Live Readiness remains informational only
7. live_enabled=false

## 10. What never counts as recovery

Do not recover by:

- deleting incident rows
- deleting losing Shadow trades
- lowering thresholds during an active incident
- disabling RISK_CONTROL_REQUIRED
- extending stale-data thresholds only to clear HALT
- marking missing feeds as healthy
- setting correlation to zero when data is missing
- bypassing the acknowledgement requirement
- adding a live-order call to the recovery code

If a threshold genuinely needs revision, change it as a separate reviewed configuration/version after the incident is closed.

## 11. Incident close criteria

An incident is considered closed when:

- the raw trigger is gone
- healthy streak requirement is met
- required acknowledgement is recorded
- effective state has returned to RUN
- ai_incident_events.closed_at is populated
- Resilience Audit does not flag an unsafe recovery transition

The incident history remains in the database for later review.

## 12. Post-incident review

For every meaningful HALT, record:

- incident ID
- first hard trigger
- affected services
- detection time
- root cause
- duration
- whether new Shadow entries were correctly blocked
- whether any Rebalance action was proposed
- healthy-streak duration
- acknowledgement time
- recovery time
- whether chaos/replay tests would have caught the same failure
- rule/config change required, if any

The purpose is not to minimize incident count. It is to make every stop and recovery explainable, reproducible, and auditable.
