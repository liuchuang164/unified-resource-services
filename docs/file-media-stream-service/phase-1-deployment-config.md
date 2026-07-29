# Phase 1 Deployment Configuration

Modes:

- `APP_ENV=test`: InMemory/Fake adapters are allowed.
- `APP_ENV=development`: choose `FMS_INFRASTRUCTURE_MODE=inmemory` or `production` explicitly.
- `APP_ENV=production`: requires `FMS_INFRASTRUCTURE_MODE=production`.

Production requires `DATABASE_URL`, `REDIS_URL`, `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`,
`MINIO_SECRET_KEY`, and `MINIO_BUCKET`. Pool, timeout, lease, security, and presigned URL TTL
settings are documented in `.env.example`. Secrets must come from environment injection or an
external secret provider; `.env.example` contains local-only examples.

Local verification:

```bash
cd services/file-media-stream-service
docker compose up -d
export DATABASE_URL=postgresql+asyncpg://fms_local:fms_local_only@localhost:55432/file_media_stream
.venv/bin/alembic upgrade head
.venv/bin/pytest tests/integration/production
```

`GET /health` is process liveness. In production, `GET /ready` checks PostgreSQL, Redis, and MinIO
concurrently and returns only dependency names with `ok` or `unavailable`.
