# Phase 1 Production Adapters

Phase 1 implements the Phase 0 Ports with PostgreSQL 16+, Redis, and MinIO while preserving Domain,
Use Case, Gateway, Unified Entry, HTTP, and Tool contracts.

- PostgreSQL is the durable fact source for resources, sessions, jobs, audit, idempotency snapshots,
  and reconciliation records. Repositories flush but never commit.
- Redis provides owner-token leases, fencing counters, replay protection, quotas, and bounded waits.
  Sensitive values are represented by SHA-256 digests in keys.
- MinIO uses the frozen server-generated object key. The bucket is constructor configuration and
  cannot be supplied by callers. Upload/download URLs have bounded TTLs and are never logged or
  persisted.
- Production composition is explicit and fail-fast. Security is fail-closed until a later real IAM
  adapter is injected; no development identity or Fake Authorization is enabled.

The media-server and processing Ports deliberately use unavailable production boundaries because
those integrations are excluded from Phase 1.
