# Phase 1 Test Report

Verification environment: macOS ARM64, Python 3.12, Docker Desktop, PostgreSQL 16, Redis 7, and
MinIO.

Coverage includes:

- migration downgrade/upgrade;
- PostgreSQL scoped CRUD, rollback, unique conflicts, audit, idempotency restart, reconciliation,
  stream state, and job state;
- Redis owner-token release, expiry, renewal, replay, quota, disconnect, and coordinated
  idempotency;
- MinIO initialization, presigned URLs, multipart completion/abort, metadata, range reads, delete,
  absence, and permission denial;
- business Unified Entry and Agent Tool Gateway paths using real production infrastructure;
- existing Phase 0 failure injection and contract/security suites.

Final local result:

- `ruff check .`: PASS
- `ruff format --check .`: PASS
- `mypy src`: PASS, 66 source files
- `pytest`: PASS, 73 tests
- total coverage: 92.49%
- PostgreSQL repository core: 87%
- Redis coordination core: 91%
- MinIO adapter core: 85%
- Alembic `upgrade head -> downgrade -1 -> upgrade head`: PASS

The only warning is Starlette's upstream `TestClient` deprecation notice for `httpx`; it does not
affect behavior or test results.
