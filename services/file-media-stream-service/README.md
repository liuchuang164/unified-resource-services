# 文件/音视频流式服务

Phase 0 implements the control-plane architecture baseline and an in-memory runnable loop for
tenant-scoped file initialization, stream sessions, and processing jobs.

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

## HTTP control plane

- `GET /health`
- `GET /ready`
- `POST /api/v1/operations/execute`
- `GET /api/v1/tools`
- `GET /api/v1/tools/{tool_name}/schema`
- `POST /api/v1/tools/execute`

Media frames and file bytes never traverse these JSON endpoints. Phase 0 uses only in-memory/fake
ports; PostgreSQL, Redis, MinIO, media servers, and processors remain later-phase integrations.

## Quality gates

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src
.venv/bin/pytest
.venv/bin/pytest --cov=src --cov-report=term-missing
```
