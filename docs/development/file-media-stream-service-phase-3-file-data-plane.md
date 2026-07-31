# File / Media Stream Service Phase 3

## Scope

Phase 3 completes the file-resource upload, verification, download, range-access,
metadata/version, and deletion lifecycle. It does not add processing pipelines,
media servers, codecs, queues, or derived-resource processing.

## Control plane and data plane

`file.read_range` is a control-plane operation. After the normal Gateway and Unified
Entry security pipeline, it returns only:

- `reference_id`
- `resource_id`
- `offset`
- `length`
- `expires_at`

The reference is short-lived, stored in Redis with TTL, and atomically consumed once.
The binary data plane uses `GET /api/v1/files/range` with the reference in the
`X-Range-Access-Reference` header. The response is a streaming `206` response and is
not JSON. A fixed URL prevents the access log from containing the reference.

Neither plane exposes the MinIO bucket, object key, physical path, or MinIO URL.

## Upload lifecycle

1. `file.initialize_upload` creates a server-owned object key, a `PENDING_UPLOAD`
   resource, and a multipart upload session.
2. `file.complete_upload` transitions through `UPLOADING` and `VERIFYING`, completes
   MinIO multipart upload, verifies size/MIME/SHA-256 metadata, invokes the
   metadata-only `MalwareScannerPort`, creates a version row, and reaches `AVAILABLE`.
3. `file.abort_upload` atomically aborts the provider upload and moves the resource
   to `FAILED`; repeated calls return the same state.
4. `file.delete_file` moves `AVAILABLE` resources through `DELETING` to `DELETED`.

If MinIO completion succeeds but metadata persistence fails, the service records
`FILE_METADATA_SYNC_REQUIRED`. If object completion or verification fails, the
resource cannot become `AVAILABLE`.

## Persistence and isolation

`file_resource_versions` and `file_upload_sessions` are scoped by both `tenant_id`
and `biz_domain`. Repository reads and writes require that complete scope. Binary
content remains only in object storage; PostgreSQL and Redis contain metadata or
short-lived authorization state.

## Audit safety

Range audit events contain caller identity, resource ID, offset/length represented by
the pre-authorized operation, operation, and decision. Audit and structured logs must
never include file bytes, capability/reference tokens, download URLs, or object keys.
