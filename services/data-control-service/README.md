# 数据库分发管控服务

Phase 1.2 Python/FastAPI baseline for `POST /data/dispatch`.

## Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn data_control_service.main:app --reload
```

## Test

```bash
ruff check .
mypy src
pytest -q
pytest --cov=src --cov-report=term-missing
```

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
- `SQLAlchemyIdempotencyRepository` and Alembic migration define the durable table and unique scope for `tenant_id`, `biz_domain`, `operation`, `target` and `idempotency_key`.
- The default local dependency still uses the in-memory implementation.

## Adapter Implementations

All six adapters are first-phase in-memory implementations with storage-specific contracts:

- PostgreSQL: relation-like rows, tenant/domain columns, controlled CRUD and batch.
- MinIO: server-side bucket mapping and generated tenant/domain object keys.
- Redis: server-generated key namespace, TTL limit and token-based locks.
- Neo4j: node/relation stores with label and relation allowlists.
- Milvus: vector dimension validation, metadata allowlist and cosine search.
- TimescaleDB: timestamp validation, bounded time-range queries and sorted results.

## Resource Registry

`ResourceRegistry` maps platform logical resources to targets and adapter-specific physical mappings. The built-in defaults are neutral demo mappings such as `DOCUMENT_RECORD`, `OBJECT_ASSET`, `CACHE_ENTRY`, `GRAPH_ENTITY`, `VECTOR_ITEM` and `TIME_SERIES_POINT`; tenant-specific mappings should move to configuration such as `config/resources.example.yaml`.

## Readiness

`GET /health/live` only confirms the process can respond. `GET /health/ready` checks configured service components, registry validation and every registered adapter's public health result. Required adapter failure makes the service not ready; optional adapter failure marks it degraded.

## Non-goals

- No raw SQL/Cypher/Redis command/path execution.
- No business-domain logic.
- No cross-adapter distributed transaction guarantee.
- No production identity provider implementation in this phase; `development` auth is blocked when `APP_ENV=production`.
- No real PostgreSQL, MinIO, Redis, Neo4j, Milvus or TimescaleDB driver integration yet.
