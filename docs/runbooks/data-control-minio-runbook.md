# 数据库分发管控服务 MinIO 运行手册

## 前置约束

- MinIO 只通过 `POST /data/dispatch` 授权访问。
- 禁止公开 `/minio/*`、Bucket 管理、任意 object key 或本地文件路径 API。
- 不提交 `.env`、`config.txt`、MinIO credentials、dump 或预签名 URL。

## 本地开发

```bash
cd services/data-control-service
docker compose -f docker-compose.minio.yml up -d
CONTROL_DATABASE_MIGRATION_URL=postgresql+psycopg://data_control:change_me@localhost:57432/dcs_control_minio alembic -c alembic-control.ini upgrade head
TARGET_DATABASE_MIGRATION_URL=postgresql+psycopg://data_control:change_me@localhost:57433/dcs_target_minio alembic -c alembic-target.ini upgrade head
CONTROL_DATABASE_URL=postgresql+asyncpg://data_control:change_me@localhost:57432/dcs_control_minio MINIO_ADAPTER_ENABLED=true MINIO_ENDPOINT=localhost:59000 MINIO_ACCESS_KEY=data_control MINIO_SECRET_KEY=change_me_123456 python scripts/bootstrap_postgresql.py
```

## Readiness

`/health/live` 不检查 MinIO。`/health/ready` 检查：

- `minio_connection`
- `minio_bucket_mapping`
- `minio_object_metadata_repository`
- `minio_adapter`

required MinIO 不可用时返回 503；optional MinIO 不可用时服务可 degraded。响应不得包含 endpoint、bucket、access key、secret key 或 object key。

## 常见故障

MinIO 不可用：

```bash
curl -f http://localhost:59000/minio/health/live
curl -i http://127.0.0.1:8000/health/ready
```

Bucket 不存在或权限错误：检查 `MINIO_DEFAULT_BUCKET`、初始化任务和 MinIO policy。服务只返回 `RESOURCE_NOT_FOUND`、`ADAPTER_AUTHENTICATION_FAILED` 或 `ADAPTER_UNAVAILABLE`，不返回 bucket 名。

上传超时或中断：`CREATE` 失败不得标记 `AVAILABLE`；`PRESIGN_UPLOAD` 上传中断保持 `PENDING_UPLOAD`，后续由 `UPLOAD_COMPLETE` 或 cleanup 处理。

Content-Type 拒绝：检查 Resource Mapping 的 `allowed_content_types`、`allowed_extensions` 和文件 magic bytes。

文件大小超限：确认 `MINIO_MAX_OBJECT_SIZE_BYTES` 和 Resource Mapping `max_object_size_bytes`。

DELETE_PENDING：确认 MinIO 可用后重试 DELETE 或执行 recovery/cleanup，不手工删除 metadata 掩盖不一致。

## Stop/Start 故障注入

只允许在专用 compose 环境执行：

```bash
docker compose -f docker-compose.minio.yml up -d
MINIO_RELIABILITY_COMPOSE=1 pytest tests/reliability/minio/test_stop_start.py -q
docker compose -f docker-compose.minio.yml down -v
```

禁止停止共享或生产 MinIO。

## Cleanup

```bash
python scripts/cleanup_minio_objects.py --dry-run
python scripts/cleanup_minio_objects.py --limit 100
```

cleanup 不跨租户，不提供公开 API，不无限循环。

## Metrics

- `minio_operation_total`
- `minio_operation_failure_total`
- `minio_operation_latency_seconds`
- `minio_connection_failure_total`
- `minio_timeout_total`
- `minio_upload_total`
- `minio_upload_failure_total`
- `minio_upload_bytes_total`
- `minio_download_authorization_total`
- `minio_delete_total`
- `minio_object_too_large_total`
- `minio_content_type_rejected_total`
- `minio_path_rejected_total`
- `minio_presigned_upload_total`
- `minio_presigned_download_total`
- `minio_orphan_object_total`

## 禁止操作

- 禁止日志记录预签名 URL。
- 禁止 Audit 保存文件内容、bucket、完整 object key 或 credentials。
- 禁止把 ETag 当作 SHA-256。
- 禁止声称 MinIO object 与 control DB metadata 强一致事务。
- 禁止使用共享 MinIO 做 stop/start。
