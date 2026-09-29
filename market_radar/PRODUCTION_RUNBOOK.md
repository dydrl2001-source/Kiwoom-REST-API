# Market Radar Production Hardening Runbook

This runbook covers the Paper/Shadow Market Radar stack. It does not enable live broker orders.

## Release sequence

1. Pull the intended commit SHA.
2. Confirm .env has an explicit MARKET_RADAR_SCHEMA_VERSION.
3. Build the image.
4. Back up PostgreSQL.
5. Apply the versioned schema bundle.
6. Start services.
7. Verify GET /health/live.
8. Verify GET /health/ready.
9. Verify Risk Control freshness and Resilience Audit.
10. Run an isolated restore drill from the new backup.
11. Keep the release in Shadow-only mode.

## Schema migration

The one-shot schema-migrate service records schema version, bundle checksum, included modules, and applied timestamp.

Run:

~~~bash
docker compose run --rm schema-migrate
docker compose run --rm radar-api python /app/schema_migrate.py check
~~~

If the same version has a different checksum, migration stops. Review the change and bump MARKET_RADAR_SCHEMA_VERSION; do not bypass checksum drift.

## Liveness and readiness

GET /health/live checks process liveness only.

GET /health/ready checks database connectivity, current schema version, and fresh Risk Control state when required.

A service can be live but not ready.

## Backup

From market_radar/local:

~~~bash
sh backup_db.sh
~~~

Backups are PostgreSQL custom-format dumps, non-empty, with SHA-256 checksums, and are ignored by Git.

## Restore drill

Never verify restore by overwriting the primary database.

~~~bash
sh restore_verify.sh backups/<backup-file>.dump
~~~

The script restores into market_radar_restore_check, checks tables and schema history, then drops that temporary database.

## CI gate

.github/workflows/market-radar-ci.yml runs Python compilation, all Market Radar tests, a no-live-order guard, and a local Docker image build.

## Rollback

1. Set RISK_MANUAL_HALT=1.
2. Confirm effective Kill Switch is HALT.
3. Back up the database.
4. Stop changed services.
5. Deploy the previously known-good commit/image.
6. Do not restore an older database merely to match older application code.
7. Run schema_migrate.py check.
8. Verify /health/live and /health/ready.
9. Prefer a forward compatibility migration.
10. Complete the recovery latch before Shadow entry resumes.

Database restore is a disaster-recovery action, not a normal application rollback.

## Release candidate evidence

- PR mergeable
- branch not behind main
- CI green
- schema migration check passes
- database backup succeeds
- isolated restore drill succeeds
- API readiness passes
- Risk Control fresh
- Resilience Audit PASS
- Shadow fail-safe preserved
- no live-order path
- incident recovery Runbook available

## Secrets

Never commit APP_KEY, APP_SECRET, mock keys, TELEGRAM_API_HASH, DART_API_KEY, OPENAI_API_KEY, real DATABASE_URL credentials, or DASHBOARD_TOKEN.

## SLO baseline

- API process liveness > 99% during intended runtime window
- Risk Control age <= 120 seconds
- critical market-feed age <= 180 seconds
- order-book status age <= 90 seconds when relevant targets exist
- Resilience Audit PASS
- unsafe HALT-to-RUN transitions = 0
- broker-order calls from this branch = 0

These are operational research targets, not financial-performance promises.

## Final rule

A release is not healthy because the dashboard loads. It is healthy only when the schema is known, data can be restored, critical state is fresh, safety controls are auditable, and rollback does not require rewriting historical evidence.
