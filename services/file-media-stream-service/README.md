# 文件/音视频流式服务

Phase 1 keeps the frozen control-plane contract and adds production PostgreSQL, Redis, and MinIO
adapters. InMemory/Fake adapters remain available only for tests and explicit local development.

## Run locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn file_media_stream_service.main:app --reload
```

The development composition is deny-by-default. Its only explicit sample scopes are:

- service caller `dev-service`, tenant `dev-tenant`, domain `development`;
- agent caller `dev-agent`, the same scope, and capability token `dev-capability-token`.

Never use these development rules in production.

## Production infrastructure mode

Start the local-only integration stack:

```bash
docker compose up -d
export DATABASE_URL=postgresql+asyncpg://fms_local:fms_local_only@localhost:55432/file_media_stream
.venv/bin/alembic upgrade head
```

Copy `.env.example` values into your secret-aware runtime, then set:

```bash
APP_ENV=production
FMS_INFRASTRUCTURE_MODE=production
.venv/bin/uvicorn file_media_stream_service.main:app
```

Production startup fails fast when PostgreSQL, Redis, or MinIO configuration is absent. It never
falls back to InMemory/Fake adapters. `/health` reports process liveness only; `/ready` checks all
three production dependencies and exposes only `ok` or `unavailable`.

Migration verification:

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
```

## HTTP control plane

- `GET /health`
- `GET /ready`
- `POST /api/v1/operations/execute`
- `GET /api/v1/tools`
- `GET /api/v1/tools/{tool_name}/schema`
- `POST /api/v1/tools/execute`

Media frames and file bytes never traverse these JSON endpoints. Phase 1 does not add a media
server, processor pipeline, OCR, ASR, or transcoding.

## Quality gates

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src
.venv/bin/pytest
.venv/bin/pytest --cov=src --cov-report=term-missing
.venv/bin/pytest tests/integration/production
```
