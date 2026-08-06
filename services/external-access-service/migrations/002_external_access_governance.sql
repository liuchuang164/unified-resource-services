-- Phase 2 governance persistence for External Access Service.
-- Forward migration. Idempotent for PostgreSQL.

CREATE TABLE IF NOT EXISTS external_access_audit (
    id UUID PRIMARY KEY,
    request_id VARCHAR(128) NOT NULL,
    trace_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    biz_domain VARCHAR(64) NOT NULL,
    caller_type VARCHAR(64) NOT NULL,
    caller_id VARCHAR(128) NOT NULL,
    operation VARCHAR(128) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    latency_ms INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    provider_request_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_external_access_audit_tenant_domain
    ON external_access_audit (tenant_id, biz_domain, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_external_access_audit_request_scope
    ON external_access_audit (tenant_id, biz_domain, request_id);

CREATE TABLE IF NOT EXISTS external_usage_record (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    biz_domain VARCHAR(64) NOT NULL,
    operation VARCHAR(128) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 1,
    estimated_cost NUMERIC(18, 6) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_external_usage_tenant_domain
    ON external_usage_record (tenant_id, biz_domain, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_external_usage_operation_provider
    ON external_usage_record (tenant_id, biz_domain, operation, provider);

-- Rollback:
-- DROP TABLE IF EXISTS external_usage_record;
-- DROP TABLE IF EXISTS external_access_audit;
