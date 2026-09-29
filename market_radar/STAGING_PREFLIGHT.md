# AI Brokerage Staging Preflight

This document defines the staging validation required before the Phase 10 branch can be called a Release Candidate.

## Current production finding

The existing Railway production radar-api is a legacy Telegram Stock Radar analytics service.

Observed production contract:

- GET /health = 200
- GET /health/live = 404
- GET /health/ready = 404
- OpenAPI title = Telegram Stock Radar Analytics
- current Railway start command downloads selected files from GitHub main at runtime
- the production service is not running the Phase 10 AI Brokerage service graph

Therefore current production is not a valid smoke target for the new AI Brokerage release.

Do not retrofit the production service in place for the first smoke test.

## Required staging isolation

Create an isolated staging environment/project with:

- separate PostgreSQL database
- no production database reuse
- no live broker-order path
- feature/ai-brokerage-v1-synced commit/branch
- MARKET_RADAR_SCHEMA_VERSION pinned
- RISK_CONTROL_REQUIRED=1
- LIVE_READINESS_COSTS_CONFIRMED=0 unless real assumptions were reviewed
- RISK_MANUAL_HALT=0 for normal smoke, 1 for explicit halt drill

Required core services:

- postgres
- schema-migrate
- radar-api
- kiwoom-feed
- chart-feed
- market-regime
- candidate-tracker
- mimosa-engine
- ai-brokerage-worker
- paper-trade-engine
- orderbook-collector
- risk-control-worker
- resilience-audit-worker
- shadow-execution-engine
- capital-allocation-worker
- paper-feedback-engine

Optional research services may be added after core smoke passes.

## Smoke sequence

1. Start staging Postgres.
2. Run schema-migrate once.
3. Confirm schema_migrate.py check passes.
4. Start core read-only market services.
5. Start AI Brokerage / Paper / Order Book services.
6. Start Risk Control before Shadow.
7. Start Shadow and Allocation.
8. Verify GET /health/live = 200.
9. Verify GET /health/ready = 200.
10. Run release_preflight.py with the staging public URL.
11. With DASHBOARD_TOKEN, verify protected dashboard contract.
12. Confirm ai_brokerage.paper_only = true.
13. Confirm live_readiness.live_enabled = false.
14. Confirm no LIVE_ENTRY decision state appears.
15. Confirm Resilience Audit PASS.
16. Trigger manual HALT drill and verify new Shadow entries stop.
17. Complete recovery-latch acknowledgement flow.
18. Run database backup.
19. Run isolated restore_verify.sh.
20. Leave staging running for soak validation.

## Preflight command

~~~bash
cd market_radar
PREFLIGHT_BASE_URL=https://<staging-domain> \
DASHBOARD_TOKEN=<staging-dashboard-token> \
python release_preflight.py
~~~

Expected result:

~~~text
preflight=PASS
health_live PASS
health_ready PASS
openapi_contract PASS
ai_brokerage_contract PASS
paper_only PASS
live_disabled PASS
no_live_entry_state PASS
risk_control_present PASS
allocation_present PASS
shadow_present PASS
resilience_present PASS
~~~

## Smoke failure classification

### health/live fails

API process/build/startup issue.

### health/live passes but health/ready fails

Check:

- database connectivity
- schema migration version/checksum
- Risk Control freshness

### openapi_contract fails

The wrong application/version is deployed. This is the exact failure currently observed on the legacy Railway production service.

### dashboard contract fails

The deployment is missing one or more AI Brokerage Phase 6-9 payloads.

### live_disabled fails

Release must be stopped immediately. This branch is designed to remain Shadow-only.

## Exit criteria for Phase 11

Phase 11 is complete only when an isolated staging target returns a full release_preflight PASS and the backup/restore drill passes on that staging database.

Production must remain unchanged until that evidence exists.
