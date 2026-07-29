# 数据库分发管控服务 Phase 2 PostgreSQL 报告

## 1. Phase 2 目标

在保持 Phase 1.2 架构边界的前提下，接入 PostgreSQL 控制面持久化和真实 PostgreSQL Adapter 路径。其他五类 Adapter 不做真实接入。

## 2. 架构依据

依据 `AGENTS.md`、`docs/governance/vibe-coding-constraints.md`、`docs/architecture/*`、Phase 1.2 报告和本阶段任务说明。当前分支包含 Phase 1.2 基线提交 `a55c84bbf50cccb1299187d80f9e7a318e70ca87`。

## 3. 实际完成内容

- 新增 SQLAlchemy Async `DatabaseManager`。
- 新增 PostgreSQL 错误映射。
- 新增控制面 ORM 模型：idempotency、access audit、change audit、resource mapping、policy binding。
- 新增示例目标表模型：`data_target.platform_records`。
- 新增 Alembic env 和 `0001` 到 `0005` migration chain。
- 新增 PostgreSQL 幂等 Repository，支持唯一约束、row lock、owner token 和 timeout reclaim。
- 新增 PostgreSQL 审计、Resource Mapping、Policy Binding Repository。
- 新增 `SQLAlchemyPostgreSQLAdapter`，保留 `InMemoryPostgreSQLAdapter` 给单元测试。
- 新增 Docker Compose、bootstrap 脚本、GitHub Actions workflow 和 PostgreSQL marker 测试基架。
- 补充 SQLAlchemy async PostgreSQL 运行依赖 `greenlet`。
- 测试环境下 `DatabaseManager` 使用 `NullPool`，避免 pytest 多事件循环复用 asyncpg 连接。

## 4. 最终目录结构

```text
services/data-control-service/
├── docker-compose.postgresql.yml
├── migrations/
│   ├── env.py
│   └── versions/0001..0005
├── scripts/
│   ├── init-postgresql.sql
│   └── bootstrap_postgresql.py
├── src/data_control_service/infrastructure/persistence/
│   ├── database.py
│   ├── errors.py
│   ├── models/
│   └── repositories/
└── tests/
    ├── integration/postgresql/
    ├── security/postgresql/
    ├── concurrency/postgresql/
    └── migrations/
```

## 5. 控制面数据库设计

控制面 schema：`control_plane`。

表：

- `idempotency_records`
- `access_audit_logs`
- `change_audit_logs`
- `resource_mappings`
- `policy_bindings`

目标示例 schema：`data_target`。

表：

- `platform_records`

开发环境可在同一 PostgreSQL 实例中运行；生产应使用独立 control database 和 target database 配置。

## 6. 表结构

`idempotency_records` 包含 scope、fingerprint、status、response_snapshot、error_code、owner_token、timestamps。

`access_audit_logs` 记录 request/trace、tenant/biz、actor、operation、target、逻辑资源、策略结果、HTTP 状态、错误码、延迟和 metadata digest。

`change_audit_logs` 记录写操作变更摘要和 changed_fields，不保存完整敏感 payload。

`resource_mappings` 保存逻辑资源到受信物理 schema/table/column/allowlist 的映射。

`policy_bindings` 保存 ALLOW/DENY 策略绑定，默认 deny 由 Policy Repository 决策体现。

`platform_records` 是平台中性的 PostgreSQL 示例业务表，包含 tenant、biz_domain、external_id、record_type、content、attributes、version 和 soft delete 字段。

## 7. 索引和唯一约束

- `uq_idempotency_scope`
- `ix_idempotency_expires_at`
- `ix_idempotency_status`
- `ix_idempotency_tenant_biz`
- `ix_idempotency_processing_started_at`
- `ix_access_audit_request_id`
- `ix_access_audit_trace_id`
- `ix_access_audit_tenant_created`
- `ix_change_audit_request_id`
- `ix_change_audit_tenant_created`
- `uq_resource_mapping_version`
- `ix_resource_mapping_current`
- `ix_policy_binding_scope`
- `uq_platform_records_external_scope`
- `ix_platform_records_scope`
- `ix_platform_records_updated_at`

## 8. Alembic revisions

- `0001_create_idempotency_records`
- `0002_create_audit_tables`
- `0003_create_resource_mappings`
- `0004_create_policy_bindings`
- `0005_create_platform_records`

已通过用户提供的 gateway server 上 PostgreSQL 16 实例执行 migration 验证。本地 Python 3.12 通过 SSH tunnel 连接远端 PostgreSQL，control database 和 target database 均完成：

```text
alembic current
alembic downgrade -1
alembic upgrade head
alembic current
```

最终结果：

```text
0005 (head)
0005 (head)
```

## 9. 幂等 claim 算法

`SQLAlchemyIdempotencyRepository.claim()`：

1. 先 insert PROCESSING。
2. 成功则 `CLAIMED`。
3. 唯一冲突后按 scope `SELECT ... FOR UPDATE`。
4. fingerprint 不同返回 `FINGERPRINT_CONFLICT`。
5. SUCCEEDED 返回 `REPLAY_SUCCEEDED`。
6. PROCESSING 未超时返回 `IN_PROGRESS`。
7. PROCESSING 超时或 FAILED 使用新 owner token 原子恢复。

## 10. owner token 和超时恢复

`mark_succeeded` / `mark_failed` 必须匹配 record id、owner token 和 PROCESSING 状态；不属于当前 owner 的完成请求不会覆盖记录。

## 11. 审计持久化

已实现 `SQLAlchemyAuditRepository`。成功/失败均写 access audit；写操作成功后写 change audit。审计记录保存 digest，不保存 token、密码、连接串、raw SQL 或完整 payload。

## 12. Resource Mapping

已实现 `SQLAlchemyResourceMappingRepository`，按 tenant、biz_domain、target、resource_type、resource_name 查询当前启用版本，物理 schema/table/allowlist 只来自数据库配置。

## 13. Policy Binding

已实现 `SQLAlchemyPolicyRepository`，按 scope 查询策略并按 priority 决策；默认 deny。当前没有外部策略管理 API，bootstrap 脚本用于 development/test 初始化。

## 14. PostgreSQL Adapter

`SQLAlchemyPostgreSQLAdapter` 使用 SQLAlchemy Core 构造参数化语句，不接受调用方 SQL、schema、table、where_sql、order_by_sql 等字段。所有操作强制 tenant_id + biz_domain scope，软删除默认不可见。

## 15. 操作支持矩阵

| Operation | 状态 |
|---|---|
| CREATE | 已实现真实 PostgreSQL 路径 |
| GET | 已实现真实 PostgreSQL 路径 |
| LIST | 已实现 allowlist filter/sort/page limit |
| UPDATE | 已实现 scope、field allowlist、version 条件 |
| UPSERT | 已实现受控 conflict target |
| DELETE | 已实现 scope soft delete |
| BATCH | Orchestrator 支持；Adapter 内直接 BATCH 占位，真实逐项由 Orchestrator 拆解 |

## 16. 事务支持矩阵

| 模式 | 状态 |
|---|---|
| NONE | 单条独立事务 |
| LOCAL | 单 Adapter 本地执行 |
| ATOMIC | `begin/commit/rollback` 使用同一 AsyncSession transaction |
| BEST_EFFORT | Orchestrator 逐项执行，失败项独立返回 |
| 跨 database 原子性 | 未实现，不声称支持 |

## 17. 多租户隔离

Adapter 层对 GET/LIST/UPDATE/DELETE/UPSERT 强制 scope 条件；CREATE 注入 tenant_id/biz_domain；payload/query 中覆盖 tenant_id/biz_domain 会拒绝。

## 18. 错误映射

`PostgreSQLErrorMapper` 映射 unique/check/not-null/fk、serialization/deadlock、timeout、connection/pool 类错误到统一错误码。不会向 API 返回 asyncpg/SQLAlchemy 原始异常。

## 19. readiness

配置 PostgreSQL URL 后，ready 检查会调用 control database ping、target database ping、持久化 repository health 和 Adapter health。响应不返回 host、port、database、username 或 URL。

## 20. Docker Compose

新增 `docker-compose.postgresql.yml`，使用 PostgreSQL 16，开发测试密码为 `change_me`，并通过 init SQL 创建 `data_target` database。

## 21. CI

新增 `.github/workflows/data-control-service.yml`，包含 lint、format、mypy、unit tests、PostgreSQL integration tests、migration downgrade/upgrade、coverage、secret scan。

本地无法验证 GitHub CI 实际运行结果；不能把 workflow 定义等同于 CI 已通过。

## 22. 单元测试

本机执行：

```text
60 passed, 4 skipped in 0.15s
```

## 23. PostgreSQL 集成测试

通过 gateway server 上 PostgreSQL 16 实例执行：

```text
pytest -m postgresql -q
.... [100%]
4 passed, 60 deselected in 3.61s
```

## 24. 并发测试

新增 `tests/concurrency/postgresql/test_postgresql_idempotency_concurrency.py`，用于真实 PostgreSQL 两个独立 Repository 实例并发 claim。该用例已在 gateway server PostgreSQL 16 上随 `pytest -m postgresql` 执行通过。

## 25. migration 测试

已新增 Alembic env 和 migration chain；control database 与 target database 均已在 gateway server PostgreSQL 16 上执行 `current -> downgrade -1 -> upgrade head -> current` 并回到 `0005 (head)`。

## 26. 故障测试

已实现错误映射单元测试，并在真实 PostgreSQL 上覆盖连接、Repository、Adapter 安全拒绝、并发幂等 claim。PostgreSQL 停止/重启、statement timeout、pool timeout、migration 未执行、audit insert 失败等故障注入测试尚未执行。

## 27. 覆盖率

本机 Python 3.12 + gateway server PostgreSQL 16 组合执行：

```text
coverage run -m pytest -q
coverage run --append -m pytest -m postgresql -q
coverage report --fail-under=85
```

结果：

```text
TOTAL 2600 statements, 324 missed, 88% coverage
```

已达到 Phase 2 要求的 85%。未通过 omit 核心代码掩盖。

## 28. 性能基础结果

本阶段完成 PostgreSQL 16 功能正确性、migration 往返、并发幂等基础验证；未执行正式性能压测，不能对外声称生产性能容量。

## 29. 未完成项

- PostgreSQL 停止/重启和故障恢复测试未执行。
- 性能基础验证未执行。
- GitHub CI workflow 已新增，但未获得远程 CI 通过证据。

## 30. 已知风险

- 当前 `platform_records` 目标表 migration 和 control-plane migration 在同一 Alembic chain 中，生产拆分为两个 database 时需要分别执行或拆分 Alembic 配置。
- 跨 control database 与 target database 的审计/业务写入不能强一致，本实现不声称跨 database 原子性。
- `SQLAlchemyPostgreSQLAdapter` 已有真实 CRUD 路径，但仍需补齐更完整的 rollback、timeout、deadlock、pool exhaustion 测试。

## 31. 最终提交 SHA

提交 SHA 由最终 Git commit 生成，以任务最终输出和 `git rev-parse HEAD` 为准。
