-- Market OS shadow-learning schema
-- Live assessments and future outcomes are intentionally separated to prevent look-ahead leakage.

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

CREATE TABLE IF NOT EXISTS market_os_assessment_outcomes (
    assessment_time     TIMESTAMPTZ NOT NULL,
    stock_code          TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    horizon             TEXT NOT NULL, -- 5m / 30m / close / D+1
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
    segment_type        TEXT NOT NULL, -- TIER/STANCE/TRIGGER/SESSION/CATALYST/SETUP
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

-- Learning policy:
-- 1. never join future outcome data into live assessment creation;
-- 2. keep rule_version on every row;
-- 3. compare market stance + time-of-day before changing thresholds;
-- 4. shadow feedback requires >=20 samples; rule changes remain manual/versioned in v1.

-- 0B microstructure is captured as shadow evidence only.
-- Recommended analysis dimensions: MICRO_STRENGTH / MICRO_BUY_SHARE.
-- Do not feed these features into live Radar/Setup scoring until sample-backed validation.


-- Episode-anchor learning policy:
-- 5m: non-overlapping 5-minute anchors per stock.
-- 30m: non-overlapping 30-minute anchors per stock.
-- close/D+1: one anchor per stock per KST trade day.
-- Raw assessment snapshots remain intact for audit; segment sample counts use anchors.
-- Confidence additionally requires stock diversity and multiple trade days.


CREATE TABLE IF NOT EXISTS market_os_interaction_edges (
    segment_type TEXT NOT NULL,
    segment_value TEXT NOT NULL,
    horizon TEXT NOT NULL,
    parent_type TEXT NOT NULL,
    parent_value TEXT NOT NULL,
    sample_basis TEXT NOT NULL,
    child_samples INTEGER NOT NULL,
    child_stocks INTEGER NOT NULL,
    child_days INTEGER NOT NULL,
    comparator_samples INTEGER NOT NULL,
    comparator_stocks INTEGER NOT NULL,
    comparator_days INTEGER NOT NULL,
    child_avg_return_pct DOUBLE PRECISION,
    comparator_avg_return_pct DOUBLE PRECISION,
    delta_avg_return_pct DOUBLE PRECISION,
    child_positive_rate DOUBLE PRECISION,
    comparator_positive_rate DOUBLE PRECISION,
    delta_positive_rate_pp DOUBLE PRECISION,
    child_avg_mfe_pct DOUBLE PRECISION,
    comparator_avg_mfe_pct DOUBLE PRECISION,
    delta_mfe_pct DOUBLE PRECISION,
    child_avg_mae_pct DOUBLE PRECISION,
    comparator_avg_mae_pct DOUBLE PRECISION,
    delta_mae_pct DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(segment_type,segment_value,horizon)
);

-- Interaction edge policy:
-- child is compared with the parent-condition complement (parent rows excluding child rows),
-- not with the inclusive parent aggregate. This is descriptive conditional comparison,
-- not a causal estimate.
