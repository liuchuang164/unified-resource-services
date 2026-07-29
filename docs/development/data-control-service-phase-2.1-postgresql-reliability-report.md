# 数据库分发管控服务 Phase 2.1 PostgreSQL 可靠性报告

## 1. 阶段目标

在 Phase 2 真实 PostgreSQL 控制面和 Adapter 基础上，补齐 migration 拆分、基础故障注入、readiness、可靠性测试、CI 配置、运行手册和报告。

## 2. Phase 2 基线

- Phase 1.2 基线：`a55c84bbf50cccb1299187d80f9e7a318e70ca87`
- Phase 2 网关验证提交：`5db951fad399bc4cbdabc283bfe13a7274f5c036`

## 3. Migration 拆分

已拆分为：

- `alembic-control.ini` -> `migrations/control`
- `alembic-target.ini` -> `migrations/target`

Control head：`0004`。Target head：`target_0001`。

旧 `alembic.ini` 已标记 deprecated，并指向 `migrations/legacy_phase2_combined`。

## 4. ADR

新增 `docs/architecture/ADR-0002-control-target-migration-separation.md`，记录拆分原因、既有库影响、stamp 过渡和回滚策略。

## 5. DatabaseManager

已具备 AsyncEngine、AsyncSession、`pool_pre_ping`、pool 配置、connect timeout、statement timeout、readiness ping、migration revision 检查、dispose 和连接信息脱敏。test 环境使用 `NullPool` 仅用于 pytest 多事件循环隔离，不用于 pool exhaustion 测试。

## 6. PostgreSQL 停止与恢复

已在 gateway server 创建本任务专用 PostgreSQL 16 容器，未停止共享业务容器。容器级 stop/start 自动化测试尚未提交到默认 CI；不得声称该项 GitHub CI 已验证。

## 7. Readiness 状态转换

Readiness 状态改为 `READY / DEGRADED / NOT_READY`。`NOT_READY` 返回 HTTP 503。组件包含 control/target database 与 migration 检查。

## 8. Statement Timeout

已在 gateway server 专用 PostgreSQL 16 上真实验证：`statement_timeout=100ms`，测试事务中 `pg_sleep(1)` 超时，映射为 `ADAPTER_TIMEOUT`，事务回滚，后续查询恢复。

## 9. Pool Exhaustion

已在真实 PostgreSQL 上用 `pool_size=1,max_overflow=0,pool_timeout=1` 验证：占用唯一连接后第二次 ping 返回 `ADAPTER_UNAVAILABLE`，释放连接后恢复。

## 10. Deadlock

已在真实 PostgreSQL 上用两个事务交叉锁两行制造 deadlock，映射为 `TRANSACTION_ROLLED_BACK`，后续 ping 正常。

## 11. Serialization Failure

已在真实 PostgreSQL 上用两个 SERIALIZABLE 事务更新同一行制造 serialization failure，映射为 `TRANSACTION_ROLLED_BACK`，不做无限自动重试。

## 12. 事务中断

已验证 statement timeout 场景下事务回滚且无业务数据残留。连接中断/容器停止于事务中间的自动化测试尚未完成。

## 13. 审计失败

当前写操作仍按 fail-closed 策略设计；跨 control/target database 不声称强一致。真实 audit insert failure 和 outbox 尚未实现。

## 14. Audit Outbox

未实现。原因：本阶段先完成 migration 分离和基础 PostgreSQL 可靠性门禁；跨库审计强一致需要独立 outbox 状态机、补偿处理器和运维告警，不应以半成品伪装完成。

## 15. Idempotency Completion Failure

当前依赖业务唯一约束与 PROCESSING timeout reclaim 防止永久挂死；尚未实现 completion outbox 或自动业务结果探测。不得声称跨库 completion 强一致。

## 16. Recovery 机制

已保留 PROCESSING timeout reclaim。`RECOVERY_REQUIRED` 和自动 Recovery Worker 尚未实现。

## 17. Fault Injection

已增加 tests/reliability/postgresql 下真实数据库故障测试。没有通过公开 API、Header 或生产配置暴露故障注入。

## 18. Metrics

新增内存 metrics registry，覆盖：

- `postgresql_pool_timeout_total`
- `postgresql_statement_timeout_total`
- `postgresql_deadlock_total`
- `postgresql_serialization_failure_total`
- `postgresql_connection_failure_total`
- `postgresql_transaction_rollback_total`
- `readiness_state`

## 19. 性能测试环境

新增 `scripts/benchmark_postgresql.py`，支持开发环境 JSON 输出。已在 gateway server 专用 PostgreSQL 16 上执行小样本脚本验证：

```text
python scripts/benchmark_postgresql.py --serial-count 5 --replay-count 5 --json
```

结果：`serial_get`、`serial_upsert`、`idempotency_replay` 均 `success=5, failed=0`。

尚未执行任务要求的完整 10 项性能基线；当前结果只证明脚本可运行和小样本错误率为 0，不作为生产性能结论。

## 20. GitHub Actions

已更新 workflow：双数据库、control/target migration、ruff、format、mypy、默认测试、PostgreSQL 集成、reliability、coverage、secret scan。推送后需要读取 GitHub Actions run 结果。

## 21. 本地 / Gateway 测试结果

本地无 PostgreSQL：

```text
pytest -q
60 passed, 10 skipped
```

Gateway server 专用 PostgreSQL 16：

```text
pytest -m postgresql -q
8 passed, 62 deselected

pytest -m reliability -q
4 passed, 66 deselected

pytest -m migration -q
2 passed, 68 deselected

coverage report --fail-under=85
TOTAL 2833 statements, 371 missed, 87% coverage
```

## 22. 未完成项

- 容器 stop/start 恢复测试未进入 CI。
- audit outbox 未实现。
- idempotency completion failure recovery worker 未实现。
- 事务中途连接 kill 场景未自动化。
- 完整 10 项性能基线未执行。
- GitHub Actions 远程通过结果待推送后确认。

## 23. 已知风险

- Control 与 target 分库时，业务写入和审计/幂等 completion 不能跨库强一致。
- 旧 combined migration 仅作过渡参考，新环境不得继续使用。
- 内存 metrics 未暴露 Prometheus endpoint。

## 24. 最终提交 SHA

最终 SHA 以任务完成后的 `git rev-parse HEAD` 为准。
