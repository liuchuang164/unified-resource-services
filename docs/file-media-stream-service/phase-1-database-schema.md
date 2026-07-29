# Phase 1 Database Schema

Alembic revision: `20260729_01`.

Tables:

- `file_resource`
- `media_resource`
- `stream_session`
- `processing_job`
- `resource_grant`
- `audit_event`
- `idempotency_record`
- `reconciliation_record`

Every durable resource includes `tenant_id` and `biz_domain`. Resource lookups use tenant, domain,
and public identifier in the same SQL predicate. File, stream, and job tables have composite scope
indexes for identifier, status, and creation time. Idempotency has a unique constraint on
`tenant_id`, `biz_domain`, `caller_id`, `operation`, and `idempotency_key`.

Repositories share an async scoped SQLAlchemy session. The HTTP application boundary commits once
after the operation and audit have completed, or rolls back on failure. Alembic—not `create_all`—is
the production schema authority.
