# File / Media Stream Service Phase 2 P1 Architecture Correction

## Scope

This correction closes four Phase 2 production consistency gaps without changing Gateway,
HTTP paths, Tool names, or media data-plane capabilities.

## Stream provisioning saga

Stream creation persists `CREATING` before calling the provider. After provider success, the
session is updated to `READY`. That update and the idempotency `COMPLETED` snapshot are committed
atomically. If the update or commit fails, the failed request transaction is rolled back and
closed before an isolated reconciliation transaction records:

- kind: `STREAM_PROVIDER_ORPHAN`
- required action: `STOP_PROVIDER_STREAM`
- scoped `tenant_id`, `biz_domain`, and `session_id`
- provider type, provider session ID, and fencing token

The request-scoped Saga compensator first creates the recovery record, then synchronously fences
the provider stop and releases the lease. This synchronous path still runs when PostgreSQL is
unavailable and the recovery record cannot be written. Successfully compensated records are
resolved; unresolved records are consumed later by the lifecycle worker.

## Lifecycle worker

`file_media_stream_service.worker_main` is an independent worker-process entry point. It does
not run as a FastAPI background task. The worker supports `start()`, `shutdown()`, graceful
signal handling, a scheduler loop, transaction commit/rollback, and per-cycle session cleanup.
Cycle failures are logged and retried; one malformed orphan record does not terminate the loop.

On restart it discovers recoverable tenant/domain scopes, renews an existing lease or acquires
a replacement fencing token, synchronizes provider state, and processes provider-orphan
reconciliation records.

## Transaction isolation

`PostgresIndependentReconciliationStore` owns a separate SQLAlchemy session factory. Recovery
records therefore do not reuse a failed request session. Each record and resolution operation
has its own committed transaction.

## Authorization alignment

Public operations remain unchanged. Unified Entry maps stream operations to policy actions:

| Operation | Required action |
| --- | --- |
| `media.create_stream_session` | `media_stream:create` plus direction-specific publish/subscribe |
| `media.get_stream_session` | `media_stream:subscribe` |
| `media.close_stream_session` | `media_stream:close` |

Provider adapters remain unaware of callers and permissions.

## Compatibility

- Gateway architecture: unchanged
- HTTP paths: unchanged
- Tool names and schemas: unchanged
- Public response shape: unchanged
- Existing stream states: unchanged
- PostgreSQL schema: unchanged; no migration is required
