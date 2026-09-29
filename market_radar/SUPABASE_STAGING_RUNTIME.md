# Supabase Persistent Staging Runtime

Purpose: accumulate persistent infrastructure evidence without exposing the production Railway database.

## Project

- Supabase project: ai-brokerage-staging
- Project ref: zlkuqxsbpkaflffrjbzi
- Region: ap-northeast-2
- Schema version: 2026.09.29.2
- Schema checksum: 43112fe4a8239b9e6850b54dea566d746987a7bf0a1920bbda8c087263c7af67

## Security boundary

- AI Brokerage public tables have RLS enabled.
- anon/authenticated direct table grants are revoked.
- internal runtime tables live in the non-exposed internal schema.
- cron invocation token is stored encrypted in Supabase Vault.
- Edge Function receives no production broker credential.
- no live-order function or endpoint is present.

## Runtime chain

pg_cron
→ pg_net
→ staging-runtime Edge Function
→ schema/checksum validation
→ internal.staging_runtime_heartbeat

Schedule: every 10 minutes.

## Infra soak summary

View: internal.staging_runtime_soak_summary

Tracks:

- heartbeat count
- first / latest heartbeat
- duration hours
- heartbeat coverage percentage
- maximum heartbeat gap
- schema version match
- checksum match

## Important limitation

This proves persistent database/function/runtime continuity only.

It does NOT replace the 72-hour full Market Radar application soak. The final Release Candidate gate continues to require persistent application staging confirmation and the ai_soak RC_CANDIDATE state.

## Railway experiment

The existing _encoder service was tested as a possible persistent caller. Its function-bun image continued to execute the service's built-in index.tsx rather than the configured custom start command and crashed. The service was returned to its prior sleeping/yearly/restart-never configuration, and staging invocation variables were cleared.

Supabase pg_cron + Edge Function remains the active persistent infra runtime.
