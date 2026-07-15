-- ICU Postgres schema — build to spec: ICU_Contract_Spec_v1.2_BasketA.md, ICU_BasketC_Registry_Decisions_v1.2.md
-- Run once against the `icu` database.

CREATE TABLE IF NOT EXISTS process_registry (
    component_id       TEXT PRIMARY KEY,
    display_name       TEXT NOT NULL,
    endpoint_url        TEXT,
    log_path            TEXT NOT NULL,
    github_repo_tag     TEXT,
    schedule_string      TEXT NOT NULL CHECK (schedule_string IN ('15M','1H','4H','1D','1W','1MO','ON_DEMAND')),
    expected_interval   INTERVAL CHECK (expected_interval IS NULL OR expected_interval >= INTERVAL '15 minutes'),
    registered_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    allowed_to_run      BOOLEAN NOT NULL DEFAULT TRUE,
    -- Basket C v1.2 / Contract Spec v1.2 §7: ON_DEMAND requires endpoint_url (Run Now is the only wake mechanism)
    CONSTRAINT on_demand_requires_endpoint CHECK (
        schedule_string <> 'ON_DEMAND' OR endpoint_url IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS status_log (
    id              BIGSERIAL PRIMARY KEY,
    component_id    TEXT NOT NULL REFERENCES process_registry(component_id),
    schema_version  TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('IDLE','RUNNING','PAUSED','HALTED','ERROR')),
    timestamp_utc   TIMESTAMPTZ,
    version         TEXT,
    last_run_utc    TIMESTAMPTZ,
    last_run_result TEXT CHECK (last_run_result IN ('SUCCESS','PARTIAL','DEGRADED','FAILED','CRITICAL','SKIPPED') OR last_run_result IS NULL),
    trigger         TEXT CHECK (trigger IN ('SCHEDULED','MANUAL','GATE_CHECK','HEARTBEAT') OR trigger IS NULL),
    message         TEXT,
    metrics         JSONB,
    health          JSONB,
    received_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_status_log_component_received
    ON status_log (component_id, received_at DESC);
