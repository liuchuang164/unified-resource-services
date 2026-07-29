# Phase 0 Open Questions

以下事项保持 Port/契约边界，不阻塞 Phase 0，也未擅自选型：

1. 生产媒体服务器采用 ZLMediaKit、SRS、Janus、LiveKit 或其他实现；
2. OCR、ASR、转码能力经内部处理服务还是 External Access Service；
3. PostgreSQL 元数据 schema、Redis idempotency/replay TTL 与事务/outbox 边界；
4. MinIO/S3 上传初始化的正式预签名策略、最大时长和 multipart 限制；
5. reconciliation worker 的周期、状态真值优先级和孤儿资源清理 SLA；
6. API 文档中历史 `/media/dispatch` 与本次冻结
   `/api/v1/operations/execute` 的长期兼容/别名策略。
7. Phase 0 在上传初始化阶段拒绝双扩展并保留 `PENDING_UPLOAD`；实际 MIME 内容嗅探、恶意文件
   扫描及 `QUARANTINED` 决策由后续上传完成阶段实现。
