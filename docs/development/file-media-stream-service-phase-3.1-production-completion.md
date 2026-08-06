# File / Media Stream Service Phase 3.1 Production Completion

## Scope and non-goals

Phase 3.1 closes the production file data-plane workflow on the frozen Phase 0–3
architecture. It adds multipart client access, upload-session lifecycle, complete
version management, deletion recovery, and the processor input reference contract.

It does not implement Phase 4 processing, OCR, ASR, FFmpeg, queues, derived resources,
or a new storage architecture.

## Multipart control plane and binary data plane

The authorized `file.create_upload_part_urls` control-plane operation returns only a
short-lived `upload_reference`, its part number, and expiry. The reference is stored
in Redis with TTL and is atomically consumed once. Redis receives no file content,
object key, bucket, MinIO URL, or physical path.

Binary bytes are sent with `PUT /api/v1/files/upload-part` and the reference in the
`X-Upload-Part-Reference` header. The endpoint has a fixed URL, accepts a binary body,
requires and enforces a bounded `Content-Length`, consumes the request as an async
chunk stream with backpressure, and proxies it to an internal presigned MinIO multipart
request without buffering the complete part in application memory. It returns only
ETag/part metadata. File
bytes never enter a JSON/Tool response, PostgreSQL, Redis, audit record, or message.

## Upload session lifecycle

`FileUploadSession` persists `tenant_id + biz_domain`, resource/version linkage,
provider upload ID, `total_parts`, `uploaded_parts`, timestamps, expiry, and one of:

- `INIT`
- `UPLOADING`
- `COMPLETED`
- `ABORTED`
- `EXPIRED`

Completion requires the submitted part set to match the parts accepted by the binary
data plane. Duplicate completion and abort are idempotent. Expired sessions and
expired/replayed part references fail closed.

## Version and deletion lifecycle

`file.create_version_upload` creates a server-keyed `PENDING_UPLOAD` version and its
own upload session. Successful completion verifies size, MIME type, and SHA-256 before
marking the version `AVAILABLE`. `file.switch_current_version` atomically updates the
resource's current version metadata. `file.delete_version` prevents deletion of the
current version and persists `DELETING -> DELETED` rather than removing metadata.

`file.delete_file` deletes every stored version and persists
`DELETING -> DELETED`. A MinIO failure leaves the resource/version non-available and
records `FILE_DELETE_PENDING`. It first aborts every active/expired multipart session,
so pending versions and provider multipart data do not survive file deletion. MinIO
completion followed by metadata persistence or final transaction-commit failure records
`FILE_METADATA_SYNC_REQUIRED`; a MinIO completion failure cannot produce an
`AVAILABLE` resource.

## Authorization and audit contracts

Operations map to actions explicitly:

| Operation | Required action |
| --- | --- |
| `file.initialize_upload` | `file:create_upload` |
| `file.create_upload_part_urls` | `file:upload_part` |
| `file.complete_upload`, `file.abort_upload` | `file:complete_upload` |
| `file.get_resource`, `file.get_metadata`, `file.create_download_url`, `file.read_range` | `file:read` |
| `file.create_version_upload`, `file.switch_current_version` | `file:create_version` |
| `file.delete_version` | `file:delete_version` |
| `file.delete_file` | `file:delete` |

Upload-part audit contains caller/scope, resource ID, part number, byte length,
operation, decision, result, and timing. It excludes file content, reference/token,
URL, bucket, and object key.

## Processor input contract

`ProcessorInputReference` contains only `resource_id`, `version_id`, `tenant_id`,
`biz_domain`, MIME type, checksum, and an opaque service-owned `storage_reference`.
Processors do not receive the MinIO bucket, object key, endpoint, or URL.

## Migration and verification

Migration `20260806_04` adds current-version linkage, version MIME type, nullable
checksum for pending versions, and durable upload-session lifecycle fields. Its
downgrade converts a pending version's absent checksum to an explicit all-zero unknown
marker because the previous schema cannot represent a null checksum, then restores
the old `NOT NULL` constraint.

Verified locally with Docker Desktop, PostgreSQL 16, Redis 7, and MinIO:

- `ruff check src tests`: PASS
- `ruff format --check src tests`: PASS
- `mypy src`: PASS (83 source files)
- `pytest`: PASS (121 tests)
- coverage: 90.04%
- Alembic `upgrade -> downgrade -1 -> upgrade`: PASS
- real PostgreSQL/Redis/MinIO integration: PASS
- MinIO/metadata/delete failure injection and reconciliation: PASS

The remaining warning is Starlette's upstream `TestClient` deprecation warning and
does not affect behavior.
