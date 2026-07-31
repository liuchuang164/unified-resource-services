# Data Access Gateway MinIO Phase 1

## Scope

This phase adds the Agent Tool protocol layer in front of the existing database distribution
control service. The first registered Tool is `minio_file_access`.

The Gateway is a separate service under `services/data-access-gateway`. It never imports the MinIO
SDK, never receives MinIO credentials and never calls MinIO directly.

## Interfaces

- `GET /dag/tools`
- `GET /dag/tools/{tool_name}/schema`
- `POST /dag/tools/execute`
- `GET /health/live`
- `GET /health/ready`

The data control service also exposes logical discovery endpoints:

- `GET /data/operations`
- `GET /data/operations/{operation}/schema`

These endpoints do not return physical tables, Bucket names, Object Keys or credentials.

## Registered MinIO actions

| Tool action | Data operation |
|---|---|
| `list_objects` | `LIST` |
| `get_object_metadata` | `GET` |
| `object_exists` | `EXISTS` |
| `upload_inline` | `CREATE` |
| `create_upload_url` | `PRESIGN_UPLOAD` |
| `complete_upload` | `UPLOAD_COMPLETE` |
| `create_download_url` | `PRESIGN_DOWNLOAD` |
| `delete_object` | `DELETE` |

`upload_local_file`, server-local download paths, arbitrary Bucket/Object Key access and direct
text-body reads are intentionally excluded.

## Authentication

The Agent supplies a short-lived Capability Token in `Authorization: Bearer`. The Gateway validates
the Tool and Action scope, then forwards the same token to the data control service. The data
control service validates the token again and checks that the resulting principal matches the
`DataRequest.auth_context`.

HS256 is limited to development and test. Production configuration rejects symmetric capability
tokens and requires an asymmetric public verification key.

## Idempotency ownership

The Gateway has no business idempotency repository, state machine or result cache. It only forwards
an explicit `idempotency_key` or deterministically derives one from the stable Tool call identity.

`POST /data/dispatch` remains the single owner of claim, request digest, concurrency handling,
conflict detection, result replay and recovery.

## Verification evidence

Local verification at implementation time:

- Gateway Ruff: passed.
- Gateway format check: passed.
- Gateway Mypy: passed.
- Gateway tests: `27 passed`.
- Gateway coverage: `83.45%`.
- Data control service regression: `108 passed, 24 skipped`.
- Data control service Mypy: passed.

The full-chain contract test validates:

```text
Capability Token
  -> ToolRequest
  -> MinIO Tool Registry
  -> DataRequest
  -> data-control-service authentication
  -> authorization
  -> idempotency
  -> MinIO Adapter
  -> ToolResponse
```

The local full-chain test uses the existing in-memory MinIO Adapter.

Gateway server verification used the full Docker deployment and the configured real PostgreSQL,
Redis and MinIO services. It confirmed:

- both service readiness endpoints return `READY`;
- Tool discovery returns `minio_file_access` with eight actions;
- `upload_inline` reaches the real MinIO Adapter successfully;
- repeating the same Tool call returns `idempotency_replayed=true`;
- `object_exists` succeeds for the uploaded logical object;
- Tool responses contain no Bucket, Object Key, endpoint, credential or local path fields.
