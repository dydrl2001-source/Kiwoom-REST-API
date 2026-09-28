-- Market OS validation schema
-- Design only in v1: do not auto-create or write until the snapshot worker is enabled.
-- Scores are observation axes, not expected-return probabilities.

CREATE TABLE IF NOT EXISTS market_os_assessment_snapshots (
    snapshot_time       TIMESTAMPTZ NOT NULL,
    stock_code          TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    watch_tier          TEXT NOT NULL,
    radar_score         SMALLINT,
    theme_score         SMALLINT,
    setup_score         SMALLINT,
    catalyst_grade      TEXT,
    trigger_state       TEXT,
    market_stance       TEXT,
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
    axis_reasons        JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_flags          JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_ref        JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_time, stock_code, rule_version)
);

CREATE INDEX IF NOT EXISTS idx_market_os_assessment_code_time
    ON market_os_assessment_snapshots(stock_code, snapshot_time DESC);

CREATE INDEX IF NOT EXISTS idx_market_os_assessment_tier_time
    ON market_os_assessment_snapshots(watch_tier, snapshot_time DESC);

-- Ex-post outcomes are calculated later from already-saved market data.
-- This separation prevents future prices from leaking into the live assessment.
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
    calculated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (assessment_time, stock_code, rule_version, horizon)
);

CREATE TABLE IF NOT EXISTS market_os_daily_reviews (
    trade_date          DATE PRIMARY KEY,
    rule_version        TEXT NOT NULL,
    regime_open         JSONB,
    regime_close        JSONB,
    top_themes          JSONB NOT NULL DEFAULT '[]'::jsonb,
    focus_candidates    JSONB NOT NULL DEFAULT '[]'::jsonb,
    false_positive_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    review_note         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Validation queries should always group by rule_version, market_stance,
-- time-of-day bucket, and watch_tier before changing thresholds.
