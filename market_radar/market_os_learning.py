"""Market OS shadow-learning worker.

Captures live multi-axis assessments and resolves ex-post outcomes from already
stored market data. It NEVER places orders and it never rewrites rule thresholds
automatically. Learning runs in shadow mode until a segment has enough samples
to be statistically worth reviewing.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta, time as dtime
import json
import hashlib
import math
import os
import statistics
import time
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from flow_store import desk_payload
from flow_core import dt as parse_dt
from market_os_rule_engine import VERSION as RULE_VERSION
from market_os_store import (
    _quality as store_quality,
    _segment_depth as store_segment_depth,
    _enrich_edges as store_enrich_edges,
    _validation_candidates as store_validation_candidates,
    _promotion_stage,
)
from market_os_shadow import (
    evaluate as shadow_evaluate,
    experiment_summaries as shadow_experiment_summaries,
    experiment_slices as shadow_experiment_slices,
    shadow_decision,
)
from market_os_dossier import build_dossier as build_adoption_dossier, dossier_hash as adoption_dossier_hash
from market_os_ruleset import (
    evaluate as ruleset_evaluate,
    dry_run_summaries as ruleset_dry_run_summaries,
    dry_run_slices as ruleset_dry_run_slices,
    impact_concentration as ruleset_impact_concentration,
    succession_decision as ruleset_succession_decision,
)
from market_os_release import (
    is_canary_selected,
    canary_bucket,
    canary_summaries,
    canary_slices,
    canary_decision,
)
from market_os_full_release import full_release_gate, build_review_package as build_full_release_review
from market_os_control import (
    base_control as runtime_base_control,
    candidate_control as runtime_candidate_control,
    control_hash as runtime_control_hash,
)

DB=os.getenv("DATABASE_URL","")
POLL=max(30,int(os.getenv("MARKET_OS_LEARNING_POLL_SECONDS","60")))
SHADOW_LAB_ENABLED=os.getenv("MARKET_OS_SHADOW_LAB_ENABLED","1").strip().lower() in {"1","true","yes","on"}
RULESET_DRY_RUN_ENABLED=os.getenv("MARKET_OS_RULESET_DRY_RUN_ENABLED","1").strip().lower() in {"1","true","yes","on"}
CANARY_ENABLED=os.getenv("MARKET_OS_CANARY_ENABLED","1").strip().lower() in {"1","true","yes","on"}
KST=ZoneInfo("Asia/Seoul")

SCHEMA=r"""
CREATE TABLE IF NOT EXISTS market_os_assessment_snapshots (
    snapshot_time       TIMESTAMPTZ NOT NULL,
    stock_code          TEXT NOT NULL,
    stock_name          TEXT,
    rule_version        TEXT NOT NULL,
    watch_tier          TEXT NOT NULL,
    radar_score         SMALLINT,
    theme_score         SMALLINT,
    setup_score         SMALLINT,
    catalyst_grade      TEXT,
    trigger_state       TEXT,
    market_stance       TEXT,
    session_bucket      TEXT,
    market_theme        TEXT,
    event_type          TEXT,
    current_price_krw   NUMERIC,
    change_pct          DOUBLE PRECISION,
    query_rank          INTEGER,
    trade_rank          INTEGER,
    interval_turnover_krw NUMERIC,
    five_min_turnover_krw NUMERIC,
    burst_multiple      DOUBLE PRECISION,
    theme_share_change_pp DOUBLE PRECISION,
    chart_state         TEXT,
    micro_trade_value_15s_krw NUMERIC,
    micro_buy_share_15s DOUBLE PRECISION,
    micro_tick_count_15s INTEGER,
    micro_gap_count_15s INTEGER,
    micro_strength      DOUBLE PRECISION,
    micro_buy_ratio     DOUBLE PRECISION,
    axis_reasons        JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_flags          JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_ref        JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_time, stock_code, rule_version)
);
CREATE INDEX IF NOT EXISTS idx_market_os_assessment_code_time
    ON market_os_assessment_snapshots(stock_code, snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_market_os_assessment_tier_time
    ON market_os_assessment_snapshots(watch_tier, snapshot_time DESC);
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_trade_value_15s_krw NUMERIC;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_buy_share_15s DOUBLE PRECISION;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_tick_count_15s INTEGER;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_gap_count_15s INTEGER;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_strength DOUBLE PRECISION;
ALTER TABLE market_os_assessment_snapshots ADD COLUMN IF NOT EXISTS micro_buy_ratio DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS market_os_assessment_outcomes (
    assessment_time     TIMESTAMPTZ NOT NULL,
    stock_code          TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    horizon             TEXT NOT NULL,
    reference_price_krw NUMERIC NOT NULL,
    outcome_price_krw   NUMERIC,
    return_pct          DOUBLE PRECISION,
    mfe_pct             DOUBLE PRECISION,
    mae_pct             DOUBLE PRECISION,
    outcome_time        TIMESTAMPTZ,
    outcome_source      TEXT,
    quality_flags       JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (assessment_time, stock_code, rule_version, horizon)
);
CREATE INDEX IF NOT EXISTS idx_market_os_outcome_horizon
    ON market_os_assessment_outcomes(horizon, assessment_time DESC);

CREATE TABLE IF NOT EXISTS market_os_learning_segments (
    segment_type        TEXT NOT NULL,
    segment_value       TEXT NOT NULL,
    horizon             TEXT NOT NULL,
    samples             INTEGER NOT NULL,
    distinct_stocks     INTEGER NOT NULL DEFAULT 0,
    distinct_days       INTEGER NOT NULL DEFAULT 0,
    sample_basis        TEXT NOT NULL DEFAULT 'RAW',
    avg_return_pct      DOUBLE PRECISION,
    median_return_pct   DOUBLE PRECISION,
    positive_rate       DOUBLE PRECISION,
    avg_mfe_pct         DOUBLE PRECISION,
    avg_mae_pct         DOUBLE PRECISION,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (segment_type, segment_value, horizon)
);

ALTER TABLE market_os_learning_segments ADD COLUMN IF NOT EXISTS distinct_stocks INTEGER NOT NULL DEFAULT 0;
ALTER TABLE market_os_learning_segments ADD COLUMN IF NOT EXISTS distinct_days INTEGER NOT NULL DEFAULT 0;
ALTER TABLE market_os_learning_segments ADD COLUMN IF NOT EXISTS sample_basis TEXT NOT NULL DEFAULT 'RAW';

CREATE TABLE IF NOT EXISTS market_os_interaction_edges (
    segment_type             TEXT NOT NULL,
    segment_value            TEXT NOT NULL,
    horizon                  TEXT NOT NULL,
    parent_type              TEXT NOT NULL,
    parent_value             TEXT NOT NULL,
    sample_basis             TEXT NOT NULL,
    child_samples            INTEGER NOT NULL,
    child_stocks             INTEGER NOT NULL,
    child_days               INTEGER NOT NULL,
    comparator_samples       INTEGER NOT NULL,
    comparator_stocks        INTEGER NOT NULL,
    comparator_days          INTEGER NOT NULL,
    child_avg_return_pct     DOUBLE PRECISION,
    comparator_avg_return_pct DOUBLE PRECISION,
    delta_avg_return_pct     DOUBLE PRECISION,
    child_positive_rate      DOUBLE PRECISION,
    comparator_positive_rate DOUBLE PRECISION,
    delta_positive_rate_pp   DOUBLE PRECISION,
    child_avg_mfe_pct        DOUBLE PRECISION,
    comparator_avg_mfe_pct   DOUBLE PRECISION,
    delta_mfe_pct            DOUBLE PRECISION,
    child_avg_mae_pct        DOUBLE PRECISION,
    comparator_avg_mae_pct   DOUBLE PRECISION,
    delta_mae_pct            DOUBLE PRECISION,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(segment_type,segment_value,horizon)
);

CREATE TABLE IF NOT EXISTS market_os_walk_forward_windows (
    segment_type             TEXT NOT NULL,
    segment_value            TEXT NOT NULL,
    horizon                  TEXT NOT NULL,
    window_name              TEXT NOT NULL,
    start_day                DATE,
    end_day                  DATE,
    samples                  INTEGER NOT NULL,
    distinct_stocks          INTEGER NOT NULL DEFAULT 0,
    distinct_days            INTEGER NOT NULL DEFAULT 0,
    avg_return_pct           DOUBLE PRECISION,
    median_return_pct        DOUBLE PRECISION,
    positive_rate            DOUBLE PRECISION,
    avg_mfe_pct              DOUBLE PRECISION,
    avg_mae_pct              DOUBLE PRECISION,
    comparator_samples       INTEGER,
    comparator_stocks        INTEGER,
    comparator_days          INTEGER,
    comparator_avg_return_pct DOUBLE PRECISION,
    comparator_positive_rate DOUBLE PRECISION,
    comparator_avg_mae_pct   DOUBLE PRECISION,
    delta_avg_return_pct     DOUBLE PRECISION,
    delta_positive_rate_pp   DOUBLE PRECISION,
    delta_mae_pct            DOUBLE PRECISION,
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(segment_type,segment_value,horizon,window_name)
);

CREATE TABLE IF NOT EXISTS market_os_promotion_registry (
    candidate_key           TEXT PRIMARY KEY,
    rule_version            TEXT NOT NULL,
    segment_type            TEXT NOT NULL,
    segment_value           TEXT NOT NULL,
    horizon                 TEXT NOT NULL,
    interaction_depth       INTEGER NOT NULL DEFAULT 1,
    current_stage           TEXT NOT NULL,
    direction               TEXT NOT NULL DEFAULT 'MIXED',
    review_action           TEXT NOT NULL DEFAULT 'NONE',
    manual_review_state     TEXT NOT NULL DEFAULT 'PENDING',
    active                  BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    stage_since             TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_transition_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    samples                 INTEGER NOT NULL DEFAULT 0,
    distinct_stocks         INTEGER NOT NULL DEFAULT 0,
    distinct_days           INTEGER NOT NULL DEFAULT 0,
    quality                 TEXT,
    walk_forward_status     TEXT,
    avg_return_pct          DOUBLE PRECISION,
    median_return_pct       DOUBLE PRECISION,
    positive_rate           DOUBLE PRECISION,
    edge_avg_return_pct     DOUBLE PRECISION,
    edge_positive_rate_pp   DOUBLE PRECISION,
    edge_mae_pct            DOUBLE PRECISION,
    early_avg_return_pct    DOUBLE PRECISION,
    recent_avg_return_pct   DOUBLE PRECISION,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb,
    shadow_rule_id          TEXT,
    manual_note             TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_os_promotion_stage
    ON market_os_promotion_registry(rule_version,current_stage,active);
CREATE INDEX IF NOT EXISTS idx_market_os_promotion_seen
    ON market_os_promotion_registry(last_seen_at DESC);

CREATE TABLE IF NOT EXISTS market_os_promotion_events (
    event_id                BIGSERIAL PRIMARY KEY,
    candidate_key           TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type              TEXT NOT NULL,
    from_stage              TEXT,
    to_stage                TEXT NOT NULL,
    direction               TEXT,
    review_action           TEXT,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_promotion_events_candidate
    ON market_os_promotion_events(candidate_key,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_shadow_rules (
    shadow_rule_id          TEXT PRIMARY KEY,
    candidate_key           TEXT NOT NULL UNIQUE,
    rule_version            TEXT NOT NULL,
    segment_type            TEXT NOT NULL,
    segment_value           TEXT NOT NULL,
    source_horizon          TEXT NOT NULL,
    action                  TEXT NOT NULL CHECK(action IN ('PROMOTE_ONE_TIER','SUPPRESS_ONE_TIER')),
    enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    approved_at             TIMESTAMPTZ NOT NULL,
    approved_by             TEXT NOT NULL DEFAULT 'MANUAL',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at             TIMESTAMPTZ,
    last_evaluated_at       TIMESTAMPTZ,
    note                    TEXT,
    spec                    JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_shadow_rules_enabled
    ON market_os_shadow_rules(enabled,approved_at DESC);

CREATE TABLE IF NOT EXISTS market_os_shadow_observations (
    assessment_time         TIMESTAMPTZ NOT NULL,
    stock_code              TEXT NOT NULL,
    rule_version            TEXT NOT NULL,
    shadow_rule_id          TEXT NOT NULL,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    matched                 BOOLEAN NOT NULL,
    changed                 BOOLEAN NOT NULL,
    control_tier            TEXT NOT NULL,
    challenger_tier         TEXT NOT NULL,
    action                  TEXT NOT NULL,
    PRIMARY KEY(assessment_time,stock_code,rule_version,shadow_rule_id)
);
CREATE INDEX IF NOT EXISTS idx_market_os_shadow_obs_rule_time
    ON market_os_shadow_observations(shadow_rule_id,assessment_time DESC);

CREATE TABLE IF NOT EXISTS market_os_shadow_experiment_summary (
    shadow_rule_id              TEXT NOT NULL,
    horizon                     TEXT NOT NULL,
    cohort                      TEXT NOT NULL,
    evidence_state              TEXT NOT NULL,
    membership_changes          INTEGER NOT NULL DEFAULT 0,
    control_samples             INTEGER NOT NULL DEFAULT 0,
    control_stocks              INTEGER NOT NULL DEFAULT 0,
    control_days                INTEGER NOT NULL DEFAULT 0,
    control_avg_return_pct      DOUBLE PRECISION,
    control_median_return_pct   DOUBLE PRECISION,
    control_positive_rate       DOUBLE PRECISION,
    control_avg_mfe_pct         DOUBLE PRECISION,
    control_avg_mae_pct         DOUBLE PRECISION,
    challenger_samples          INTEGER NOT NULL DEFAULT 0,
    challenger_stocks           INTEGER NOT NULL DEFAULT 0,
    challenger_days             INTEGER NOT NULL DEFAULT 0,
    challenger_avg_return_pct   DOUBLE PRECISION,
    challenger_median_return_pct DOUBLE PRECISION,
    challenger_positive_rate    DOUBLE PRECISION,
    challenger_avg_mfe_pct      DOUBLE PRECISION,
    challenger_avg_mae_pct      DOUBLE PRECISION,
    delta_avg_return_pct        DOUBLE PRECISION,
    delta_positive_rate_pp      DOUBLE PRECISION,
    delta_mae_pct               DOUBLE PRECISION,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(shadow_rule_id,horizon,cohort)
);

CREATE TABLE IF NOT EXISTS market_os_shadow_decisions (
    shadow_rule_id          TEXT PRIMARY KEY,
    decision_state          TEXT NOT NULL,
    review_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    primary_cohort          TEXT,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb,
    manual_decision_state   TEXT NOT NULL DEFAULT 'PENDING',
    state_since             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_market_os_shadow_decision_state
    ON market_os_shadow_decisions(decision_state,review_eligible,updated_at DESC);

CREATE TABLE IF NOT EXISTS market_os_shadow_decision_events (
    event_id                BIGSERIAL PRIMARY KEY,
    shadow_rule_id          TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_state              TEXT,
    to_state                TEXT NOT NULL,
    review_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_shadow_decision_events
    ON market_os_shadow_decision_events(shadow_rule_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_adoption_dossiers (
    dossier_id              TEXT PRIMARY KEY,
    shadow_rule_id          TEXT NOT NULL,
    revision                INTEGER NOT NULL,
    content_hash            TEXT NOT NULL,
    decision_state          TEXT NOT NULL,
    decision_updated_at     TIMESTAMPTZ,
    source_decision_event_id BIGINT,
    review_state            TEXT NOT NULL DEFAULT 'PENDING',
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at             TIMESTAMPTZ,
    reviewed_by             TEXT,
    review_note             TEXT,
    dossier                 JSONB NOT NULL,
    UNIQUE(shadow_rule_id,revision)
);
ALTER TABLE market_os_adoption_dossiers ADD COLUMN IF NOT EXISTS source_decision_event_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_market_os_adoption_dossier_rule
    ON market_os_adoption_dossiers(shadow_rule_id,revision DESC);
CREATE INDEX IF NOT EXISTS idx_market_os_adoption_dossier_review
    ON market_os_adoption_dossiers(review_state,generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_os_adoption_dossier_hash
    ON market_os_adoption_dossiers(shadow_rule_id,content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_os_adoption_dossier_accept_event
    ON market_os_adoption_dossiers(shadow_rule_id,source_decision_event_id)
    WHERE source_decision_event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS market_os_adoption_dossier_events (
    event_id                BIGSERIAL PRIMARY KEY,
    dossier_id              TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type              TEXT NOT NULL,
    from_review_state       TEXT,
    to_review_state         TEXT NOT NULL,
    note                    TEXT,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_adoption_dossier_events
    ON market_os_adoption_dossier_events(dossier_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_versioned_rulesets (
    ruleset_id              TEXT PRIMARY KEY,
    version_label           TEXT NOT NULL UNIQUE,
    base_rule_version       TEXT NOT NULL,
    source_dossier_id       TEXT NOT NULL UNIQUE,
    source_shadow_rule_id   TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK(status IN (
                                'DRY_RUN_ACTIVE','DRY_RUN_STOPPED','STALE_SOURCE')),
    spec_hash               TEXT NOT NULL,
    spec                    JSONB NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at            TIMESTAMPTZ NOT NULL,
    stopped_at              TIMESTAMPTZ,
    stale_at                TIMESTAMPTZ,
    last_evaluated_at       TIMESTAMPTZ,
    note                    TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_os_ruleset_status
    ON market_os_versioned_rulesets(status,activated_at DESC);

CREATE TABLE IF NOT EXISTS market_os_ruleset_dry_run_observations (
    assessment_time         TIMESTAMPTZ NOT NULL,
    stock_code              TEXT NOT NULL,
    control_rule_version    TEXT NOT NULL,
    ruleset_id              TEXT NOT NULL,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    control_tier            TEXT NOT NULL,
    candidate_tier          TEXT NOT NULL,
    changed                 BOOLEAN NOT NULL,
    matched_overlays        JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY(assessment_time,stock_code,control_rule_version,ruleset_id)
);
CREATE INDEX IF NOT EXISTS idx_market_os_ruleset_obs_time
    ON market_os_ruleset_dry_run_observations(ruleset_id,assessment_time DESC);

CREATE TABLE IF NOT EXISTS market_os_ruleset_dry_run_summary (
    ruleset_id                  TEXT NOT NULL,
    horizon                     TEXT NOT NULL,
    cohort                      TEXT NOT NULL,
    evidence_state              TEXT NOT NULL,
    membership_changes          INTEGER NOT NULL DEFAULT 0,
    control_samples             INTEGER NOT NULL DEFAULT 0,
    control_stocks              INTEGER NOT NULL DEFAULT 0,
    control_days                INTEGER NOT NULL DEFAULT 0,
    control_avg_return_pct      DOUBLE PRECISION,
    control_median_return_pct   DOUBLE PRECISION,
    control_positive_rate       DOUBLE PRECISION,
    control_avg_mfe_pct         DOUBLE PRECISION,
    control_avg_mae_pct         DOUBLE PRECISION,
    candidate_samples           INTEGER NOT NULL DEFAULT 0,
    candidate_stocks            INTEGER NOT NULL DEFAULT 0,
    candidate_days              INTEGER NOT NULL DEFAULT 0,
    candidate_avg_return_pct    DOUBLE PRECISION,
    candidate_median_return_pct DOUBLE PRECISION,
    candidate_positive_rate     DOUBLE PRECISION,
    candidate_avg_mfe_pct       DOUBLE PRECISION,
    candidate_avg_mae_pct       DOUBLE PRECISION,
    delta_avg_return_pct        DOUBLE PRECISION,
    delta_positive_rate_pp      DOUBLE PRECISION,
    delta_mae_pct               DOUBLE PRECISION,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(ruleset_id,horizon,cohort)
);

CREATE TABLE IF NOT EXISTS market_os_ruleset_succession_decisions (
    ruleset_id              TEXT PRIMARY KEY,
    decision_state          TEXT NOT NULL,
    review_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    primary_cohort          TEXT,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb,
    manual_review_state     TEXT NOT NULL DEFAULT 'PENDING',
    state_since             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_market_os_ruleset_succession_state
    ON market_os_ruleset_succession_decisions(decision_state,review_eligible,updated_at DESC);

CREATE TABLE IF NOT EXISTS market_os_ruleset_succession_events (
    event_id                BIGSERIAL PRIMARY KEY,
    ruleset_id              TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_state              TEXT,
    to_state                TEXT NOT NULL,
    review_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_ruleset_succession_events
    ON market_os_ruleset_succession_events(ruleset_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_ruleset_events (
    event_id                BIGSERIAL PRIMARY KEY,
    ruleset_id              TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type              TEXT NOT NULL,
    from_status             TEXT,
    to_status               TEXT NOT NULL,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_ruleset_events
    ON market_os_ruleset_events(ruleset_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_release_candidates (
    release_candidate_id    TEXT PRIMARY KEY,
    release_version_label   TEXT NOT NULL UNIQUE,
    source_ruleset_id       TEXT NOT NULL,
    source_succession_event_id BIGINT NOT NULL,
    package_hash            TEXT NOT NULL,
    package                 JSONB NOT NULL,
    status                  TEXT NOT NULL CHECK(status IN (
                                'RELEASE_CANDIDATE','CANARY_ACTIVE','CANARY_STOPPED',
                                'CANARY_SOURCE_STALE','CANARY_ROLLBACK_REQUIRED')),
    canary_allocation_pct   INTEGER NOT NULL CHECK(canary_allocation_pct BETWEEN 1 AND 25),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    canary_started_at       TIMESTAMPTZ,
    stopped_at              TIMESTAMPTZ,
    stale_at                TIMESTAMPTZ,
    rollback_at             TIMESTAMPTZ,
    canary_last_scanned_at  TIMESTAMPTZ,
    last_evaluated_at       TIMESTAMPTZ,
    note                    TEXT,
    UNIQUE(source_ruleset_id,source_succession_event_id)
);
ALTER TABLE market_os_release_candidates ADD COLUMN IF NOT EXISTS canary_last_scanned_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_market_os_release_status
    ON market_os_release_candidates(status,created_at DESC);

CREATE TABLE IF NOT EXISTS market_os_release_events (
    event_id                BIGSERIAL PRIMARY KEY,
    release_candidate_id    TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type              TEXT NOT NULL,
    from_status             TEXT,
    to_status               TEXT NOT NULL,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_release_events
    ON market_os_release_events(release_candidate_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_canary_observations (
    assessment_time         TIMESTAMPTZ NOT NULL,
    stock_code              TEXT NOT NULL,
    control_rule_version    TEXT NOT NULL,
    release_candidate_id    TEXT NOT NULL,
    trade_day               DATE NOT NULL,
    assignment_bucket       INTEGER NOT NULL,
    allocation_pct          INTEGER NOT NULL,
    control_tier            TEXT NOT NULL,
    candidate_tier          TEXT NOT NULL,
    changed                 BOOLEAN NOT NULL,
    matched_overlays        JSONB NOT NULL DEFAULT '[]'::jsonb,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(assessment_time,stock_code,control_rule_version,release_candidate_id)
);
CREATE INDEX IF NOT EXISTS idx_market_os_canary_obs
    ON market_os_canary_observations(release_candidate_id,assessment_time DESC);

CREATE TABLE IF NOT EXISTS market_os_canary_summary (
    release_candidate_id        TEXT NOT NULL,
    horizon                     TEXT NOT NULL,
    cohort                      TEXT NOT NULL,
    evidence_state              TEXT NOT NULL,
    membership_changes          INTEGER NOT NULL DEFAULT 0,
    control_samples             INTEGER NOT NULL DEFAULT 0,
    control_stocks              INTEGER NOT NULL DEFAULT 0,
    control_days                INTEGER NOT NULL DEFAULT 0,
    control_avg_return_pct      DOUBLE PRECISION,
    control_median_return_pct   DOUBLE PRECISION,
    control_positive_rate       DOUBLE PRECISION,
    control_avg_mfe_pct         DOUBLE PRECISION,
    control_avg_mae_pct         DOUBLE PRECISION,
    candidate_samples           INTEGER NOT NULL DEFAULT 0,
    candidate_stocks            INTEGER NOT NULL DEFAULT 0,
    candidate_days              INTEGER NOT NULL DEFAULT 0,
    candidate_avg_return_pct    DOUBLE PRECISION,
    candidate_median_return_pct DOUBLE PRECISION,
    candidate_positive_rate     DOUBLE PRECISION,
    candidate_avg_mfe_pct       DOUBLE PRECISION,
    candidate_avg_mae_pct       DOUBLE PRECISION,
    delta_avg_return_pct        DOUBLE PRECISION,
    delta_positive_rate_pp      DOUBLE PRECISION,
    delta_mae_pct               DOUBLE PRECISION,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(release_candidate_id,horizon,cohort)
);

CREATE TABLE IF NOT EXISTS market_os_canary_decisions (
    release_candidate_id    TEXT PRIMARY KEY,
    decision_state          TEXT NOT NULL,
    review_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    primary_cohort          TEXT,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb,
    manual_review_state     TEXT NOT NULL DEFAULT 'PENDING',
    state_since             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_market_os_canary_decision
    ON market_os_canary_decisions(decision_state,review_eligible,updated_at DESC);

CREATE TABLE IF NOT EXISTS market_os_canary_decision_events (
    event_id                BIGSERIAL PRIMARY KEY,
    release_candidate_id    TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_state              TEXT,
    to_state                TEXT NOT NULL,
    review_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_canary_decision_events
    ON market_os_canary_decision_events(release_candidate_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_full_release_gates (
    release_candidate_id    TEXT PRIMARY KEY,
    gate_state              TEXT NOT NULL,
    review_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb,
    state_since             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_market_os_full_release_gate
    ON market_os_full_release_gates(gate_state,review_eligible,updated_at DESC);

CREATE TABLE IF NOT EXISTS market_os_full_release_gate_events (
    event_id                BIGSERIAL PRIMARY KEY,
    release_candidate_id    TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_state              TEXT,
    to_state                TEXT NOT NULL,
    review_eligible         BOOLEAN NOT NULL DEFAULT FALSE,
    reason_codes            JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_full_release_gate_events
    ON market_os_full_release_gate_events(release_candidate_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_full_release_reviews (
    review_id               TEXT PRIMARY KEY,
    release_candidate_id    TEXT NOT NULL,
    revision                INTEGER NOT NULL,
    source_gate_event_id    BIGINT NOT NULL,
    content_hash            TEXT NOT NULL,
    gate_state              TEXT NOT NULL,
    review_state            TEXT NOT NULL DEFAULT 'PENDING' CHECK(review_state IN (
                                'PENDING','RELEASE_READY','REJECTED',
                                'STALE_CANARY','SUPERSEDED')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at             TIMESTAMPTZ,
    reviewed_by             TEXT,
    review_note             TEXT,
    package                 JSONB NOT NULL,
    UNIQUE(release_candidate_id,revision),
    UNIQUE(release_candidate_id,source_gate_event_id)
);
CREATE INDEX IF NOT EXISTS idx_market_os_full_release_reviews
    ON market_os_full_release_reviews(review_state,created_at DESC);

CREATE TABLE IF NOT EXISTS market_os_full_release_review_events (
    event_id                BIGSERIAL PRIMARY KEY,
    review_id               TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type              TEXT NOT NULL,
    from_review_state       TEXT,
    to_review_state         TEXT NOT NULL,
    note                    TEXT,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_full_release_review_events
    ON market_os_full_release_review_events(review_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_control_state (
    id                      INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
    control_id              TEXT NOT NULL,
    mode                    TEXT NOT NULL CHECK(mode IN ('BASE','RULESET')),
    active_version_label    TEXT NOT NULL,
    base_rule_version       TEXT NOT NULL,
    ruleset_id              TEXT,
    ruleset_hash            TEXT,
    ruleset_spec            JSONB,
    source_review_id        TEXT,
    switch_transaction_id   TEXT,
    control_hash            TEXT NOT NULL,
    activated_at            TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_os_switch_transactions (
    switch_transaction_id   TEXT PRIMARY KEY,
    source_review_id        TEXT NOT NULL,
    release_candidate_id    TEXT NOT NULL,
    ruleset_id              TEXT NOT NULL,
    state                   TEXT NOT NULL CHECK(state IN (
                                'PREPARED_SWITCH','COMMITTED','HEALTHY',
                                'ROLLED_BACK','AUTO_ROLLED_BACK','CANCELLED')),
    expected_control_hash   TEXT NOT NULL,
    previous_control        JSONB NOT NULL,
    candidate_control       JSONB NOT NULL,
    candidate_hash          TEXT NOT NULL,
    pre_switch_watch_count  INTEGER NOT NULL DEFAULT 0,
    prepared_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    committed_at            TIMESTAMPTZ,
    health_deadline         TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    rollback_at             TIMESTAMPTZ,
    rollback_reason         TEXT,
    note                    TEXT
);
CREATE INDEX IF NOT EXISTS idx_market_os_switch_state
    ON market_os_switch_transactions(state,prepared_at DESC);

CREATE TABLE IF NOT EXISTS market_os_switch_events (
    event_id                BIGSERIAL PRIMARY KEY,
    switch_transaction_id   TEXT NOT NULL,
    event_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type              TEXT NOT NULL,
    from_state              TEXT,
    to_state                TEXT NOT NULL,
    evidence                JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_market_os_switch_events
    ON market_os_switch_events(switch_transaction_id,event_time DESC);

CREATE TABLE IF NOT EXISTS market_os_learning_status (
    id                  INTEGER PRIMARY KEY DEFAULT 1 CHECK(id=1),
    updated_at          TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL,
    last_snapshot_at    TIMESTAMPTZ,
    last_outcome_at     TIMESTAMPTZ,
    assessments_total   BIGINT NOT NULL DEFAULT 0,
    outcomes_total      BIGINT NOT NULL DEFAULT 0,
    note                TEXT
);
"""


def db():
    return psycopg.connect(DB,row_factory=dict_row,connect_timeout=5,
                           options="-c statement_timeout=20000 -c lock_timeout=3000")


def table_exists(cur,name):
    cur.execute("SELECT to_regclass(%s) AS name",("public."+name,))
    return cur.fetchone()["name"] is not None


def ensure_schema():
    with db() as c,c.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(72419071)")
        cur.execute(SCHEMA)
        base=runtime_base_control(RULE_VERSION)
        cur.execute("""INSERT INTO market_os_control_state(
                id,control_id,mode,active_version_label,base_rule_version,
                ruleset_id,ruleset_hash,ruleset_spec,source_review_id,
                switch_transaction_id,control_hash,activated_at,updated_at)
            VALUES(1,%s,%s,%s,%s,NULL,NULL,NULL,NULL,NULL,%s,NULL,now())
            ON CONFLICT(id) DO NOTHING""",
            (base["control_id"],base["mode"],base["active_version_label"],
             base["base_rule_version"],base["control_hash"]))


def session_bucket(ts):
    local=ts.astimezone(KST)
    t=local.time()
    if t < dtime(9,0):
        return "PRE"
    if t < dtime(9,20):
        return "OPEN_20"
    if t < dtime(11,30):
        return "MORNING"
    if t < dtime(13,30):
        return "MIDDAY"
    if t < dtime(14,50):
        return "AFTERNOON"
    if t <= dtime(15,30):
        return "CLOSE"
    return "AFTER"


def active_control_version(cur):
    if not table_exists(cur,"market_os_control_state"):
        return RULE_VERSION
    cur.execute("SELECT active_version_label FROM market_os_control_state WHERE id=1")
    r=cur.fetchone()
    return (r["active_version_label"] if r and r["active_version_label"] else RULE_VERSION)


def active_control_snapshot(cur):
    base=runtime_base_control(RULE_VERSION)
    if not table_exists(cur,"market_os_control_state"):
        return base
    cur.execute("""SELECT control_id,mode,active_version_label,base_rule_version,
                          ruleset_id,ruleset_hash,ruleset_spec,source_review_id,
                          switch_transaction_id,control_hash,activated_at
                   FROM market_os_control_state WHERE id=1""")
    r=cur.fetchone()
    if not r:
        return base
    out=dict(r)
    if out.get("activated_at"):
        out["activated_at"]=out["activated_at"].isoformat()
    return out


def safe_num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):
        return None


def current_microstructure(codes,sample):
    """Use only fully closed 5-second buckets at/before the assessment."""
    codes=[x for x in codes if x]
    if not codes:return {}
    with db() as c,c.cursor() as cur:
        if not table_exists(cur,"market_realtime_5s_bars"):
            return {}
        end=sample-timedelta(seconds=5)
        start=end-timedelta(seconds=15)
        cur.execute("""SELECT stock_code,
                              SUM(trade_value_krw) AS tv,
                              SUM(buy_volume) AS buy,
                              SUM(sell_volume) AS sell,
                              SUM(tick_count) AS ticks,
                              SUM(gap_count) AS gaps
                       FROM market_realtime_5s_bars
                       WHERE stock_code=ANY(%s) AND bucket_time>=%s AND bucket_time<=%s
                       GROUP BY stock_code""",(codes,start,end))
        out={}
        for r in cur.fetchall():
            buy=safe_num(r["buy"]) or 0;sell=safe_num(r["sell"]) or 0;den=buy+sell
            out[r["stock_code"]]={
                "trade_value_15s_krw":safe_num(r["tv"]),
                "buy_share_15s":buy/den if den else None,
                "tick_count_15s":int(r["ticks"] or 0),
                "gap_count_15s":int(r["gaps"] or 0),
                "strength":None,"buy_ratio":None,
            }
        cur.execute("""SELECT DISTINCT ON(stock_code)
                              stock_code,last_strength,last_buy_ratio,bucket_time
                       FROM market_realtime_5s_bars
                       WHERE stock_code=ANY(%s) AND bucket_time<=%s
                       ORDER BY stock_code,bucket_time DESC""",(codes,end))
        for r in cur.fetchall():
            x=out.setdefault(r["stock_code"],{
                "trade_value_15s_krw":None,"buy_share_15s":None,
                "tick_count_15s":0,"gap_count_15s":0,"strength":None,"buy_ratio":None
            })
            x["strength"]=safe_num(r["last_strength"]);x["buy_ratio"]=safe_num(r["last_buy_ratio"])
        return out


def capture_assessments():
    payload=desk_payload(include_tracking=False)
    control_meta=payload.get("market_os_control") or {}
    if not payload.get("recent_trade_count"):
        return 0,None,control_meta
    sample=parse_dt(payload.get("sample_time"))
    if not sample:
        return 0,None,control_meta
    age=(datetime.now(timezone.utc)-sample).total_seconds()
    if age < -60 or age > 180:
        return 0,None,control_meta
    snap=sample.replace(microsecond=0)
    micro=current_microstructure([x.get("code") for x in payload.get("market_os_watchlist",[])],sample)
    rows={r.get("code"):r for r in payload.get("rows",[])}
    regime=payload.get("market_regime") or {}
    items=[]
    for x in payload.get("market_os_watchlist",[]):
        code=x.get("code")
        r=rows.get(code) or {}
        px=safe_num(r.get("price_krw"))
        if not code or px is None or px<=0:
            continue
        evidence={
            "market_regime_snapshot":regime.get("snapshot_time"),
            "chart_snapshot":(r.get("chart") or {}).get("snapshot_time"),
            "research_id":((r.get("research") or {}).get("id")),
            "research_completed_at":((r.get("research") or {}).get("completed_at")),
            "sample_time":payload.get("sample_time"),
            "source":"flow_desk"
        }
        assessment_version=payload.get("market_os_version") or RULE_VERSION
        items.append((
            snap,code,x.get("name"),assessment_version,x.get("watch_tier"),
            x.get("radar_score"),x.get("theme_score"),x.get("setup_score"),
            x.get("catalyst_grade"),x.get("trigger_state"),x.get("market_stance"),
            session_bucket(snap),x.get("market_theme"),x.get("event_type"),px,
            safe_num(x.get("change_pct")),x.get("query_rank"),x.get("trade_rank"),
            x.get("interval_turnover_krw"),x.get("five_min_turnover_krw"),
            safe_num(x.get("burst_multiple")),safe_num(x.get("theme_share_change_pp")),
            x.get("chart_state"),
            (micro.get(code) or {}).get("trade_value_15s_krw"),
            (micro.get(code) or {}).get("buy_share_15s"),
            (micro.get(code) or {}).get("tick_count_15s"),
            (micro.get(code) or {}).get("gap_count_15s"),
            (micro.get(code) or {}).get("strength"),
            (micro.get(code) or {}).get("buy_ratio"),
            json.dumps(x.get("axis_reasons") or {},ensure_ascii=False),
            json.dumps(x.get("risk_flags") or [],ensure_ascii=False),
            json.dumps(evidence,ensure_ascii=False)
        ))
    if not items:
        return 0,snap,control_meta
    with db() as c,c.cursor() as cur:
        cur.executemany("""INSERT INTO market_os_assessment_snapshots(
          snapshot_time,stock_code,stock_name,rule_version,watch_tier,
          radar_score,theme_score,setup_score,catalyst_grade,trigger_state,market_stance,
          session_bucket,market_theme,event_type,current_price_krw,change_pct,query_rank,trade_rank,
          interval_turnover_krw,five_min_turnover_krw,burst_multiple,theme_share_change_pp,
          chart_state,micro_trade_value_15s_krw,micro_buy_share_15s,micro_tick_count_15s,
          micro_gap_count_15s,micro_strength,micro_buy_ratio,axis_reasons,risk_flags,evidence_ref)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)
          ON CONFLICT(snapshot_time,stock_code,rule_version) DO NOTHING""",items)
        n=cur.rowcount if cur.rowcount is not None and cur.rowcount>=0 else len(items)
        return n,snap,control_meta


def _realtime_target(cur,code,target,window_seconds=20):
    """First observed 5-second bucket at/after the target time.

    Using the bucket OPEN avoids using prices that occurred after the target.
    """
    if not table_exists(cur,"market_realtime_5s_bars"):
        return None
    cur.execute("""SELECT bucket_time,open_price,gap_count
                   FROM market_realtime_5s_bars
                   WHERE stock_code=%s AND bucket_time>=%s AND bucket_time<=%s
                   ORDER BY bucket_time LIMIT 1""",
                (code,target,target+timedelta(seconds=window_seconds)))
    r=cur.fetchone()
    if not r:return None
    px=safe_num(r["open_price"])
    if px is None or px<=0:return None
    flags=["REALTIME_GAPS"] if int(r["gap_count"] or 0)>0 else []
    return px,r["bucket_time"],"KIWOOM_0B_5S_OPEN",flags


def _sor_target(cur,code,target,window_seconds=150):
    cur.execute("""SELECT batch_time,payload FROM radar_flow_quotes
                   WHERE stock_code=%s AND batch_time>=%s AND batch_time<=%s
                   ORDER BY batch_time LIMIT 1""",
                (code,target,target+timedelta(seconds=window_seconds)))
    r=cur.fetchone()
    if not r:return None
    px=safe_num((r["payload"] or {}).get("price_krw"))
    if px is None or px<=0:return None
    return px,r["batch_time"],"SOR_FLOW"


def _minute_target(cur,code,target,window_minutes=6):
    if not table_exists(cur,"market_minute_bars"):
        return None
    cur.execute("""SELECT bar_time,open_price FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3
                     AND bar_time>=%s AND bar_time<=%s
                   ORDER BY bar_time LIMIT 1""",
                (code,target,target+timedelta(minutes=window_minutes)))
    r=cur.fetchone()
    if not r:return None
    px=safe_num(r["open_price"])
    if px is None or px<=0:return None
    return px,r["bar_time"],"KRX_3M_OPEN_FALLBACK"


def _mfe_mae(cur,code,start,end,reference):
    if not reference or end<=start:
        return None,None,[]
    if table_exists(cur,"market_realtime_5s_bars"):
        cur.execute("""SELECT MAX(high_price) AS hi,MIN(low_price) AS lo,COUNT(*) AS n,
                              COALESCE(SUM(gap_count),0) AS gaps
                       FROM market_realtime_5s_bars
                       WHERE stock_code=%s AND bucket_time>=%s AND bucket_time<%s""",(code,start,end))
        rr=cur.fetchone()
        if rr and rr["n"] and int(rr["gaps"] or 0)==0:
            hi=safe_num(rr["hi"]);lo=safe_num(rr["lo"])
            return ((hi/reference-1)*100 if hi else None,
                    (lo/reference-1)*100 if lo else None,
                    ["MFE_MAE_KIWOOM_0B_5S"])
    if not table_exists(cur,"market_minute_bars"):
        return None,None,["MFE_MAE_NO_BARS"]
    # Conservative fallback: only fully post-assessment 3-minute bars are used.
    cur.execute("""SELECT MAX(high_price) AS hi,MIN(low_price) AS lo,COUNT(*) AS n
                   FROM market_minute_bars
                   WHERE stock_code=%s AND interval_min=3
                     AND bar_time>=%s AND bar_time<%s""",(code,start,end))
    r=cur.fetchone()
    if not r or not r["n"]:
        return None,None,["MFE_MAE_NO_3M_BARS"]
    hi=safe_num(r["hi"]);lo=safe_num(r["lo"])
    mfe=(hi/reference-1)*100 if hi else None
    mae=(lo/reference-1)*100 if lo else None
    return mfe,mae,["MFE_MAE_KRX_3M_CONSERVATIVE"]


def _daily_close(cur,code,trade_date):
    cur.execute("""SELECT trade_date,close_price FROM market_daily_bars
                   WHERE stock_code=%s AND trade_date=%s
                   ORDER BY trade_date DESC LIMIT 1""",(code,trade_date))
    r=cur.fetchone()
    if not r:return None
    px=safe_num(r["close_price"])
    return (px,r["trade_date"]) if px and px>0 else None


def _next_daily_close(cur,code,trade_date,now_local):
    cur.execute("""SELECT trade_date,close_price FROM market_daily_bars
                   WHERE stock_code=%s AND trade_date>%s
                   ORDER BY trade_date ASC LIMIT 1""",(code,trade_date))
    r=cur.fetchone()
    if not r:return None
    d=r["trade_date"]
    if d==now_local.date() and now_local.time()<dtime(15,40):
        return None
    px=safe_num(r["close_price"])
    return (px,d) if px and px>0 else None


def _close_time_utc(day):
    return datetime.combine(day,dtime(15,30),tzinfo=KST).astimezone(timezone.utc)


def _resolve_one(cur,a,horizon,now):
    at=a["snapshot_time"];code=a["stock_code"];ref=safe_num(a["current_price_krw"])
    if not ref or ref<=0:return None
    now_local=now.astimezone(KST);local_day=at.astimezone(KST).date()
    flags=[]
    if horizon in ("5m","30m"):
        minutes=5 if horizon=="5m" else 30
        target=at+timedelta(minutes=minutes)
        if now<target+timedelta(seconds=30):return None
        rt=_realtime_target(cur,code,target)
        if rt:
            px,ot,source,q=rt;flags+=q
            resolved=(px,ot,source)
        else:
            resolved=_sor_target(cur,code,target)
            if not resolved:
                resolved=_minute_target(cur,code,target)
                if resolved:flags.append("OUTCOME_KRX_FALLBACK")
        if not resolved:return None
        px,ot,source=resolved
        mfe,mae,q=_mfe_mae(cur,code,at,ot,ref);flags+=q
    elif horizon=="close":
        close_utc=_close_time_utc(local_day)
        if now < close_utc+timedelta(minutes=10):return None
        d=_daily_close(cur,code,local_day)
        if not d:return None
        px,_=d;ot=close_utc;source="KRX_DAILY_CLOSE"
        mfe,mae,q=_mfe_mae(cur,code,at,close_utc,ref);flags+=q
    elif horizon=="D+1":
        d=_next_daily_close(cur,code,local_day,now_local)
        if not d:return None
        px,day=d;ot=_close_time_utc(day);source="KRX_NEXT_DAILY_CLOSE"
        if now<ot+timedelta(minutes=10):return None
        mfe,mae,q=_mfe_mae(cur,code,at,ot,ref);flags+=q
    else:
        return None
    ret=(px/ref-1)*100
    return (a["snapshot_time"],code,a["rule_version"],horizon,ref,px,ret,mfe,mae,ot,source,
            json.dumps(flags,ensure_ascii=False))


def resolve_outcomes(limit=240):
    now=datetime.now(timezone.utc)
    inserted=0
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT a.* FROM market_os_assessment_snapshots a
                       WHERE a.snapshot_time>now()-interval '14 days'
                       ORDER BY a.snapshot_time ASC LIMIT %s""",(limit,))
        assessments=cur.fetchall()
        for a in assessments:
            for horizon in ("5m","30m","close","D+1"):
                cur.execute("""SELECT 1 FROM market_os_assessment_outcomes
                               WHERE assessment_time=%s AND stock_code=%s
                                 AND rule_version=%s AND horizon=%s""",
                            (a["snapshot_time"],a["stock_code"],a["rule_version"],horizon))
                if cur.fetchone():continue
                out=_resolve_one(cur,a,horizon,now)
                if not out:continue
                cur.execute("""INSERT INTO market_os_assessment_outcomes(
                    assessment_time,stock_code,rule_version,horizon,reference_price_krw,
                    outcome_price_krw,return_pct,mfe_pct,mae_pct,outcome_time,outcome_source,quality_flags)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT DO NOTHING""",out)
                inserted+=cur.rowcount if cur.rowcount and cur.rowcount>0 else 0
    return inserted


def _bucket_setup(v):
    if v is None:return "UNKNOWN"
    v=int(v)
    if v>=80:return "80-100"
    if v>=65:return "65-79"
    if v>=50:return "50-64"
    return "0-49"


def _aggregate(values):
    vals=[x for x in values if x.get("return_pct") is not None]
    if not vals:return None
    rets=[float(x["return_pct"]) for x in vals]
    mfes=[float(x["mfe_pct"]) for x in vals if x.get("mfe_pct") is not None]
    maes=[float(x["mae_pct"]) for x in vals if x.get("mae_pct") is not None]
    stocks={x.get("stock_code") for x in vals if x.get("stock_code")}
    days={x.get("trade_day") for x in vals if x.get("trade_day")}
    return {
        "samples":len(rets),
        "distinct_stocks":len(stocks),
        "distinct_days":len(days),
        "avg_return_pct":sum(rets)/len(rets),
        "median_return_pct":statistics.median(rets),
        "positive_rate":sum(x>0 for x in rets)/len(rets),
        "avg_mfe_pct":sum(mfes)/len(mfes) if mfes else None,
        "avg_mae_pct":sum(maes)/len(maes) if maes else None
    }


def _walk_forward_windows(values,comparator=None):
    """Split a segment by complete trade days into early/recent halves.

    Day-level splitting prevents observations from the same trading day leaking
    across both halves. Comparator rows, when supplied, are restricted to the
    exact same day sets so interaction deltas remain time-aligned.
    """
    days=sorted({x.get("trade_day") for x in values if x.get("trade_day")})
    if len(days)<4:
        return []
    cut=len(days)//2
    early_days=set(days[:cut]);recent_days=set(days[cut:])
    out=[]
    for name,dayset in (("EARLY",early_days),("RECENT",recent_days)):
        child_vals=[x for x in values if x.get("trade_day") in dayset]
        child=_aggregate(child_vals)
        if not child:
            continue
        row={
            "window_name":name,
            "start_day":min(dayset),"end_day":max(dayset),
            **child,
            "comparator_samples":None,"comparator_stocks":None,"comparator_days":None,
            "comparator_avg_return_pct":None,"comparator_positive_rate":None,
            "comparator_avg_mae_pct":None,
            "delta_avg_return_pct":None,"delta_positive_rate_pp":None,"delta_mae_pct":None,
        }
        if comparator is not None:
            comp_vals=[x for x in comparator if x.get("trade_day") in dayset]
            comp=_aggregate(comp_vals)
            if comp:
                row.update({
                    "comparator_samples":comp["samples"],
                    "comparator_stocks":comp["distinct_stocks"],
                    "comparator_days":comp["distinct_days"],
                    "comparator_avg_return_pct":comp["avg_return_pct"],
                    "comparator_positive_rate":comp["positive_rate"],
                    "comparator_avg_mae_pct":comp["avg_mae_pct"],
                    "delta_avg_return_pct":child["avg_return_pct"]-comp["avg_return_pct"],
                    "delta_positive_rate_pp":(child["positive_rate"]-comp["positive_rate"])*100,
                    "delta_mae_pct":(
                        child["avg_mae_pct"]-comp["avg_mae_pct"]
                        if child["avg_mae_pct"] is not None and comp["avg_mae_pct"] is not None
                        else None
                    ),
                })
        out.append(row)
    return out


def _sample_basis(horizon):
    if horizon=="5m":return "NON_OVERLAP_5M"
    if horizon=="30m":return "NON_OVERLAP_30M"
    if horizon=="close":return "ONE_PER_STOCK_DAY_CLOSE"
    if horizon=="D+1":return "ONE_PER_STOCK_DAY_D1"
    return "UNKNOWN"


def _episode_anchors(rows):
    """Reduce repeated snapshots to horizon-aware non-overlapping anchors.

    Raw assessments remain stored for audit. Learning segments use these anchors
    so a stock that stays on screen for 20 minutes is not counted as 20
    independent observations.
    """
    ordered=sorted(rows,key=lambda r:(r["horizon"],r["stock_code"],r["snapshot_time"]))
    last_time={}
    last_day={}
    out=[]
    for r in ordered:
        horizon=r["horizon"];code=r["stock_code"];ts=r["snapshot_time"]
        day=ts.astimezone(KST).date().isoformat()
        r=dict(r);r["trade_day"]=day
        key=(horizon,code)
        if horizon in ("close","D+1"):
            if last_day.get(key)==day:
                continue
            last_day[key]=day;out.append(r);continue
        cooldown=300 if horizon=="5m" else 1800 if horizon=="30m" else 300
        prev=last_time.get(key)
        if prev is not None and (ts-prev).total_seconds()<cooldown:
            continue
        last_time[key]=ts;out.append(r)
    return out


def _bucket_strength(v):
    v=safe_num(v)
    if v is None:return "UNKNOWN"
    if v>=120:return "120+"
    if v>=100:return "100-119"
    if v>=80:return "80-99"
    return "<80"


def _bucket_buy_share(v):
    v=safe_num(v)
    if v is None:return "UNKNOWN"
    if v>=.65:return "65%+"
    if v>=.55:return "55-64%"
    if v>=.45:return "45-54%"
    return "<45%"


def _micro_state(strength,buy_share):
    """Pre-registered shadow heuristic; not a live trade signal."""
    s=safe_num(strength);b=safe_num(buy_share)
    if s is None or b is None:return "NO_DATA"
    if s>=120 and b>=.65:return "STRONG_CONFIRM"
    if s<80 and b<.45:return "WEAK_CONFIRM"
    if s>=100 and b>=.55:return "POSITIVE"
    if s<100 and b<.45:return "NEGATIVE"
    return "MIXED"


def _segment_depth(kind):
    return {
        "STANCE_TRIGGER":2,"TIER_SESSION":2,"STANCE_SETUP":2,"SETUP_TRIGGER":2,
        "STANCE_SETUP_TRIGGER":3,
        "STANCE_TRIGGER_MICRO":3,"SETUP_TRIGGER_MICRO":3,
        "STANCE_SETUP_TRIGGER_MICRO":4,
    }.get(kind,1)


def _parent_key(kind,value):
    p=value.split(" | ")
    try:
        if kind=="STANCE_TRIGGER":return ("STANCE",p[0])
        if kind=="TIER_SESSION":return ("TIER",p[0])
        if kind=="STANCE_SETUP":return ("STANCE",p[0])
        if kind=="SETUP_TRIGGER":return ("SETUP",p[0])
        if kind=="STANCE_SETUP_TRIGGER":return ("STANCE_TRIGGER",p[0]+" | "+p[2])
        if kind=="STANCE_TRIGGER_MICRO":return ("STANCE_TRIGGER",p[0]+" | "+p[1])
        if kind=="SETUP_TRIGGER_MICRO":return ("SETUP_TRIGGER",p[0]+" | "+p[1])
        if kind=="STANCE_SETUP_TRIGGER_MICRO":
            return ("STANCE_SETUP_TRIGGER",p[0]+" | "+p[1]+" | "+p[2])
    except IndexError:
        return None
    return None


def _learning_dims(r):
    """Return pre-registered single and interaction dimensions.

    Keeping the interaction list explicit prevents an uncontrolled combinatorial
    search over every possible feature combination.
    """
    tier=r["watch_tier"] or "UNKNOWN"
    stance=r["market_stance"] or "UNKNOWN"
    trigger=r["trigger_state"] or "UNKNOWN"
    session=r["session_bucket"] or "UNKNOWN"
    setup=_bucket_setup(r["setup_score"])
    dims={
        "TIER":tier,
        "STANCE":stance,
        "TRIGGER":trigger,
        "SESSION":session,
        "CATALYST":r["catalyst_grade"] or "UNKNOWN",
        "SETUP":setup,
        "STANCE_TRIGGER":stance+" | "+trigger,
        "TIER_SESSION":tier+" | "+session,
        "STANCE_SETUP":stance+" | "+setup,
        "SETUP_TRIGGER":setup+" | "+trigger,
        "STANCE_SETUP_TRIGGER":stance+" | "+setup+" | "+trigger,
    }
    clean_micro=int(r["micro_tick_count_15s"] or 0)>0 and int(r["micro_gap_count_15s"] or 0)==0
    if clean_micro:
        strength=_bucket_strength(r["micro_strength"])
        buy_share=_bucket_buy_share(r["micro_buy_share_15s"])
        micro=_micro_state(r["micro_strength"],r["micro_buy_share_15s"])
        dims["MICRO_STRENGTH"]=strength
        dims["MICRO_BUY_SHARE"]=buy_share
        dims["MICRO_STATE"]=micro
        dims["STANCE_TRIGGER_MICRO"]=stance+" | "+trigger+" | "+micro
        dims["SETUP_TRIGGER_MICRO"]=setup+" | "+trigger+" | "+micro
        dims["STANCE_SETUP_TRIGGER_MICRO"]=stance+" | "+setup+" | "+trigger+" | "+micro
    return dims


def refresh_segments():
    with db() as c,c.cursor() as cur:
        cur.execute("""SELECT a.snapshot_time,a.stock_code,
                              a.watch_tier,a.market_stance,a.trigger_state,a.session_bucket,
                              a.catalyst_grade,a.setup_score,a.micro_strength,a.micro_buy_share_15s,
                              a.micro_tick_count_15s,a.micro_gap_count_15s,
                              o.horizon,o.return_pct,o.mfe_pct,o.mae_pct
                       FROM market_os_assessment_outcomes o
                       JOIN market_os_assessment_snapshots a
                         ON a.snapshot_time=o.assessment_time AND a.stock_code=o.stock_code
                        AND a.rule_version=o.rule_version
                       WHERE a.rule_version=%s
                         AND a.snapshot_time>now()-interval '60 days'""",
                    (active_control_version(cur),))
        raw=cur.fetchall()
        rows=_episode_anchors(raw)
        groups=defaultdict(list)
        for r in rows:
            horizon=r["horizon"]
            dims=_learning_dims(r)
            for kind,value in dims.items():
                groups[(kind,value,horizon)].append(r)

        cur.execute("DELETE FROM market_os_learning_segments")
        segment_payload=[]
        for (kind,value,horizon),vals in groups.items():
            a=_aggregate(vals)
            if not a:continue
            segment_payload.append((kind,value,horizon,a["samples"],a["distinct_stocks"],a["distinct_days"],
                            _sample_basis(horizon),a["avg_return_pct"],a["median_return_pct"],
                            a["positive_rate"],a["avg_mfe_pct"],a["avg_mae_pct"]))
        cur.executemany("""INSERT INTO market_os_learning_segments(
              segment_type,segment_value,horizon,samples,distinct_stocks,distinct_days,sample_basis,
              avg_return_pct,median_return_pct,positive_rate,avg_mfe_pct,avg_mae_pct,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",segment_payload)

        # Compare each pre-registered interaction to the complement inside its
        # parent condition. Parent aggregate includes the child, so using the
        # complement avoids mechanically diluting the observed conditional gap.
        cur.execute("DELETE FROM market_os_interaction_edges")
        edge_payload=[]
        for (kind,value,horizon),child_vals in groups.items():
            if _segment_depth(kind)<2:continue
            parent=_parent_key(kind,value)
            if not parent:continue
            parent_vals=groups.get((parent[0],parent[1],horizon)) or []
            if kind.endswith("_MICRO"):
                parent_vals=[
                    r for r in parent_vals
                    if int(r["micro_tick_count_15s"] or 0)>0
                    and int(r["micro_gap_count_15s"] or 0)==0
                    and _micro_state(r["micro_strength"],r["micro_buy_share_15s"])!="NO_DATA"
                ]
            if not parent_vals:continue
            child_ids={(r["stock_code"],r["snapshot_time"]) for r in child_vals}
            comparator=[r for r in parent_vals if (r["stock_code"],r["snapshot_time"]) not in child_ids]
            child=_aggregate(child_vals);comp=_aggregate(comparator)
            if not child or not comp:continue
            d_avg=(child["avg_return_pct"]-comp["avg_return_pct"]
                   if child["avg_return_pct"] is not None and comp["avg_return_pct"] is not None else None)
            d_pos=((child["positive_rate"]-comp["positive_rate"])*100
                   if child["positive_rate"] is not None and comp["positive_rate"] is not None else None)
            d_mfe=(child["avg_mfe_pct"]-comp["avg_mfe_pct"]
                   if child["avg_mfe_pct"] is not None and comp["avg_mfe_pct"] is not None else None)
            d_mae=(child["avg_mae_pct"]-comp["avg_mae_pct"]
                   if child["avg_mae_pct"] is not None and comp["avg_mae_pct"] is not None else None)
            edge_payload.append((
                kind,value,horizon,parent[0],parent[1],_sample_basis(horizon),
                child["samples"],child["distinct_stocks"],child["distinct_days"],
                comp["samples"],comp["distinct_stocks"],comp["distinct_days"],
                child["avg_return_pct"],comp["avg_return_pct"],d_avg,
                child["positive_rate"],comp["positive_rate"],d_pos,
                child["avg_mfe_pct"],comp["avg_mfe_pct"],d_mfe,
                child["avg_mae_pct"],comp["avg_mae_pct"],d_mae
            ))
        cur.executemany("""INSERT INTO market_os_interaction_edges(
              segment_type,segment_value,horizon,parent_type,parent_value,sample_basis,
              child_samples,child_stocks,child_days,comparator_samples,comparator_stocks,comparator_days,
              child_avg_return_pct,comparator_avg_return_pct,delta_avg_return_pct,
              child_positive_rate,comparator_positive_rate,delta_positive_rate_pp,
              child_avg_mfe_pct,comparator_avg_mfe_pct,delta_mfe_pct,
              child_avg_mae_pct,comparator_avg_mae_pct,delta_mae_pct,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
              edge_payload)
        cur.execute("DELETE FROM market_os_walk_forward_windows")
        wf_payload=[]
        for (kind,value,horizon),child_vals in groups.items():
            comparator=None
            if _segment_depth(kind)>=2:
                parent=_parent_key(kind,value)
                parent_vals=groups.get((parent[0],parent[1],horizon)) if parent else None
                if parent_vals:
                    if kind.endswith("_MICRO"):
                        parent_vals=[
                            r for r in parent_vals
                            if int(r["micro_tick_count_15s"] or 0)>0
                            and int(r["micro_gap_count_15s"] or 0)==0
                            and _micro_state(r["micro_strength"],r["micro_buy_share_15s"])!="NO_DATA"
                        ]
                    child_ids={(r["stock_code"],r["snapshot_time"]) for r in child_vals}
                    comparator=[
                        r for r in parent_vals
                        if (r["stock_code"],r["snapshot_time"]) not in child_ids
                    ]
            for w in _walk_forward_windows(child_vals,comparator):
                wf_payload.append((
                    kind,value,horizon,w["window_name"],w["start_day"],w["end_day"],
                    w["samples"],w["distinct_stocks"],w["distinct_days"],
                    w["avg_return_pct"],w["median_return_pct"],w["positive_rate"],
                    w["avg_mfe_pct"],w["avg_mae_pct"],
                    w["comparator_samples"],w["comparator_stocks"],w["comparator_days"],
                    w["comparator_avg_return_pct"],w["comparator_positive_rate"],
                    w["comparator_avg_mae_pct"],w["delta_avg_return_pct"],
                    w["delta_positive_rate_pp"],w["delta_mae_pct"]
                ))
        cur.executemany("""INSERT INTO market_os_walk_forward_windows(
              segment_type,segment_value,horizon,window_name,start_day,end_day,
              samples,distinct_stocks,distinct_days,avg_return_pct,median_return_pct,positive_rate,
              avg_mfe_pct,avg_mae_pct,comparator_samples,comparator_stocks,comparator_days,
              comparator_avg_return_pct,comparator_positive_rate,comparator_avg_mae_pct,
              delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct,updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
              wf_payload)
        return len(segment_payload)




def _registry_key(rule_version,segment_type,segment_value,horizon):
    raw="|".join((rule_version or RULE_VERSION,segment_type or "",segment_value or "",horizon or ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def refresh_promotion_registry():
    """Persist current scientific lifecycle without ever enabling a shadow rule."""
    with db() as c,c.cursor() as cur:
        rule_version=active_control_version(cur)
        if not table_exists(cur,"market_os_learning_segments"):
            return {"active":0,"transitions":0,"promotion_candidates":0}

        cur.execute("""SELECT segment_type,segment_value,horizon,samples,distinct_stocks,distinct_days,
                              sample_basis,avg_return_pct,median_return_pct,positive_rate,
                              avg_mfe_pct,avg_mae_pct
                       FROM market_os_learning_segments
                       WHERE horizon IN ('30m','close','D+1')""")
        segments=[]
        for r in cur.fetchall():
            s=dict(r)
            s["quality"]=store_quality(
                s["samples"],s["distinct_stocks"],s["distinct_days"],
                store_segment_depth(s["segment_type"])
            )
            segments.append(s)

        edge_rows=[]
        if table_exists(cur,"market_os_interaction_edges"):
            cur.execute("""SELECT segment_type,segment_value,horizon,parent_type,parent_value,sample_basis,
                                  child_samples,child_stocks,child_days,
                                  comparator_samples,comparator_stocks,comparator_days,
                                  child_avg_return_pct,comparator_avg_return_pct,delta_avg_return_pct,
                                  child_positive_rate,comparator_positive_rate,delta_positive_rate_pp,
                                  child_avg_mfe_pct,comparator_avg_mfe_pct,delta_mfe_pct,
                                  child_avg_mae_pct,comparator_avg_mae_pct,delta_mae_pct
                           FROM market_os_interaction_edges
                           WHERE horizon IN ('30m','close','D+1')""")
            edge_rows=[dict(x) for x in cur.fetchall()]
        store_enrich_edges(segments,edge_rows)

        wf_rows=[]
        if table_exists(cur,"market_os_walk_forward_windows"):
            cur.execute("""SELECT segment_type,segment_value,horizon,window_name,start_day,end_day,
                                  samples,distinct_stocks,distinct_days,avg_return_pct,median_return_pct,
                                  positive_rate,avg_mfe_pct,avg_mae_pct,comparator_samples,
                                  comparator_stocks,comparator_days,comparator_avg_return_pct,
                                  comparator_positive_rate,comparator_avg_mae_pct,delta_avg_return_pct,
                                  delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_walk_forward_windows
                           WHERE horizon IN ('30m','close','D+1')""")
            wf_rows=[dict(x) for x in cur.fetchall()]
        validations=store_validation_candidates(segments,wf_rows)
        validation_idx={(x["segment_type"],x["segment_value"],x["horizon"]):x for x in validations}

        cur.execute("""UPDATE market_os_promotion_registry
                       SET active=FALSE
                       WHERE rule_version=%s""",(rule_version,))

        transitions=0
        promotion_candidates=0
        for s in segments:
            key_tuple=(s["segment_type"],s["segment_value"],s["horizon"])
            validation=validation_idx.get(key_tuple)
            lifecycle=_promotion_stage(s,validation)
            if not lifecycle:
                continue
            candidate_key=_registry_key(rule_version,*key_tuple)
            cur.execute("""SELECT current_stage,direction,review_action,manual_review_state
                           FROM market_os_promotion_registry
                           WHERE candidate_key=%s""",(candidate_key,))
            old=cur.fetchone()
            old_stage=old["current_stage"] if old else None
            effective_stage="SHADOW_RULE" if old_stage=="SHADOW_RULE" else lifecycle["stage"]
            if effective_stage=="PROMOTION_CANDIDATE":
                promotion_candidates+=1

            wf=(validation or {}).get("walk_forward") or {}
            early=wf.get("early") or {};recent=wf.get("recent") or {}
            reason_codes=list(lifecycle.get("reason_codes") or [])
            if old_stage=="SHADOW_RULE":
                reason_codes.append("MANUAL_SHADOW_RULE_PRESERVED")

            evidence={
                "validation_status":(validation or {}).get("status"),
                "validation_readiness":(validation or {}).get("readiness"),
                "walk_forward_status":wf.get("status"),
                "walk_forward_retention_ratio":wf.get("retention_ratio"),
                "cumulative":{
                    "samples":s.get("samples"),"distinct_stocks":s.get("distinct_stocks"),
                    "distinct_days":s.get("distinct_days"),"quality":s.get("quality"),
                    "avg_return_pct":s.get("avg_return_pct"),
                    "median_return_pct":s.get("median_return_pct"),
                    "positive_rate":s.get("positive_rate"),
                    "edge_avg_return_pct":s.get("edge_avg_return_pct"),
                    "edge_positive_rate_pp":s.get("edge_positive_rate_pp"),
                    "edge_mae_pct":s.get("edge_mae_pct"),
                },
                "early":{
                    "start_day":early.get("start_day"),"end_day":early.get("end_day"),
                    "samples":early.get("samples"),"avg_return_pct":early.get("avg_return_pct"),
                },
                "recent":{
                    "start_day":recent.get("start_day"),"end_day":recent.get("end_day"),
                    "samples":recent.get("samples"),"avg_return_pct":recent.get("avg_return_pct"),
                },
            }
            evidence_json=json.dumps(evidence,ensure_ascii=False,default=str)
            reasons_json=json.dumps(reason_codes,ensure_ascii=False)

            stage_changed=bool(old and old_stage!=effective_stage)
            direction_changed=bool(old and old["direction"]!=lifecycle["direction"])
            action_changed=bool(old and old["review_action"]!=lifecycle["review_action"])
            event_type="DISCOVERED" if old is None else "STAGE_CHANGED" if stage_changed else "EVIDENCE_CHANGED"
            log_event=old is None or stage_changed or direction_changed or action_changed

            cur.execute("""INSERT INTO market_os_promotion_registry(
                    candidate_key,rule_version,segment_type,segment_value,horizon,interaction_depth,
                    current_stage,direction,review_action,active,samples,distinct_stocks,distinct_days,
                    quality,walk_forward_status,avg_return_pct,median_return_pct,positive_rate,
                    edge_avg_return_pct,edge_positive_rate_pp,edge_mae_pct,
                    early_avg_return_pct,recent_avg_return_pct,reason_codes,evidence)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                ON CONFLICT(candidate_key) DO UPDATE SET
                    segment_type=excluded.segment_type,segment_value=excluded.segment_value,
                    horizon=excluded.horizon,interaction_depth=excluded.interaction_depth,
                    current_stage=CASE
                        WHEN market_os_promotion_registry.current_stage='SHADOW_RULE'
                        THEN 'SHADOW_RULE' ELSE excluded.current_stage END,
                    direction=excluded.direction,review_action=excluded.review_action,
                    active=TRUE,last_seen_at=now(),
                    stage_since=CASE
                        WHEN market_os_promotion_registry.current_stage=
                             CASE WHEN market_os_promotion_registry.current_stage='SHADOW_RULE'
                                  THEN 'SHADOW_RULE' ELSE excluded.current_stage END
                        THEN market_os_promotion_registry.stage_since ELSE now() END,
                    last_transition_at=CASE
                        WHEN market_os_promotion_registry.current_stage=
                             CASE WHEN market_os_promotion_registry.current_stage='SHADOW_RULE'
                                  THEN 'SHADOW_RULE' ELSE excluded.current_stage END
                        THEN market_os_promotion_registry.last_transition_at ELSE now() END,
                    samples=excluded.samples,distinct_stocks=excluded.distinct_stocks,
                    distinct_days=excluded.distinct_days,quality=excluded.quality,
                    walk_forward_status=excluded.walk_forward_status,
                    avg_return_pct=excluded.avg_return_pct,
                    median_return_pct=excluded.median_return_pct,
                    positive_rate=excluded.positive_rate,
                    edge_avg_return_pct=excluded.edge_avg_return_pct,
                    edge_positive_rate_pp=excluded.edge_positive_rate_pp,
                    edge_mae_pct=excluded.edge_mae_pct,
                    early_avg_return_pct=excluded.early_avg_return_pct,
                    recent_avg_return_pct=excluded.recent_avg_return_pct,
                    reason_codes=excluded.reason_codes,evidence=excluded.evidence""",
                (candidate_key,rule_version,s["segment_type"],s["segment_value"],s["horizon"],
                 s.get("interaction_depth",store_segment_depth(s["segment_type"])),
                 effective_stage,lifecycle["direction"],lifecycle["review_action"],
                 s["samples"],s["distinct_stocks"],s["distinct_days"],s["quality"],
                 wf.get("status"),s.get("avg_return_pct"),s.get("median_return_pct"),
                 s.get("positive_rate"),s.get("edge_avg_return_pct"),
                 s.get("edge_positive_rate_pp"),s.get("edge_mae_pct"),
                 early.get("avg_return_pct"),recent.get("avg_return_pct"),
                 reasons_json,evidence_json))

            if log_event:
                cur.execute("""INSERT INTO market_os_promotion_events(
                        candidate_key,event_type,from_stage,to_stage,direction,review_action,
                        reason_codes,evidence)
                    VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                    (candidate_key,event_type,old_stage,effective_stage,lifecycle["direction"],
                     lifecycle["review_action"],reasons_json,evidence_json))
                transitions+=1

        cur.execute("""SELECT COUNT(*) AS n FROM market_os_promotion_registry
                       WHERE rule_version=%s AND active=TRUE""",(rule_version,))
        active=int(cur.fetchone()["n"])
        return {
            "active":active,
            "transitions":transitions,
            "promotion_candidates":promotion_candidates,
        }


def capture_shadow_observations(limit_per_rule=800):
    """Freeze CONTROL and CHALLENGER decisions prospectively after manual approval."""
    if not SHADOW_LAB_ENABLED:
        return 0
    inserted=0
    with db() as c,c.cursor() as cur:
        if not table_exists(cur,"market_os_shadow_rules"):
            return 0
        cur.execute("""SELECT shadow_rule_id,candidate_key,rule_version,segment_type,segment_value,
                              source_horizon,action,approved_at,spec
                       FROM market_os_shadow_rules
                       WHERE enabled=TRUE
                       ORDER BY approved_at""")
        rules=cur.fetchall()
        for rule in rules:
            cur.execute("""SELECT a.*
                           FROM market_os_assessment_snapshots a
                           WHERE a.rule_version=%s
                             AND a.snapshot_time>=%s
                             AND NOT EXISTS(
                                 SELECT 1 FROM market_os_shadow_observations o
                                 WHERE o.assessment_time=a.snapshot_time
                                   AND o.stock_code=a.stock_code
                                   AND o.rule_version=a.rule_version
                                   AND o.shadow_rule_id=%s
                             )
                           ORDER BY a.snapshot_time,a.stock_code
                           LIMIT %s""",
                        (rule["rule_version"],rule["approved_at"],rule["shadow_rule_id"],limit_per_rule))
            rows=[]
            for a in cur.fetchall():
                result=shadow_evaluate(dict(a),dict(rule))
                rows.append((
                    a["snapshot_time"],a["stock_code"],a["rule_version"],rule["shadow_rule_id"],
                    result["matched"],result["changed"],result["control_tier"],
                    result["challenger_tier"],result["action"]
                ))
            if rows:
                cur.executemany("""INSERT INTO market_os_shadow_observations(
                        assessment_time,stock_code,rule_version,shadow_rule_id,matched,changed,
                        control_tier,challenger_tier,action)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""",rows)
                inserted+=cur.rowcount if cur.rowcount is not None and cur.rowcount>=0 else len(rows)
                cur.execute("""UPDATE market_os_shadow_rules
                               SET last_evaluated_at=now()
                               WHERE shadow_rule_id=%s""",(rule["shadow_rule_id"],))
    return inserted


def _shadow_evidence_state(summary):
    changes=int(summary.get("membership_changes") or 0)
    c=summary.get("control") or {};h=summary.get("challenger") or {}
    n=min(int(c.get("samples") or 0),int(h.get("samples") or 0))
    days=min(int(c.get("distinct_days") or 0),int(h.get("distinct_days") or 0))
    stocks=min(int(c.get("distinct_stocks") or 0),int(h.get("distinct_stocks") or 0))
    if changes==0:
        return "NO_DIFFERENCE"
    if n<10 or days<2 or stocks<3:
        return "COLLECTING"
    if n<30 or days<3 or changes<5:
        return "FORMING"
    return "COMPARABLE"


def refresh_shadow_summaries():
    """Recompute prospective A/B summaries from frozen observations and resolved outcomes."""
    if not SHADOW_LAB_ENABLED:
        return 0
    written=0
    with db() as c,c.cursor() as cur:
        if not table_exists(cur,"market_os_shadow_rules"):
            return 0
        cur.execute("""SELECT shadow_rule_id,rule_version,approved_at,
                              segment_type,segment_value,source_horizon,action
                       FROM market_os_shadow_rules
                       ORDER BY approved_at""")
        rules=cur.fetchall()
        for rule in rules:
            cur.execute("""SELECT o.assessment_time,o.stock_code,o.control_tier,o.challenger_tier,
                                  a.market_stance,
                                  y.horizon,y.return_pct,y.mfe_pct,y.mae_pct
                           FROM market_os_shadow_observations o
                           JOIN market_os_assessment_outcomes y
                             ON y.assessment_time=o.assessment_time
                            AND y.stock_code=o.stock_code
                            AND y.rule_version=o.rule_version
                           JOIN market_os_assessment_snapshots a
                             ON a.snapshot_time=o.assessment_time
                            AND a.stock_code=o.stock_code
                            AND a.rule_version=o.rule_version
                           WHERE o.shadow_rule_id=%s
                             AND y.horizon IN ('5m','30m','close','D+1')
                           ORDER BY y.horizon,o.stock_code,o.assessment_time""",
                        (rule["shadow_rule_id"],))
            raw=[]
            for r in cur.fetchall():
                x=dict(r)
                x["snapshot_time"]=r["assessment_time"]
                x["trade_day"]=r["assessment_time"].astimezone(KST).date().isoformat()
                raw.append(x)
            anchors=_episode_anchors(raw)
            summaries=shadow_experiment_summaries(anchors)
            slices=shadow_experiment_slices(anchors)
            decision=shadow_decision(dict(rule),summaries,slices)
            cur.execute("""DELETE FROM market_os_shadow_experiment_summary
                           WHERE shadow_rule_id=%s""",(rule["shadow_rule_id"],))
            for s in summaries:
                control=s["control"];challenger=s["challenger"]
                state=_shadow_evidence_state(s)
                cur.execute("""INSERT INTO market_os_shadow_experiment_summary(
                        shadow_rule_id,horizon,cohort,evidence_state,membership_changes,
                        control_samples,control_stocks,control_days,control_avg_return_pct,
                        control_median_return_pct,control_positive_rate,control_avg_mfe_pct,control_avg_mae_pct,
                        challenger_samples,challenger_stocks,challenger_days,challenger_avg_return_pct,
                        challenger_median_return_pct,challenger_positive_rate,challenger_avg_mfe_pct,
                        challenger_avg_mae_pct,delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                    (rule["shadow_rule_id"],s["horizon"],s["cohort"],state,s["membership_changes"],
                     control["samples"],control["distinct_stocks"],control["distinct_days"],
                     control["avg_return_pct"],control["median_return_pct"],control["positive_rate"],
                     control["avg_mfe_pct"],control["avg_mae_pct"],
                     challenger["samples"],challenger["distinct_stocks"],challenger["distinct_days"],
                     challenger["avg_return_pct"],challenger["median_return_pct"],challenger["positive_rate"],
                     challenger["avg_mfe_pct"],challenger["avg_mae_pct"],
                     s["delta_avg_return_pct"],s["delta_positive_rate_pp"],s["delta_mae_pct"]))
                written+=1

            cur.execute("""SELECT decision_state FROM market_os_shadow_decisions
                           WHERE shadow_rule_id=%s""",(rule["shadow_rule_id"],))
            old=cur.fetchone()
            old_state=old["decision_state"] if old else None
            reasons_json=json.dumps(decision.get("reason_codes") or [],ensure_ascii=False)
            evidence_json=json.dumps(decision.get("evidence") or {},ensure_ascii=False,default=str)
            primary=(decision.get("evidence") or {}).get("primary_cohort")
            cur.execute("""INSERT INTO market_os_shadow_decisions(
                    shadow_rule_id,decision_state,review_eligible,primary_cohort,
                    reason_codes,evidence,manual_decision_state,state_since,updated_at)
                VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb,'PENDING',now(),now())
                ON CONFLICT(shadow_rule_id) DO UPDATE SET
                    decision_state=excluded.decision_state,
                    review_eligible=excluded.review_eligible,
                    primary_cohort=excluded.primary_cohort,
                    reason_codes=excluded.reason_codes,
                    evidence=excluded.evidence,
                    state_since=CASE
                        WHEN market_os_shadow_decisions.decision_state=excluded.decision_state
                        THEN market_os_shadow_decisions.state_since ELSE now() END,
                    updated_at=now()""",
                (rule["shadow_rule_id"],decision["state"],bool(decision.get("review_eligible")),
                 primary,reasons_json,evidence_json))
            if old_state!=decision["state"]:
                cur.execute("""INSERT INTO market_os_shadow_decision_events(
                        shadow_rule_id,from_state,to_state,review_eligible,reason_codes,evidence)
                    VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                    (rule["shadow_rule_id"],old_state,decision["state"],
                     bool(decision.get("review_eligible")),reasons_json,evidence_json))
    return written


def refresh_adoption_dossiers():
    """Freeze immutable review revisions for currently accepted shadow candidates."""
    if not SHADOW_LAB_ENABLED:
        return {"generated":0,"staled":0}
    generated=0;staled=0
    with db() as c,c.cursor() as cur:
        required=(
            "market_os_shadow_decisions","market_os_shadow_rules",
            "market_os_promotion_registry","market_os_adoption_dossiers"
        )
        if any(not table_exists(cur,x) for x in required):
            return {"generated":0,"staled":0}

        cur.execute("""SELECT d.shadow_rule_id,d.decision_state,d.review_eligible,
                              d.primary_cohort,d.reason_codes,d.evidence,d.updated_at AS decision_updated_at,
                              de.event_id AS source_decision_event_id,de.event_time AS accept_event_time,
                              r.candidate_key,r.rule_version,r.segment_type,r.segment_value,
                              r.source_horizon,r.action,r.approved_at,
                              p.direction,p.review_action,p.quality,p.walk_forward_status,
                              p.samples,p.distinct_stocks,p.distinct_days,p.avg_return_pct,
                              p.early_avg_return_pct,p.recent_avg_return_pct
                       FROM market_os_shadow_decisions d
                       JOIN market_os_shadow_rules r ON r.shadow_rule_id=d.shadow_rule_id
                       JOIN LATERAL (
                           SELECT event_id,event_time
                           FROM market_os_shadow_decision_events e
                           WHERE e.shadow_rule_id=d.shadow_rule_id
                             AND e.to_state='ACCEPT_CANDIDATE'
                           ORDER BY event_time DESC,event_id DESC LIMIT 1
                       ) de ON TRUE
                       LEFT JOIN market_os_promotion_registry p ON p.candidate_key=r.candidate_key
                       WHERE d.decision_state='ACCEPT_CANDIDATE'
                         AND d.review_eligible=TRUE
                       ORDER BY de.event_time,d.shadow_rule_id""")
        accepted=cur.fetchall()
        accepted_ids={r["shadow_rule_id"] for r in accepted}

        # A pending dossier cannot remain actionable after the decision falls
        # below ACCEPT_CANDIDATE. Historical approved/rejected reviews stay intact.
        cur.execute("""SELECT dossier_id,shadow_rule_id,review_state
                       FROM market_os_adoption_dossiers
                       WHERE review_state='PENDING'""")
        for d in cur.fetchall():
            if d["shadow_rule_id"] in accepted_ids:
                continue
            cur.execute("""UPDATE market_os_adoption_dossiers
                           SET review_state='STALE_DECISION'
                           WHERE dossier_id=%s AND review_state='PENDING'""",(d["dossier_id"],))
            if cur.rowcount:
                cur.execute("""INSERT INTO market_os_adoption_dossier_events(
                        dossier_id,event_type,from_review_state,to_review_state,note,evidence)
                    VALUES(%s,'DECISION_STALE','PENDING','STALE_DECISION',
                           'Shadow Decision no longer ACCEPT_CANDIDATE','{}'::jsonb)""",
                    (d["dossier_id"],))
                staled+=1

        for row in accepted:
            rule=dict(row)
            decision={
                "decision_state":row["decision_state"],
                "review_eligible":row["review_eligible"],
                "primary_cohort":row["primary_cohort"],
                "reason_codes":row["reason_codes"] or [],
                "evidence":row["evidence"] or {},
            }
            promotion={
                "direction":row["direction"],"review_action":row["review_action"],
                "quality":row["quality"],"walk_forward_status":row["walk_forward_status"],
                "samples":row["samples"],"distinct_stocks":row["distinct_stocks"],
                "distinct_days":row["distinct_days"],"avg_return_pct":row["avg_return_pct"],
                "early_avg_return_pct":row["early_avg_return_pct"],
                "recent_avg_return_pct":row["recent_avg_return_pct"],
            }

            cur.execute("""SELECT horizon,cohort,evidence_state,membership_changes,
                                  control_samples,challenger_samples,
                                  control_avg_return_pct,challenger_avg_return_pct,
                                  delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_shadow_experiment_summary
                           WHERE shadow_rule_id=%s
                           ORDER BY CASE horizon WHEN '30m' THEN 1 WHEN 'close' THEN 2
                                    WHEN 'D+1' THEN 3 ELSE 4 END,cohort""",
                        (row["shadow_rule_id"],))
            summaries=[dict(x) for x in cur.fetchall()]

            cur.execute("""SELECT o.assessment_time,o.stock_code,a.stock_name,a.market_stance,
                                  o.control_tier,o.challenger_tier,
                                  MAX(y.return_pct) FILTER(WHERE y.horizon='30m') AS return_30m_pct,
                                  MAX(y.return_pct) FILTER(WHERE y.horizon='close') AS return_close_pct,
                                  MAX(y.return_pct) FILTER(WHERE y.horizon='D+1') AS return_d1_pct
                           FROM market_os_shadow_observations o
                           JOIN market_os_assessment_snapshots a
                             ON a.snapshot_time=o.assessment_time
                            AND a.stock_code=o.stock_code
                            AND a.rule_version=o.rule_version
                           LEFT JOIN market_os_assessment_outcomes y
                             ON y.assessment_time=o.assessment_time
                            AND y.stock_code=o.stock_code
                            AND y.rule_version=o.rule_version
                           WHERE o.shadow_rule_id=%s AND o.changed=TRUE
                           GROUP BY o.assessment_time,o.stock_code,a.stock_name,a.market_stance,
                                    o.control_tier,o.challenger_tier
                           ORDER BY o.assessment_time DESC
                           LIMIT 500""",(row["shadow_rule_id"],))
            cases=[]
            for x in cur.fetchall():
                v=dict(x)
                v["assessment_time"]=x["assessment_time"].isoformat() if x["assessment_time"] else None
                cases.append(v)

            dossier=build_adoption_dossier(rule,decision,promotion,summaries,cases)
            h=adoption_dossier_hash(dossier)
            cur.execute("""SELECT dossier_id,revision,review_state
                           FROM market_os_adoption_dossiers
                           WHERE shadow_rule_id=%s AND source_decision_event_id=%s""",
                        (row["shadow_rule_id"],row["source_decision_event_id"]))
            if cur.fetchone():
                continue

            cur.execute("""SELECT dossier_id,revision,review_state
                           FROM market_os_adoption_dossiers
                           WHERE shadow_rule_id=%s
                           ORDER BY revision DESC LIMIT 1""",(row["shadow_rule_id"],))
            prev=cur.fetchone()
            revision=(int(prev["revision"])+1) if prev else 1
            if prev and prev["review_state"]=="PENDING":
                cur.execute("""UPDATE market_os_adoption_dossiers
                               SET review_state='SUPERSEDED'
                               WHERE dossier_id=%s AND review_state='PENDING'""",(prev["dossier_id"],))
                if cur.rowcount:
                    cur.execute("""INSERT INTO market_os_adoption_dossier_events(
                            dossier_id,event_type,from_review_state,to_review_state,note,evidence)
                        VALUES(%s,'SUPERSEDED_BY_NEW_EVIDENCE','PENDING','SUPERSEDED',
                               'A newer evidence revision was generated',%s::jsonb)""",
                        (prev["dossier_id"],json.dumps({"next_revision":revision},ensure_ascii=False)))

            dossier_id=f"ad-{h[:20]}-r{revision:03d}"
            cur.execute("""INSERT INTO market_os_adoption_dossiers(
                    dossier_id,shadow_rule_id,revision,content_hash,decision_state,
                    decision_updated_at,source_decision_event_id,review_state,dossier)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'PENDING',%s::jsonb)""",
                (dossier_id,row["shadow_rule_id"],revision,h,row["decision_state"],
                 row["decision_updated_at"],row["source_decision_event_id"],
                 json.dumps(dossier,ensure_ascii=False,default=str)))
            cur.execute("""INSERT INTO market_os_adoption_dossier_events(
                    dossier_id,event_type,from_review_state,to_review_state,note,evidence)
                VALUES(%s,'GENERATED',NULL,'PENDING',
                       'Immutable adoption review revision generated',%s::jsonb)""",
                (dossier_id,json.dumps({
                    "shadow_rule_id":row["shadow_rule_id"],
                    "revision":revision,"content_hash":h,
                    "source_decision_event_id":row["source_decision_event_id"],
                },ensure_ascii=False)))
            generated+=1
    return {"generated":generated,"staled":staled}


def capture_ruleset_dry_run_observations(limit_per_ruleset=800):
    """Evaluate active versioned candidate rulesets prospectively beside CONTROL."""
    if not RULESET_DRY_RUN_ENABLED:
        return {"inserted":0,"staled":0}
    inserted=0;staled=0
    with db() as c,c.cursor() as cur:
        if not table_exists(cur,"market_os_versioned_rulesets"):
            return {"inserted":0,"staled":0}
        cur.execute("""SELECT vr.ruleset_id,vr.base_rule_version,vr.source_dossier_id,
                              vr.source_shadow_rule_id,vr.status,vr.spec,vr.activated_at,
                              d.decision_state,d.review_eligible,
                              sr.enabled AS shadow_rule_enabled
                       FROM market_os_versioned_rulesets vr
                       LEFT JOIN market_os_shadow_decisions d
                         ON d.shadow_rule_id=vr.source_shadow_rule_id
                       LEFT JOIN market_os_shadow_rules sr
                         ON sr.shadow_rule_id=vr.source_shadow_rule_id
                       WHERE vr.status='DRY_RUN_ACTIVE'
                       ORDER BY vr.activated_at""")
        rulesets=cur.fetchall()
        for rs in rulesets:
            source_ok=bool(
                rs["decision_state"]=="ACCEPT_CANDIDATE"
                and rs["review_eligible"]
                and rs["shadow_rule_enabled"]
            )
            if not source_ok:
                cur.execute("""UPDATE market_os_versioned_rulesets
                               SET status='STALE_SOURCE',stale_at=now(),
                                   note='Source Shadow Decision or rule no longer eligible'
                               WHERE ruleset_id=%s AND status='DRY_RUN_ACTIVE'""",
                            (rs["ruleset_id"],))
                if cur.rowcount:
                    cur.execute("""INSERT INTO market_os_ruleset_events(
                            ruleset_id,event_type,from_status,to_status,evidence)
                        VALUES(%s,'SOURCE_STALE','DRY_RUN_ACTIVE','STALE_SOURCE',%s::jsonb)""",
                        (rs["ruleset_id"],json.dumps({
                            "decision_state":rs["decision_state"],
                            "review_eligible":bool(rs["review_eligible"]),
                            "shadow_rule_enabled":bool(rs["shadow_rule_enabled"]),
                        },ensure_ascii=False)))
                    cur.execute("""UPDATE market_os_shadow_decisions
                                   SET manual_decision_state='DRY_RUN_STALE_SOURCE'
                                   WHERE shadow_rule_id=%s""",(rs["source_shadow_rule_id"],))
                    staled+=1
                continue

            cur.execute("""SELECT a.*
                           FROM market_os_assessment_snapshots a
                           WHERE a.rule_version=%s
                             AND a.snapshot_time>=%s
                             AND NOT EXISTS(
                                 SELECT 1 FROM market_os_ruleset_dry_run_observations o
                                 WHERE o.assessment_time=a.snapshot_time
                                   AND o.stock_code=a.stock_code
                                   AND o.control_rule_version=a.rule_version
                                   AND o.ruleset_id=%s
                             )
                           ORDER BY a.snapshot_time,a.stock_code
                           LIMIT %s""",
                        (rs["base_rule_version"],rs["activated_at"],rs["ruleset_id"],limit_per_ruleset))
            rows=[]
            for a in cur.fetchall():
                result=ruleset_evaluate(dict(a),rs["spec"] or {})
                rows.append((
                    a["snapshot_time"],a["stock_code"],a["rule_version"],rs["ruleset_id"],
                    result["control_tier"],result["candidate_tier"],result["changed"],
                    json.dumps(result["matched_overlays"],ensure_ascii=False)
                ))
            if rows:
                cur.executemany("""INSERT INTO market_os_ruleset_dry_run_observations(
                        assessment_time,stock_code,control_rule_version,ruleset_id,
                        control_tier,candidate_tier,changed,matched_overlays)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT DO NOTHING""",rows)
                inserted+=cur.rowcount if cur.rowcount is not None and cur.rowcount>=0 else len(rows)
                cur.execute("""UPDATE market_os_versioned_rulesets
                               SET last_evaluated_at=now()
                               WHERE ruleset_id=%s""",(rs["ruleset_id"],))
    return {"inserted":inserted,"staled":staled}


def refresh_ruleset_dry_run_summaries():
    """Summarize versioned CONTROL vs CANDIDATE on resolved prospective outcomes."""
    if not RULESET_DRY_RUN_ENABLED:
        return 0
    written=0
    with db() as c,c.cursor() as cur:
        if not table_exists(cur,"market_os_versioned_rulesets"):
            return 0
        cur.execute("""SELECT vr.ruleset_id,vr.base_rule_version,vr.source_shadow_rule_id,
                              vr.status,vr.spec,vr.activated_at,
                              ad.dossier AS source_dossier
                       FROM market_os_versioned_rulesets vr
                       LEFT JOIN market_os_adoption_dossiers ad
                         ON ad.dossier_id=vr.source_dossier_id
                       ORDER BY vr.activated_at""")
        for rs in cur.fetchall():
            cur.execute("""SELECT o.assessment_time,o.stock_code,
                                  o.control_tier,o.candidate_tier,a.market_stance,
                                  y.horizon,y.return_pct,y.mfe_pct,y.mae_pct
                           FROM market_os_ruleset_dry_run_observations o
                           JOIN market_os_assessment_outcomes y
                             ON y.assessment_time=o.assessment_time
                            AND y.stock_code=o.stock_code
                            AND y.rule_version=o.control_rule_version
                           JOIN market_os_assessment_snapshots a
                             ON a.snapshot_time=o.assessment_time
                            AND a.stock_code=o.stock_code
                            AND a.rule_version=o.control_rule_version
                           WHERE o.ruleset_id=%s
                             AND y.horizon IN ('5m','30m','close','D+1')
                           ORDER BY y.horizon,o.stock_code,o.assessment_time""",
                        (rs["ruleset_id"],))
            raw=[]
            for r in cur.fetchall():
                x=dict(r)
                x["snapshot_time"]=r["assessment_time"]
                x["trade_day"]=r["assessment_time"].astimezone(KST).date().isoformat()
                raw.append(x)
            anchors=_episode_anchors(raw)
            summaries=ruleset_dry_run_summaries(anchors)
            slices=ruleset_dry_run_slices(anchors)
            concentration={
                "REVIEW":ruleset_impact_concentration(anchors,"REVIEW"),
                "FOCUS":ruleset_impact_concentration(anchors,"FOCUS"),
            }
            # Effect retention must compare against the evidence frozen at
            # dossier review time, never against a moving Shadow summary.
            shadow_reference=list(
                ((rs["source_dossier"] or {}).get("control_vs_challenger") or [])
            )
            succession=ruleset_succession_decision(
                {"spec":rs["spec"] or {}},summaries,slices,concentration,shadow_reference
            )
            if rs["status"]=="STALE_SOURCE":
                succession={
                    "state":"RULESET_MORE_DATA","review_eligible":False,
                    "reason_codes":["SOURCE_STALE"],
                    "evidence":{**(succession.get("evidence") or {}),"ruleset_status":"STALE_SOURCE"},
                }
            cur.execute("""DELETE FROM market_os_ruleset_dry_run_summary
                           WHERE ruleset_id=%s""",(rs["ruleset_id"],))
            for s in summaries:
                control=s["control"];candidate=s["challenger"]
                state=_shadow_evidence_state(s)
                cur.execute("""INSERT INTO market_os_ruleset_dry_run_summary(
                        ruleset_id,horizon,cohort,evidence_state,membership_changes,
                        control_samples,control_stocks,control_days,control_avg_return_pct,
                        control_median_return_pct,control_positive_rate,control_avg_mfe_pct,control_avg_mae_pct,
                        candidate_samples,candidate_stocks,candidate_days,candidate_avg_return_pct,
                        candidate_median_return_pct,candidate_positive_rate,candidate_avg_mfe_pct,
                        candidate_avg_mae_pct,delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                    (rs["ruleset_id"],s["horizon"],s["cohort"],state,s["membership_changes"],
                     control["samples"],control["distinct_stocks"],control["distinct_days"],
                     control["avg_return_pct"],control["median_return_pct"],control["positive_rate"],
                     control["avg_mfe_pct"],control["avg_mae_pct"],
                     candidate["samples"],candidate["distinct_stocks"],candidate["distinct_days"],
                     candidate["avg_return_pct"],candidate["median_return_pct"],candidate["positive_rate"],
                     candidate["avg_mfe_pct"],candidate["avg_mae_pct"],
                     s["delta_avg_return_pct"],s["delta_positive_rate_pp"],s["delta_mae_pct"]))
                written+=1

            cur.execute("""SELECT decision_state
                           FROM market_os_ruleset_succession_decisions
                           WHERE ruleset_id=%s""",(rs["ruleset_id"],))
            old=cur.fetchone()
            old_state=old["decision_state"] if old else None
            reasons_json=json.dumps(succession.get("reason_codes") or [],ensure_ascii=False)
            evidence_json=json.dumps(succession.get("evidence") or {},ensure_ascii=False,default=str)
            primary=(succession.get("evidence") or {}).get("primary_cohort")
            cur.execute("""INSERT INTO market_os_ruleset_succession_decisions(
                    ruleset_id,decision_state,review_eligible,primary_cohort,
                    reason_codes,evidence,manual_review_state,state_since,updated_at)
                VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb,'PENDING',now(),now())
                ON CONFLICT(ruleset_id) DO UPDATE SET
                    decision_state=excluded.decision_state,
                    review_eligible=excluded.review_eligible,
                    primary_cohort=excluded.primary_cohort,
                    reason_codes=excluded.reason_codes,
                    evidence=excluded.evidence,
                    state_since=CASE
                        WHEN market_os_ruleset_succession_decisions.decision_state=excluded.decision_state
                        THEN market_os_ruleset_succession_decisions.state_since ELSE now() END,
                    updated_at=now()""",
                (rs["ruleset_id"],succession["state"],bool(succession.get("review_eligible")),
                 primary,reasons_json,evidence_json))
            if old_state!=succession["state"]:
                cur.execute("""INSERT INTO market_os_ruleset_succession_events(
                        ruleset_id,from_state,to_state,review_eligible,reason_codes,evidence)
                    VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                    (rs["ruleset_id"],old_state,succession["state"],
                     bool(succession.get("review_eligible")),reasons_json,evidence_json))
    return written


def capture_canary_observations(limit_per_release=800):
    """Evaluate deterministic stock-day canary samples without replacing CONTROL."""
    if not CANARY_ENABLED:
        return {"inserted":0,"staled":0}
    inserted=0;staled=0
    with db() as c,c.cursor() as cur:
        if not table_exists(cur,"market_os_release_candidates"):
            return {"inserted":0,"staled":0}
        cur.execute("""SELECT rc.release_candidate_id,rc.source_ruleset_id,rc.status,
                              rc.canary_allocation_pct,rc.canary_started_at,
                              rc.canary_last_scanned_at,
                              vr.base_rule_version,vr.status AS ruleset_status,vr.spec,
                              sd.decision_state AS succession_state,
                              sd.review_eligible AS succession_eligible
                       FROM market_os_release_candidates rc
                       JOIN market_os_versioned_rulesets vr
                         ON vr.ruleset_id=rc.source_ruleset_id
                       LEFT JOIN market_os_ruleset_succession_decisions sd
                         ON sd.ruleset_id=rc.source_ruleset_id
                       WHERE rc.status='CANARY_ACTIVE'
                       ORDER BY rc.canary_started_at""")
        for rc in cur.fetchall():
            source_ok=bool(
                rc["ruleset_status"]=="DRY_RUN_ACTIVE"
                and rc["succession_state"]=="SUCCESSION_CANDIDATE"
                and rc["succession_eligible"]
            )
            if not source_ok:
                cur.execute("""UPDATE market_os_release_candidates
                               SET status='CANARY_SOURCE_STALE',stale_at=now(),
                                   note='Source ruleset/succession no longer release-eligible'
                               WHERE release_candidate_id=%s AND status='CANARY_ACTIVE'""",
                            (rc["release_candidate_id"],))
                if cur.rowcount:
                    cur.execute("""INSERT INTO market_os_release_events(
                            release_candidate_id,event_type,from_status,to_status,evidence)
                        VALUES(%s,'SOURCE_STALE','CANARY_ACTIVE','CANARY_SOURCE_STALE',%s::jsonb)""",
                        (rc["release_candidate_id"],json.dumps({
                            "ruleset_status":rc["ruleset_status"],
                            "succession_state":rc["succession_state"],
                            "succession_eligible":bool(rc["succession_eligible"]),
                        },ensure_ascii=False)))
                    staled+=1
                continue

            # Advance by complete assessment timestamps, including rows not assigned
            # to Canary, so the 80% CONTROL-only population is not rescanned forever.
            cur.execute("""WITH next_times AS (
                               SELECT DISTINCT snapshot_time
                               FROM market_os_assessment_snapshots
                               WHERE rule_version=%s
                                 AND snapshot_time>%s
                               ORDER BY snapshot_time
                               LIMIT %s
                           )
                           SELECT a.*
                           FROM market_os_assessment_snapshots a
                           JOIN next_times t ON t.snapshot_time=a.snapshot_time
                           WHERE a.rule_version=%s
                           ORDER BY a.snapshot_time,a.stock_code""",
                        (rc["base_rule_version"],
                         rc["canary_last_scanned_at"] or rc["canary_started_at"],
                         max(1,limit_per_release//12),
                         rc["base_rule_version"]))
            scanned=cur.fetchall()
            rows=[]
            for a in scanned:
                day=a["snapshot_time"].astimezone(KST).date().isoformat()
                if not is_canary_selected(
                    rc["release_candidate_id"],a["stock_code"],day,rc["canary_allocation_pct"]
                ):
                    continue
                result=ruleset_evaluate(dict(a),rc["spec"] or {})
                rows.append((
                    a["snapshot_time"],a["stock_code"],a["rule_version"],
                    rc["release_candidate_id"],day,
                    canary_bucket(rc["release_candidate_id"],a["stock_code"],day),
                    rc["canary_allocation_pct"],result["control_tier"],
                    result["candidate_tier"],result["changed"],
                    json.dumps(result["matched_overlays"],ensure_ascii=False)
                ))
            if rows:
                cur.executemany("""INSERT INTO market_os_canary_observations(
                        assessment_time,stock_code,control_rule_version,release_candidate_id,
                        trade_day,assignment_bucket,allocation_pct,control_tier,candidate_tier,
                        changed,matched_overlays)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT DO NOTHING""",rows)
                inserted+=cur.rowcount if cur.rowcount is not None and cur.rowcount>=0 else len(rows)
            if scanned:
                last_scan=max(a["snapshot_time"] for a in scanned)
                cur.execute("""UPDATE market_os_release_candidates
                               SET canary_last_scanned_at=%s,last_evaluated_at=now()
                               WHERE release_candidate_id=%s""",
                            (last_scan,rc["release_candidate_id"]))
    return {"inserted":inserted,"staled":staled}


def refresh_canary_summaries():
    """Summarize canary-only CONTROL vs candidate and enforce rollback stop."""
    if not CANARY_ENABLED:
        return {"written":0,"rollbacks":0}
    written=0;rollbacks=0
    with db() as c,c.cursor() as cur:
        if not table_exists(cur,"market_os_release_candidates"):
            return {"written":0,"rollbacks":0}
        cur.execute("""SELECT release_candidate_id,status
                       FROM market_os_release_candidates
                       WHERE canary_started_at IS NOT NULL
                       ORDER BY created_at""")
        for rc in cur.fetchall():
            cur.execute("""SELECT o.assessment_time,o.stock_code,o.trade_day,
                                  o.control_tier,o.candidate_tier,a.market_stance,
                                  y.horizon,y.return_pct,y.mfe_pct,y.mae_pct
                           FROM market_os_canary_observations o
                           JOIN market_os_assessment_outcomes y
                             ON y.assessment_time=o.assessment_time
                            AND y.stock_code=o.stock_code
                            AND y.rule_version=o.control_rule_version
                           JOIN market_os_assessment_snapshots a
                             ON a.snapshot_time=o.assessment_time
                            AND a.stock_code=o.stock_code
                            AND a.rule_version=o.control_rule_version
                           WHERE o.release_candidate_id=%s
                             AND y.horizon IN ('5m','30m','close','D+1')
                           ORDER BY y.horizon,o.stock_code,o.assessment_time""",
                        (rc["release_candidate_id"],))
            raw=[]
            for r in cur.fetchall():
                x=dict(r)
                x["snapshot_time"]=r["assessment_time"]
                if not x.get("trade_day"):
                    x["trade_day"]=r["assessment_time"].astimezone(KST).date().isoformat()
                else:
                    x["trade_day"]=str(x["trade_day"])
                raw.append(x)
            anchors=_episode_anchors(raw)
            summaries=canary_summaries(anchors)
            slices=canary_slices(anchors)
            decision=canary_decision(summaries,slices)

            cur.execute("""DELETE FROM market_os_canary_summary
                           WHERE release_candidate_id=%s""",(rc["release_candidate_id"],))
            for s in summaries:
                control=s["control"];candidate=s["challenger"]
                state=_shadow_evidence_state(s)
                cur.execute("""INSERT INTO market_os_canary_summary(
                        release_candidate_id,horizon,cohort,evidence_state,membership_changes,
                        control_samples,control_stocks,control_days,control_avg_return_pct,
                        control_median_return_pct,control_positive_rate,control_avg_mfe_pct,control_avg_mae_pct,
                        candidate_samples,candidate_stocks,candidate_days,candidate_avg_return_pct,
                        candidate_median_return_pct,candidate_positive_rate,candidate_avg_mfe_pct,
                        candidate_avg_mae_pct,delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct,updated_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                    (rc["release_candidate_id"],s["horizon"],s["cohort"],state,s["membership_changes"],
                     control["samples"],control["distinct_stocks"],control["distinct_days"],
                     control["avg_return_pct"],control["median_return_pct"],control["positive_rate"],
                     control["avg_mfe_pct"],control["avg_mae_pct"],
                     candidate["samples"],candidate["distinct_stocks"],candidate["distinct_days"],
                     candidate["avg_return_pct"],candidate["median_return_pct"],candidate["positive_rate"],
                     candidate["avg_mfe_pct"],candidate["avg_mae_pct"],
                     s["delta_avg_return_pct"],s["delta_positive_rate_pp"],s["delta_mae_pct"]))
                written+=1

            cur.execute("""SELECT decision_state FROM market_os_canary_decisions
                           WHERE release_candidate_id=%s""",(rc["release_candidate_id"],))
            old=cur.fetchone();old_state=old["decision_state"] if old else None
            reasons_json=json.dumps(decision.get("reason_codes") or [],ensure_ascii=False)
            evidence_json=json.dumps(decision.get("evidence") or {},ensure_ascii=False,default=str)
            primary=(decision.get("evidence") or {}).get("primary_cohort")
            cur.execute("""INSERT INTO market_os_canary_decisions(
                    release_candidate_id,decision_state,review_eligible,primary_cohort,
                    reason_codes,evidence,manual_review_state,state_since,updated_at)
                VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb,'PENDING',now(),now())
                ON CONFLICT(release_candidate_id) DO UPDATE SET
                    decision_state=excluded.decision_state,
                    review_eligible=excluded.review_eligible,
                    primary_cohort=excluded.primary_cohort,
                    reason_codes=excluded.reason_codes,evidence=excluded.evidence,
                    state_since=CASE
                        WHEN market_os_canary_decisions.decision_state=excluded.decision_state
                        THEN market_os_canary_decisions.state_since ELSE now() END,
                    updated_at=now()""",
                (rc["release_candidate_id"],decision["state"],
                 bool(decision.get("review_eligible")),primary,reasons_json,evidence_json))
            if old_state!=decision["state"]:
                cur.execute("""INSERT INTO market_os_canary_decision_events(
                        release_candidate_id,from_state,to_state,review_eligible,
                        reason_codes,evidence)
                    VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
                    (rc["release_candidate_id"],old_state,decision["state"],
                     bool(decision.get("review_eligible")),reasons_json,evidence_json))

            if decision["state"]=="CANARY_ROLLBACK_REQUIRED" and rc["status"]=="CANARY_ACTIVE":
                cur.execute("""UPDATE market_os_release_candidates
                               SET status='CANARY_ROLLBACK_REQUIRED',rollback_at=now(),
                                   note='Canary safety gate detected comparable harm'
                               WHERE release_candidate_id=%s AND status='CANARY_ACTIVE'""",
                            (rc["release_candidate_id"],))
                if cur.rowcount:
                    cur.execute("""INSERT INTO market_os_release_events(
                            release_candidate_id,event_type,from_status,to_status,evidence)
                        VALUES(%s,'AUTO_CANARY_ROLLBACK','CANARY_ACTIVE',
                               'CANARY_ROLLBACK_REQUIRED',%s::jsonb)""",
                        (rc["release_candidate_id"],evidence_json))
                    rollbacks+=1
    return {"written":written,"rollbacks":rollbacks}


def _full_release_composition(cur,rc):
    """Compare deterministic Canary stock-day sample with the eligible CONTROL universe."""
    started=rc.get("canary_started_at")
    scanned=rc.get("canary_last_scanned_at")
    base=rc.get("base_rule_version")
    if not started or not base:
        return {
            "expected_pct":rc.get("canary_allocation_pct"),
            "eligible_stock_days":0,"selected_stock_days":0,
            "stance_universe":{},"stance_canary":{},
            "tier_universe":{},"tier_canary":{},
        }

    cur.execute("""SELECT DISTINCT ON(stock_code,trade_day)
                          stock_code,trade_day,market_stance,watch_tier
                   FROM (
                       SELECT stock_code,
                              (snapshot_time AT TIME ZONE 'Asia/Seoul')::date AS trade_day,
                              snapshot_time,market_stance,watch_tier
                       FROM market_os_assessment_snapshots
                       WHERE rule_version=%s AND snapshot_time>=%s
                         AND (%s IS NULL OR snapshot_time<=%s)
                   ) x
                   ORDER BY stock_code,trade_day,snapshot_time""",
                (base,started,scanned,scanned))
    universe=cur.fetchall()

    cur.execute("""SELECT DISTINCT ON(o.stock_code,o.trade_day)
                          o.stock_code,o.trade_day,a.market_stance,a.watch_tier,o.assessment_time
                   FROM market_os_canary_observations o
                   JOIN market_os_assessment_snapshots a
                     ON a.snapshot_time=o.assessment_time
                    AND a.stock_code=o.stock_code
                    AND a.rule_version=o.control_rule_version
                   WHERE o.release_candidate_id=%s
                   ORDER BY o.stock_code,o.trade_day,o.assessment_time""",
                (rc["release_candidate_id"],))
    selected=cur.fetchall()

    def counts(rows,key):
        out={}
        for r in rows:
            value=r[key] or "UNKNOWN"
            out[value]=out.get(value,0)+1
        return out

    return {
        "expected_pct":int(rc.get("canary_allocation_pct") or 0),
        "eligible_stock_days":len(universe),
        "selected_stock_days":len(selected),
        "stance_universe":counts(universe,"market_stance"),
        "stance_canary":counts(selected,"market_stance"),
        "tier_universe":counts(universe,"watch_tier"),
        "tier_canary":counts(selected,"watch_tier"),
    }


def refresh_full_release_reviews():
    """Maintain Full Release Gate and freeze one review package per READY transition."""
    with db() as c,c.cursor() as cur:
        required=(
            "market_os_release_candidates","market_os_canary_decisions",
            "market_os_canary_summary","market_os_versioned_rulesets",
            "market_os_ruleset_dry_run_summary","market_os_full_release_gates",
        )
        if any(not table_exists(cur,x) for x in required):
            return {"gate_transitions":0,"reviews_generated":0,"reviews_staled":0}

        cur.execute("""SELECT rc.release_candidate_id,rc.release_version_label,
                              rc.source_ruleset_id,rc.package_hash,rc.package,rc.status,
                              rc.canary_allocation_pct,rc.canary_started_at,
                              rc.canary_last_scanned_at,
                              cd.decision_state,cd.review_eligible,cd.primary_cohort,
                              cd.reason_codes AS canary_reason_codes,cd.evidence AS canary_evidence,
                              vr.ruleset_id,vr.version_label,vr.base_rule_version,
                              vr.spec_hash,vr.spec,vr.status AS ruleset_status
                       FROM market_os_release_candidates rc
                       JOIN market_os_versioned_rulesets vr
                         ON vr.ruleset_id=rc.source_ruleset_id
                       LEFT JOIN market_os_canary_decisions cd
                         ON cd.release_candidate_id=rc.release_candidate_id
                       WHERE rc.canary_started_at IS NOT NULL
                       ORDER BY rc.created_at""")
        releases=cur.fetchall()
        transitions=0;generated=0;staled=0

        for row in releases:
            rc=dict(row)
            cur.execute("""SELECT horizon,cohort,evidence_state,membership_changes,
                                  control_samples,candidate_samples,
                                  control_avg_return_pct,candidate_avg_return_pct,
                                  delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_canary_summary
                           WHERE release_candidate_id=%s""",(row["release_candidate_id"],))
            canary_rows=[dict(x) for x in cur.fetchall()]

            cur.execute("""SELECT horizon,cohort,evidence_state,membership_changes,
                                  control_samples,candidate_samples,
                                  control_avg_return_pct,candidate_avg_return_pct,
                                  delta_avg_return_pct,delta_positive_rate_pp,delta_mae_pct
                           FROM market_os_ruleset_dry_run_summary
                           WHERE ruleset_id=%s""",(row["source_ruleset_id"],))
            dry_rows=[dict(x) for x in cur.fetchall()]

            composition=_full_release_composition(cur,{
                **rc,"release_candidate_id":row["release_candidate_id"],
                "base_rule_version":row["base_rule_version"],
                "canary_last_scanned_at":row["canary_last_scanned_at"],
            })
            canary_decision={
                "decision_state":row["decision_state"],
                "review_eligible":bool(row["review_eligible"]),
                "primary_cohort":row["primary_cohort"],
                "reason_codes":row["canary_reason_codes"] or [],
                "evidence":row["canary_evidence"] or {},
            }
            release_candidate={
                "release_candidate_id":row["release_candidate_id"],
                "release_version_label":row["release_version_label"],
                "source_ruleset_id":row["source_ruleset_id"],
                "package_hash":row["package_hash"],
                "package":row["package"] or {},
                "status":row["status"],
            }
            ruleset={
                "ruleset_id":row["ruleset_id"],"version_label":row["version_label"],
                "base_rule_version":row["base_rule_version"],"spec_hash":row["spec_hash"],
                "spec":row["spec"] or {},"status":row["ruleset_status"],
            }
            gate=full_release_gate(
                release_candidate,canary_decision,canary_rows,dry_rows,
                composition,ruleset,RULE_VERSION
            )

            cur.execute("""SELECT gate_state FROM market_os_full_release_gates
                           WHERE release_candidate_id=%s""",(row["release_candidate_id"],))
            old=cur.fetchone();old_state=old["gate_state"] if old else None
            reasons_json=json.dumps(gate["reason_codes"],ensure_ascii=False)
            evidence_json=json.dumps(gate["evidence"],ensure_ascii=False,default=str)
            cur.execute("""INSERT INTO market_os_full_release_gates(
                    release_candidate_id,gate_state,review_eligible,reason_codes,evidence,
                    state_since,updated_at)
                VALUES(%s,%s,%s,%s::jsonb,%s::jsonb,now(),now())
                ON CONFLICT(release_candidate_id) DO UPDATE SET
                    gate_state=excluded.gate_state,
                    review_eligible=excluded.review_eligible,
                    reason_codes=excluded.reason_codes,evidence=excluded.evidence,
                    state_since=CASE
                        WHEN market_os_full_release_gates.gate_state=excluded.gate_state
                        THEN market_os_full_release_gates.state_since ELSE now() END,
                    updated_at=now()""",
                (row["release_candidate_id"],gate["state"],gate["review_eligible"],
                 reasons_json,evidence_json))

            gate_event_id=None
            if old_state!=gate["state"]:
                cur.execute("""INSERT INTO market_os_full_release_gate_events(
                        release_candidate_id,from_state,to_state,review_eligible,
                        reason_codes,evidence)
                    VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                    RETURNING event_id""",
                    (row["release_candidate_id"],old_state,gate["state"],
                     gate["review_eligible"],reasons_json,evidence_json))
                gate_event_id=cur.fetchone()["event_id"]
                transitions+=1

            # Human readiness is revocable until a future live switch exists.
            if gate["state"]!="FULL_RELEASE_REVIEW_READY":
                cur.execute("""SELECT review_id,review_state FROM market_os_full_release_reviews
                               WHERE release_candidate_id=%s
                                 AND review_state IN ('PENDING','RELEASE_READY')""",
                            (row["release_candidate_id"],))
                for pending in cur.fetchall():
                    cur.execute("""UPDATE market_os_full_release_reviews
                                   SET review_state='STALE_CANARY'
                                   WHERE review_id=%s
                                     AND review_state IN ('PENDING','RELEASE_READY')""",
                                (pending["review_id"],))
                    if cur.rowcount:
                        cur.execute("""INSERT INTO market_os_full_release_review_events(
                                review_id,event_type,from_review_state,to_review_state,note,evidence)
                            VALUES(%s,'CANARY_GATE_STALE',%s,'STALE_CANARY',
                                   'Full Release Gate no longer REVIEW_READY',%s::jsonb)""",
                            (pending["review_id"],pending["review_state"],json.dumps({
                                "gate_state":gate["state"],
                                "reason_codes":gate["reason_codes"],
                            },ensure_ascii=False)))
                        staled+=1
                cur.execute("""UPDATE market_os_canary_decisions
                               SET manual_review_state='FULL_RELEASE_STALE'
                               WHERE release_candidate_id=%s""",(row["release_candidate_id"],))
                continue

            # A review package is frozen only on entry into REVIEW_READY.
            if not gate_event_id:
                continue
            cur.execute("""SELECT 1 FROM market_os_full_release_reviews
                           WHERE release_candidate_id=%s AND source_gate_event_id=%s""",
                        (row["release_candidate_id"],gate_event_id))
            if cur.fetchone():
                continue

            cur.execute("""SELECT review_id,revision,review_state
                           FROM market_os_full_release_reviews
                           WHERE release_candidate_id=%s
                           ORDER BY revision DESC LIMIT 1""",(row["release_candidate_id"],))
            prev=cur.fetchone()
            revision=(int(prev["revision"])+1) if prev else 1
            if prev and prev["review_state"]=="PENDING":
                cur.execute("""UPDATE market_os_full_release_reviews
                               SET review_state='SUPERSEDED'
                               WHERE review_id=%s AND review_state='PENDING'""",(prev["review_id"],))
                if cur.rowcount:
                    cur.execute("""INSERT INTO market_os_full_release_review_events(
                            review_id,event_type,from_review_state,to_review_state,note,evidence)
                        VALUES(%s,'SUPERSEDED_BY_NEW_READY_GATE','PENDING','SUPERSEDED',
                               'New FULL_RELEASE_REVIEW_READY transition',%s::jsonb)""",
                        (prev["review_id"],json.dumps({"next_revision":revision},ensure_ascii=False)))

            built=build_full_release_review(
                release_candidate,gate_event_id,gate,canary_rows,dry_rows,
                composition,ruleset,RULE_VERSION
            )
            review_id=built["review_id"]+f"-r{revision:03d}"
            cur.execute("""INSERT INTO market_os_full_release_reviews(
                    review_id,release_candidate_id,revision,source_gate_event_id,
                    content_hash,gate_state,review_state,package)
                VALUES(%s,%s,%s,%s,%s,%s,'PENDING',%s::jsonb)""",
                (review_id,row["release_candidate_id"],revision,gate_event_id,
                 built["content_hash"],gate["state"],
                 json.dumps(built["package"],ensure_ascii=False,default=str)))
            cur.execute("""INSERT INTO market_os_full_release_review_events(
                    review_id,event_type,from_review_state,to_review_state,note,evidence)
                VALUES(%s,'GENERATED',NULL,'PENDING',
                       'Immutable Full Release Review package generated',%s::jsonb)""",
                (review_id,json.dumps({
                    "release_candidate_id":row["release_candidate_id"],
                    "source_gate_event_id":gate_event_id,
                    "content_hash":built["content_hash"],
                },ensure_ascii=False)))
            cur.execute("""UPDATE market_os_canary_decisions
                           SET manual_review_state='FULL_RELEASE_REVIEW_PENDING'
                           WHERE release_candidate_id=%s""",(row["release_candidate_id"],))
            generated+=1

        return {
            "gate_transitions":transitions,
            "reviews_generated":generated,
            "reviews_staled":staled,
        }


def update_status(status,note,last_snapshot=None,last_outcome=False):
    with db() as c,c.cursor() as cur:
        rule_version=active_control_version(cur)
        cur.execute("SELECT COUNT(*) AS n FROM market_os_assessment_snapshots WHERE rule_version=%s",(rule_version,))
        assessments=int(cur.fetchone()["n"])
        cur.execute("SELECT COUNT(*) AS n,MAX(calculated_at) AS t FROM market_os_assessment_outcomes WHERE rule_version=%s",(rule_version,))
        r=cur.fetchone();outcomes=int(r["n"]);out_t=r["t"]
        cur.execute("""INSERT INTO market_os_learning_status(
          id,updated_at,status,last_snapshot_at,last_outcome_at,assessments_total,outcomes_total,note)
          VALUES(1,now(),%s,%s,%s,%s,%s,%s)
          ON CONFLICT(id) DO UPDATE SET updated_at=now(),status=excluded.status,
          last_snapshot_at=COALESCE(excluded.last_snapshot_at,market_os_learning_status.last_snapshot_at),
          last_outcome_at=COALESCE(excluded.last_outcome_at,market_os_learning_status.last_outcome_at),
          assessments_total=excluded.assessments_total,outcomes_total=excluded.outcomes_total,note=excluded.note""",
          (status,last_snapshot,out_t if last_outcome else None,assessments,outcomes,note))


def cycle():
    captured,snap=capture_assessments()
    shadow_obs=capture_shadow_observations()
    outcomes=resolve_outcomes()
    segments=refresh_segments()
    registry=refresh_promotion_registry()
    shadow_summaries=refresh_shadow_summaries()
    dossiers=refresh_adoption_dossiers()
    ruleset_obs=capture_ruleset_dry_run_observations()
    ruleset_summaries=refresh_ruleset_dry_run_summaries()
    canary_obs=capture_canary_observations()
    canary_stats=refresh_canary_summaries()
    full_release=refresh_full_release_reviews()
    update_status(
        "OK",
        f"captured={captured} shadow_obs={shadow_obs} outcomes={outcomes} segments={segments} "
        f"registry_active={registry['active']} promotion_candidates={registry['promotion_candidates']} "
        f"registry_transitions={registry['transitions']} shadow_summaries={shadow_summaries} "
        f"dossiers_generated={dossiers['generated']} dossiers_staled={dossiers['staled']} "
        f"ruleset_obs={ruleset_obs['inserted']} ruleset_stale={ruleset_obs['staled']} "
        f"ruleset_summaries={ruleset_summaries} canary_obs={canary_obs['inserted']} "
        f"canary_stale={canary_obs['staled']} canary_rollbacks={canary_stats['rollbacks']} "
        f"full_release_transitions={full_release['gate_transitions']} "
        f"full_release_reviews={full_release['reviews_generated']} "
        f"full_release_stale={full_release['reviews_staled']}",
        last_snapshot=snap,last_outcome=bool(outcomes)
    )
    return (captured,outcomes,segments,registry,shadow_obs,shadow_summaries,dossiers,
            ruleset_obs,ruleset_summaries,canary_obs,canary_stats,full_release)


if __name__=="__main__":
    ensure_schema()
    print(f"Market OS learning started · poll={POLL}s · rule={RULE_VERSION}",flush=True)
    while True:
        try:
            a,o,s,r,so,ss,ad,ro,rs,co,cs,fr=cycle()
            if (a or o or so or r.get("transitions") or ad.get("generated")
                    or ad.get("staled") or ro.get("inserted") or ro.get("staled")
                    or co.get("inserted") or co.get("staled") or cs.get("rollbacks")
                    or fr.get("gate_transitions") or fr.get("reviews_generated")
                    or fr.get("reviews_staled")):
                print(
                    f"learning cycle assessments={a} shadow_obs={so} outcomes={o} segments={s} "
                    f"registry={r['active']} candidates={r['promotion_candidates']} "
                    f"transitions={r['transitions']} shadow_summaries={ss} "
                    f"dossiers={ad['generated']} dossier_stale={ad['staled']} "
                    f"ruleset_obs={ro['inserted']} ruleset_stale={ro['staled']} summaries={rs} "
                    f"canary_obs={co['inserted']} canary_stale={co['staled']} "
                    f"canary_rollbacks={cs['rollbacks']} "
                    f"full_release_transitions={fr['gate_transitions']} "
                    f"full_release_reviews={fr['reviews_generated']} "
                    f"full_release_stale={fr['reviews_staled']}",
                    flush=True
                )
        except Exception as exc:
            print("market os learning error",type(exc).__name__,str(exc)[:400],flush=True)
            try:update_status("ERROR",type(exc).__name__)
            except Exception:pass
        time.sleep(POLL)
