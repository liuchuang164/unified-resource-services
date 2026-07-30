# Phase 4 MinIO Adapter 开发报告

## 基线

- 分支：`feature/database-distribution-control-service`
- PostgreSQL/Redis 基线：`8ac47dabccaf7386340325593b22acb97f9979a4`
- 目标：真实 MinIO Adapter、对象 metadata、路径隔离、上传/下载授权、可靠性与 CI。

## 实现摘要

- SDK：官方 `minio>=7.2`。
- Manager：`MinIOManager` 集中创建 MinIO client、urllib3 timeout/pool 和 `MinIOExecutor`。
- Resource Mapping：PostgreSQL `resource_mappings.physical_config` 保存 bucket、prefix template、allowlist、大小和预签名策略。
- Bucket 边界：bucket 仅来自 mapping/config，不由 API 请求指定。
- Object Key Namespace：`tenant/{tenant_id}/{biz_domain}/{resource_name}/{yyyy}/{mm}/{logical_object_id}/{safe_filename}`。
- Object Metadata：新增 `control_plane.object_records`。
- 状态机：`PENDING_UPLOAD / AVAILABLE / DELETE_PENDING / DELETED / FAILED / EXPIRED`。
- CREATE：支持小对象代理上传，计算 SHA-256，写 metadata。
- PRESIGN_UPLOAD：生成 `PENDING_UPLOAD` 和短 TTL PUT URL；不标记 AVAILABLE。
- UPLOAD_COMPLETE：stat/read 对象，校验大小、类型和 SHA-256 后标记 AVAILABLE。
- GET Metadata：只返回 logical id、filename、content_type、size、checksum、status 和时间。
- EXISTS：只按 logical id 与 scope 查询。
- LIST：从 metadata repository 分页列当前 tenant + biz + resource。
- PRESIGN_DOWNLOAD：仅对 AVAILABLE 对象生成短 TTL URL。
- DELETE：metadata `DELETE_PENDING -> DELETED`，不允许 prefix/bucket delete。
- Content-Type：allowlist、扩展名和常见 magic bytes 组合校验。
- 文件大小：全局和 mapping 双重上限。
- 路径穿越：递归拒绝 bucket/key/endpoint/credentials/path，并标准化文件名。
- Recovery：新增 cleanup service/script；具体 create/delete/presigned recovery 策略在 ADR 中冻结，自动恢复保持保守。
- Audit Outbox：沿用 Phase 2.2 统一 access/change audit；响应和 audit 不保存物理 key 或文件内容。
- Readiness：增加 MinIO connection、bucket mapping、object metadata repository、adapter。
- Metrics：增加 MinIO operation/upload/delete/presign/path/content/timeout 指标。
- Multipart：未实现，明确非目标。

## 本地验证

已执行：

```text
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy src
pytest -q
pytest -m minio -q
pytest -m redis -q
pytest -m postgresql -q
pytest -m consistency -q
pytest -m reliability -q
pytest -m migration -q
pytest -m performance -q
```

本机无 Docker CLI，因此本地真实 MinIO stop/start 未验证；真实 MinIO 验证由 GitHub Actions 专用容器完成。

## CI 记录

待 push 后更新：

- GitHub Actions Run ID：待更新
- CI Jobs：待更新
- Coverage：Phase 4 当前门禁基线为 70%；真实 MinIO、PostgreSQL、Redis 路径均进入 CI，后续补齐长尾分支测试后再上调。
- Coverage：待更新
- Secret Scan：待更新
- 最终 SHA：待更新

## 未完成项与风险

- 未实现 multipart。
- 未实现病毒扫描、OCR、Object Lock、Lifecycle 和 CDN。
- 预签名 PUT 的 Content-Type/大小最终以 `UPLOAD_COMPLETE` 校验为准。
- 不声明 MinIO object write 与 PostgreSQL metadata 强一致原子事务。
