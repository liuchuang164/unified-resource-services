# ADR-0005: MinIO 对象存储契约

- 状态：Accepted
- 日期：2026-07-30
- 分支：`feature/database-distribution-control-service`
- 基线：Redis Phase 3 commit `8ac47dabccaf7386340325593b22acb97f9979a4`

## 决策

1. SDK 选择：采用官方 `minio>=7.2` Python SDK。该 SDK 为同步接口，因此所有 SDK 调用都通过 `MinIOExecutor` 的受控线程池执行，不在 FastAPI async 链路直接阻塞。
2. Bucket 管理边界：运行时 Adapter 不提供 Bucket 管理 API。Bucket 由平台配置和环境初始化，readiness 只检查 bucket 存在和权限。
3. Object Key Namespace：对象 key 由 `MinIOObjectKeyBuilder` 生成，默认格式为 `tenant/{tenant_id}/{biz_domain}/{resource_name}/{yyyy}/{mm}/{logical_object_id}/{safe_filename}`。
4. 客户端不能传 bucket/key：bucket、object_key、endpoint、access_key、secret_key、本地路径和物理路径均被边界校验递归拒绝，避免跨租户和路径穿越。
5. 上传边界：`CREATE` 支持小对象代理上传；大对象优先走 `PRESIGN_UPLOAD`，随后必须 `UPLOAD_COMPLETE`。
6. Content-Type 验证：同时校验 Resource Mapping allowlist、全局 allowlist、文件扩展名和常见格式 magic bytes。默认拒绝可执行内容。
7. 大小限制：同时受 Resource Mapping 与全局 `MINIO_MAX_OBJECT_SIZE_BYTES` 约束；完成确认时再次校验实际大小。
8. 状态机：控制面 `object_records` 记录 `PENDING_UPLOAD / AVAILABLE / DELETE_PENDING / DELETED / FAILED / EXPIRED`。
9. 幂等：`CREATE / DELETE / PRESIGN_UPLOAD / UPLOAD_COMPLETE` 继续使用 PostgreSQL control-plane idempotency；相同 key replay 返回原结果，冲突由通用 fingerprint 处理。
10. 最终一致性：MinIO object write 与 PostgreSQL metadata 不声明强一致事务，依赖状态机、幂等、Audit Outbox 和 recovery/cleanup。
11. Recovery Strategy：通过 `logical_object_id`、object record、MinIO `stat_object`、size、checksum 和状态判断是否已执行；未知状态禁止自动重复上传。
12. DELETE 语义：先标记 `DELETE_PENDING`，删除对象后标记 `DELETED`；重复 DELETE 通过幂等 replay 或 DELETED 状态返回稳定结果。
13. Multipart：本阶段不实现 multipart API。超过代理上传能力的对象应使用预签名上传；报告和 runbook 明确该限制。
14. Presigned URL 安全：URL 短 TTL，仅单对象方法授权，不写入长期审计正文，不进入 metrics，不返回 bucket/key/credentials。
15. 尚未解决风险：预签名 PUT URL 本身不能强制所有客户端都提交正确 Content-Type 和大小，最终以 `UPLOAD_COMPLETE` 的真实 stat/read 校验为准；未实现病毒扫描、Object Lock、Lifecycle 和 multipart abort 平台。
