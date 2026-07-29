# 数据库分发管控服务

Phase 3 Python/FastAPI service for `POST /data/dispatch`, with PostgreSQL control-plane persistence, a real SQLAlchemy PostgreSQL adapter path and a real `redis.asyncio` Redis adapter path.

## Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn data_control_service.main:app --reload
```

## PostgreSQL Development

```bash
docker compose -f docker-compose.postgresql.yml --profile dev up -d
CONTROL_DATABASE_MIGRATION_URL=postgresql+psycopg://data_control:change_me@localhost:5432/data_control alembic -c alembic-control.ini upgrade head
TARGET_DATABASE_MIGRATION_URL=postgresql+psycopg://data_control:change_me@localhost:5432/data_target alembic -c alembic-target.ini upgrade head
CONTROL_DATABASE_URL=postgresql+asyncpg://data_control:change_me@localhost:5432/data_control python scripts/bootstrap_postgresql.py
```

Use `CONTROL_DATABASE_URL` for service control-plane tables and `POSTGRESQL_ADAPTER_DATABASE_URL` for target PostgreSQL data. Development may point both to the same PostgreSQL instance, but control-plane tables live in `control_plane` and example target data lives in `data_target`.

Phase 2.1 splits Alembic history:

```bash
alembic -c alembic-control.ini current
alembic -c alembic-target.ini current
alembic -c alembic-control.ini downgrade -1
alembic -c alembic-target.ini downgrade -1
```

`alembic.ini` is deprecated and retained only for Phase 2 combined-chain transition reference. Existing Phase 2 databases should use `scripts/stamp_split_migrations.py` after verifying that control-plane tables and target tables already exist.

## Redis Development

```bash
docker compose -f docker-compose.redis.yml up -d
CONTROL_DATABASE_MIGRATION_URL=postgresql+psycopg://data_control:change_me@localhost:56432/data_control alembic -c alembic-control.ini upgrade head
TARGET_DATABASE_MIGRATION_URL=postgresql+psycopg://data_control:change_me@localhost:56433/data_target alembic -c alembic-target.ini upgrade head
CONTROL_DATABASE_URL=postgresql+asyncpg://data_control:change_me@localhost:56432/data_control REDIS_ADAPTER_ENABLED=true REDIS_URL=redis://localhost:56379/0 python scripts/bootstrap_postgresql.py
```

Use `REDIS_ADAPTER_ENABLED=true` and `REDIS_URL` to register the real Redis adapter. `REDIS_ADAPTER_REQUIRED=true` makes readiness fail when Redis is unavailable. Redis keys are always generated from server-side Resource Mapping as `{prefix}:{tenant_id}:{biz_domain}:{resource}:{logical_key}`; callers cannot submit raw commands, Lua, connection fields or physical keys.

## Test

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
pytest -m postgresql -q
pytest -m redis -q
pytest -m reliability -q
pytest tests/reliability/redis/test_stop_start.py -q
pytest --cov=src --cov-report=term-missing
```

`pytest -m postgresql` requires explicit PostgreSQL URLs. Without them, PostgreSQL tests skip and must not be counted as real Phase 2 validation.

`pytest -m redis` requires explicit Redis and control database URLs for real Redis dispatch coverage. Without them, real dependency tests skip and must not be counted as real Phase 3 validation. The dedicated stop/start test must only run with `REDIS_RELIABILITY_COMPOSE=1` in the repository compose environment.

## Phase 1.2 Scope

- Implements frozen `DataRequest` / `DataResponse` contracts.
- Builds trusted execution context from server-side authentication providers; request bodies cannot self-assert roles, permissions or cross-tenant scope.
- Enforces tenant and business-domain scope, logical resource mappings, operation permissions, payload limits, idempotency and routing.
- Registers controlled adapters for PostgreSQL, MinIO, Redis, Neo4j, Milvus and TimescaleDB without raw SQL, raw Cypher, raw Redis command, object-path or physical connection passthrough.
- Adds a transaction orchestrator for `NONE`, `LOCAL`, `ATOMIC` and ordered `BEST_EFFORT` batch semantics.
- Provides in-memory infrastructure for local development and SQLAlchemy metadata persistence for idempotency records.
- Exposes readiness through public service checks for auth, registry, resource mapping, idempotency and adapter health.

## Current AuthProvider

- `AUTH_PROVIDER=development` is the only runtime provider wired in this phase.
- `DevelopmentAuthProvider` reads trusted claims from `X-Dev-Subject-Id`, `X-Dev-Tenant-Id`, `X-Dev-Biz-Domains`, `X-Dev-Roles` and `X-Dev-Permissions`.
- It is valid only in `APP_ENV=development` or `APP_ENV=test`.
- `APP_ENV=production` with `AUTH_PROVIDER=development` fails application startup.

## Idempotency

- Application code depends on the `IdempotencyRepository` port.
- `InMemoryIdempotencyRepository` uses per-scope `asyncio.Lock` to make claim atomic.
- `SQLAlchemyIdempotencyRepository` uses PostgreSQL unique scope, row locking, owner tokens and timeout recovery.
- Runtime dependency switches to PostgreSQL when `CONTROL_DATABASE_URL` is configured. The in-memory implementation is retained for local unit tests and bootstrap-free development only.

## Adapter Implementations

PostgreSQL has a real SQLAlchemy Async adapter path. Redis has a real `redis.asyncio` adapter path when enabled. MinIO, Neo4j, Milvus and TimescaleDB remain Phase 1.2 in-memory implementations with storage-specific contracts:

- PostgreSQL: SQLAlchemy Core, parameterized statements, trusted Resource Mapping, tenant/domain filters, soft delete and optimistic versioning.
- MinIO: server-side bucket mapping and generated tenant/domain object keys.
- Redis: server-generated key namespace, persisted Resource Mapping, TTL limits, `GET/EXISTS/UPSERT/DELETE`, token-based `LOCK/UNLOCK` and fixed compare-and-delete Lua.
- Neo4j: node/relation stores with label and relation allowlists.
- Milvus: vector dimension validation, metadata allowlist and cosine search.
- TimescaleDB: timestamp validation, bounded time-range queries and sorted results.

## Resource Registry

`ResourceRegistry` maps platform logical resources to targets and adapter-specific physical mappings. Phase 2 adds `resource_mappings` and `policy_bindings` tables. The in-memory defaults remain for local unit tests; PostgreSQL runtime should bootstrap mappings and policies using `scripts/bootstrap_postgresql.py` or a controlled admin process.

## Readiness

`GET /health/live` only confirms the process can respond. `GET /health/ready` checks configured service components, registry validation and every registered adapter's public health result. Required adapter failure makes the service not ready; optional adapter failure marks it degraded.

When PostgreSQL URLs are configured, readiness also pings the control database, PostgreSQL adapter database and persistent repositories without returning host, port, database name, username or URL.

When Redis is enabled, readiness also pings Redis and validates Redis Resource Mapping from the control database without returning host, port, username, password, URL or physical keys.

## Non-goals

- No raw SQL/Cypher/Redis command/path execution.
- No business-domain logic.
- No cross-adapter distributed transaction guarantee.
- No production identity provider implementation in this phase; `development` auth is blocked when `APP_ENV=production`.
- No real MinIO, Neo4j, Milvus or TimescaleDB driver integration yet.
- No direct Redis command API, raw Lua, Scan/Keys/Flush or Redis management command passthrough.
- No cross-database atomicity between control-plane audit/idempotency and target data writes.
