-- Phase 2.5 production governance persistence.
-- Forward migration. Idempotent for PostgreSQL.

CREATE TABLE IF NOT EXISTS quota_policy (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    biz_domain VARCHAR(64) NOT NULL,
    operation VARCHAR(128),
    provider VARCHAR(64),
    limit_value INTEGER NOT NULL,
    period VARCHAR(32) NOT NULL DEFAULT 'DAY',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quota_policy_scope
    ON quota_policy (tenant_id, biz_domain, operation, provider);

CREATE TABLE IF NOT EXISTS provider_runtime_config (
    provider_code VARCHAR(64) PRIMARY KEY,
    timeout_ms INTEGER NOT NULL DEFAULT 30000,
    retry_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    rate_limit JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Rollback:
-- DROP TABLE IF EXISTS provider_runtime_config;
-- DROP TABLE IF EXISTS quota_policy;
