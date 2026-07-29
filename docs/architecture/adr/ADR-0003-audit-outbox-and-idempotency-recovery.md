# ADR-0003 Audit Outbox 与 Idempotency Recovery

## 状态

Accepted

## 背景

数据库分发管控服务在 PostgreSQL Phase 2.2 中使用独立 control database 与 target database。业务写入、幂等完成记录、审计日志不在同一个数据库事务内，因此不能声明跨库强一致。

两个需要收口的风险是：

- target 写入成功后，control 审计写入失败，导致业务数据存在但审计缺失。
- target 写入成功后，幂等 `mark_succeeded` 失败，相同 `idempotency_key` 重试可能再次写目标库。

## 决策

1. 审计写入改为 control database 内的 `audit_outbox` 事件表。
2. 请求路径在业务成功后写 outbox，`AuditOutboxProcessor.run_once()` 负责把事件物化到正式审计表。
3. Outbox worker 通过 `FOR UPDATE SKIP LOCKED` 领取事件，使用 worker lock、attempts、next_retry_at 和 FAILED 终态控制重试。
4. 幂等表新增 `RECOVERY_REQUIRED` 状态和业务结果引用字段。
5. 如果 target 写成功但 `mark_succeeded` 失败，请求会尽力把幂等记录标记为 `RECOVERY_REQUIRED`，相同 key 后续 claim 直接返回 `IDEMPOTENCY_RECOVERY_REQUIRED`，不会重新执行 adapter。
6. 管理员通过 `scripts/recover_idempotency.py` 显式诊断和恢复 recovery-required 记录。
7. Deadlock 和 serialization failure 分别映射为 `TRANSACTION_DEADLOCK` 与 `TRANSACTION_SERIALIZATION_FAILURE`，保留 PostgreSQL rollback 汇总指标。

## 结果

- 审计从请求主路径解耦，失败事件可由 processor 补偿。
- 幂等完成失败有显式、可诊断状态，避免仅依赖 PROCESSING timeout reclaim。
- 本设计是最终一致补偿，不是跨数据库二阶段提交或分布式事务。

## 非目标

- 不引入 Kafka、RabbitMQ、CDC、两阶段提交或跨 Adapter 分布式事务。
- 不通过公开 API、Header 或生产配置暴露故障注入能力。
- 不停止共享 PostgreSQL；stop/start 可靠性测试只允许使用专用 compose 环境。
