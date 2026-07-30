# File / Media Stream Service Phase 2

## Scope

Phase 2 adds a media data-plane control layer without changing the frozen HTTP or Tool contract.
Control operations still enter through the Agent Gateway or business Unified Entry and pass the
same identity, authorization, replay, quota, idempotency, and audit pipeline.

Media frames remain outside PostgreSQL, Redis, JSON responses, events, logs, and audit records.

## Components

- `MediaProviderPort`: endpoint creation, start, stop, status, and health.
- `ProtocolAdapter`: maps `WEBRTC`, `RTMP`, `HLS`, `WS_AUDIO`, `WS_VIDEO`, and legacy
  `WEBSOCKET` without protocol-specific Domain branching.
- `FakeMediaProvider`: deterministic local/integration provider.
- `GenericHttpMediaProvider`: vendor-neutral HTTP adapter with bounded timeout and bearer token
  injection.
- `StreamCoordinationPort`: fencing-token lease acquisition, heartbeat, and owner-checked release.
- `StreamLifecycleService`: connected/heartbeat/recovery orchestration.

Production selects the Generic HTTP provider only when `MEDIA_PROVIDER_BASE_URL` and
`MEDIA_PROVIDER_API_TOKEN` are configured. Otherwise the provider boundary fails closed.

## Persistence

Migration `20260730_02` adds provider/session identifiers, protocol routes, connection state,
heartbeat, and fencing token to `stream_session`. It also creates tenant/domain-scoped
`stream_event`.

Stream event metadata is restricted to control-plane metadata such as connection state. It must
never contain frames, payloads, credentials, endpoint secrets, or stream keys.

## Failure and recovery

- Provider creation failure persists the session as `FAILED`, releases the Redis lease, and creates
  a reconciliation record.
- Provider success followed by repository failure stops the provider endpoint, releases the lease,
  and resolves compensation when all cleanup succeeds.
- Lost lease marks the session `FAILED` and emits `STREAM_TIMEOUT`.
- Restart recovery lists `READY`/`ACTIVE` sessions inside an explicit tenant/domain scope and checks
  the Provider. Missing provider sessions become `STREAM_RESTART_REQUIRED` reconciliation records.

## Local verification

```bash
cd services/file-media-stream-service
docker compose up -d
export DATABASE_URL=postgresql+asyncpg://fms_local:fms_local_only@localhost:55432/file_media_stream
.venv/bin/alembic upgrade head
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src
.venv/bin/pytest
.venv/bin/pytest --cov=src --cov-report=term-missing
```

No real WebRTC server, RTMP server, HLS segmenter, FFmpeg pipeline, OCR, ASR, or content analysis is
implemented in this phase.
