# 数据库分发管控服务

Phase 1 Python/FastAPI baseline for `POST /data/dispatch`.

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
pytest
```

## Phase 1 Scope

- Implements frozen `DataRequest` / `DataResponse` contracts.
- Enforces tenant and business-domain scope, RBAC-style permissions, payload limits, idempotency and routing.
- Registers controlled adapters for PostgreSQL, MinIO, Redis, Neo4j, Milvus and TimescaleDB.
- Uses in-memory infrastructure for idempotency and audit so the service can start and be tested without external databases.

## Non-goals

- No raw SQL/Cypher/Redis command/path execution.
- No business-domain logic.
- No cross-adapter distributed transaction guarantee.
- No production database migrations yet; the first durable persistence migration must be added when a real metadata store is selected.
