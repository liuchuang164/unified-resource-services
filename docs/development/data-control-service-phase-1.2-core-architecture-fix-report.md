# 数据库分发管控服务 Phase 1.2 核心架构修复报告

## 1. 六个架构偏离

1. 请求体 `auth_context` 被当作可信身份使用。
2. 幂等逻辑由 Application 层普通 dict 先查后写，存在并发竞态。
3. 六类数据库 Adapter 继承同一个通用内存 CRUD 实现。
4. 缺少独立 Transaction Orchestrator，事务模式只做简单判断。
5. readiness 只检查部分 Adapter，并由 API 层访问 Registry 私有字段。
6. 平台默认策略硬编码 `CASE_RECORD`、`case`、`litigation` 等业务示例。

## 2. 根因与修复方案

| 偏离 | 根因 | 修复方案 |
|---|---|---|
| 可信身份 | 请求契约混合了请求声明和认证事实 | 新增 `AuthProvider` 端口、`AuthenticatedPrincipal`、`RequestContext`，由 Header/网关注入的认证结果生成 `ExecutionContext` |
| 幂等竞态 | 幂等状态没有 Repository 边界，认领不是原子操作 | 新增 `IdempotencyRepository` 端口、内存逐作用域锁实现和 SQLAlchemy 持久化实现 |
| 通用 Adapter | Phase 1 演示骨架将六类存储抽象成一个字典 | 删除通用 CRUD Adapter，六类 Adapter 分别实现存储特定校验、作用域和数据结构 |
| 事务编排缺失 | 路由层承担了事务能力判断，但不执行事务语义 | 新增 `TransactionOrchestrator`，支持 `NONE`、`LOCAL`、`ATOMIC`、`BEST_EFFORT` |
| readiness 不可靠 | API 直接窥探 Registry 内部结构，健康检查范围不足 | Registry 暴露 `list_targets`、`list_adapters`、`validate`、`health_all`，Service 汇总 ready/degraded |
| 业务资源硬编码 | 默认策略把某一业务域当作平台事实 | 新增 `ResourceDefinition`、`ResourceMapping`、`ResourceRegistry`、`ResourceMappingRepository`，默认资源改为平台中性 demo |

## 3. 修改文件

主要修改：

- `services/data-control-service/src/data_control_service/contracts/request.py`
- `services/data-control-service/src/data_control_service/contracts/enums.py`
- `services/data-control-service/src/data_control_service/contracts/errors.py`
- `services/data-control-service/src/data_control_service/domain/models.py`
- `services/data-control-service/src/data_control_service/domain/policies.py`
- `services/data-control-service/src/data_control_service/application/context_resolver.py`
- `services/data-control-service/src/data_control_service/application/idempotency_service.py`
- `services/data-control-service/src/data_control_service/application/routing_service.py`
- `services/data-control-service/src/data_control_service/application/authorization_service.py`
- `services/data-control-service/src/data_control_service/application/transaction_orchestrator.py`
- `services/data-control-service/src/data_control_service/application/data_control_service.py`
- `services/data-control-service/src/data_control_service/api/dependencies.py`
- `services/data-control-service/src/data_control_service/api/routes/data.py`
- `services/data-control-service/src/data_control_service/api/routes/health.py`
- `services/data-control-service/src/data_control_service/app.py`
- `services/data-control-service/src/data_control_service/adapters/*.py`
- `services/data-control-service/src/data_control_service/ports/*.py`
- `services/data-control-service/src/data_control_service/infrastructure/**/*.py`
- `services/data-control-service/migrations/versions/0001_create_idempotency_records.py`
- `services/data-control-service/config/resources.example.yaml`
- `services/data-control-service/tests/**`
- `services/data-control-service/README.md`
- `docs/architecture/data-request-response-contract.md`

## 4. AuthProvider 结构

请求链路调整为：

```text
HTTP Credential / Trusted Gateway Claims
→ AuthProvider
→ AuthenticatedPrincipal
→ Request Scope Validation
→ ExecutionContext
```

当前实现状态：

- 真实生产实现：未接入。
- 内存/开发实现：`DevelopmentAuthProvider` 从受控开发 Header 读取认证事实。
- 测试实现：`TestAuthProvider` 可用于测试环境。
- 生产限制：`APP_ENV=production` 且 `AUTH_PROVIDER=development` 时启动失败。

请求体只允许声明 `tenant_id`、`biz_domain`、`actor`，不得提交可信 `roles` 或 `permissions`。服务端校验请求声明必须与认证主体一致。

## 5. 并发幂等实现

幂等唯一作用域：

```text
tenant_id + biz_domain + operation + target + idempotency_key
```

`IdempotencyRepository.claim()` 原子返回：

```text
CLAIMED
REPLAY_SUCCEEDED
IN_PROGRESS
FINGERPRINT_CONFLICT
RETRY_FAILED
```

实现状态：

- `InMemoryIdempotencyRepository`：使用逐作用域 `asyncio.Lock`，同一临界区内完成读取、判断和写入 `PROCESSING`。
- `SQLAlchemyIdempotencyRepository`：建立正式持久化接口，依赖唯一约束、`IntegrityError` 和行级锁语义。
- Alembic：创建 `idempotency_records` 表和唯一约束。
- 指纹：使用规范化 JSON 和 SHA-256，包含 operation、target、resource、payload，排除 trace/timestamp 等非业务变化字段。

## 6. 六类 Adapter 差异

| Target | 当前状态 | 存储特定约束 |
|---|---|---|
| PostgreSQL | 内存实现 | relation-like row、逻辑表、tenant/biz 自动列、受控 CRUD/BATCH、拒绝空条件更新删除 |
| MinIO | 内存实现 | server-side bucket mapping、tenant/domain prefix、生成 object key、拒绝 bucket/object_key/path/secret |
| Redis | 内存实现 | `dcs:{tenant}:{domain}:{resource}:{logical_key}` 命名空间、TTL 上限、token LOCK/UNLOCK、拒绝 raw command |
| Neo4j | 内存实现 | node/relation 独立结构、label allowlist、relation allowlist、同 scope 关系约束、拒绝 raw Cypher |
| Milvus | 内存实现 | collection mapping、vector dimension、metadata allowlist、top_k 上限、scope 过滤、余弦相似度 |
| TimescaleDB | 内存实现 | timestamp 必填、时间范围和跨度限制、tenant/biz 过滤、排序返回、BATCH 单项校验 |

## 7. Transaction Orchestrator

| 模式 | 当前支持 | 行为 |
|---|---|---|
| `NONE` | 已实现 | 单条直接执行 |
| `LOCAL` | 已实现 | 当前按单 Adapter 本地执行 |
| `ATOMIC` | 已实现 | 要求 Adapter 声明原子事务能力；内存 Adapter 用快照提交/回滚模拟 |
| `BEST_EFFORT` | 已实现 | BATCH 逐项执行，返回 `total/succeeded/failed/items[]` 且保持顺序 |
| 跨 Adapter 分布式事务 | 未实现 | 明确不伪装强一致分布式事务 |

## 8. Readiness

`GET /health/live` 只验证进程可响应。

`GET /health/ready` 汇总：

- config/app 装配状态；
- auth provider；
- policy provider；
- resource mapping repository；
- idempotency repository；
- audit repository；
- adapter registry validate；
- 所有 Adapter public health。

required Adapter 失败时 `ready=false`；optional Adapter 失败时 `ready=true` 且 `degraded=true`。响应不暴露连接地址或 Secret。

## 9. Resource Registry

平台默认注册表改为中性资源：

- `DOCUMENT_RECORD`
- `OBJECT_ASSET`
- `CACHE_ENTRY`
- `GRAPH_ENTITY`
- `VECTOR_ITEM`
- `TIME_SERIES_POINT`

业务资源应通过配置注入，示例文件位于：

```text
services/data-control-service/config/resources.example.yaml
```

核心代码不再硬编码 `CASE_RECORD`、`case`、`litigation`。

## 10. 测试命令与真实输出

```bash
.venv/bin/ruff check .
```

输出：

```text
All checks passed!
```

```bash
.venv/bin/ruff format --check .
```

输出：

```text
68 files already formatted
```

```bash
.venv/bin/mypy src
```

输出：

```text
Success: no issues found in 44 source files
```

```bash
.venv/bin/pytest -q
```

输出：

```text
54 passed in 0.12s
```

```bash
.venv/bin/pytest --cov=src --cov-report=term-missing
```

输出摘要：

```text
54 passed in 0.31s
TOTAL 1397 statements, 163 missed, 88% coverage
```

## 11. 覆盖率

总覆盖率：`88%`。

核心路径覆盖：

- dispatch pipeline；
- trusted auth scope；
- idempotency concurrency；
- adapter contracts；
- adapter-specific security；
- transaction orchestrator；
- readiness；
- layer dependency checks。

## 12. 未接入真实存储的部分

- PostgreSQL、MinIO、Redis、Neo4j、Milvus、TimescaleDB 真实驱动尚未接入。
- 默认运行依赖仍使用内存 Adapter 和内存幂等 Repository。
- SQLAlchemy 幂等 Repository 已完成接口、模型和迁移，但未作为默认生产配置启用。
- 生产级 Identity Provider 未接入。
- 跨 Adapter 分布式事务未实现，按架构明确拒绝伪装。

## 13. 已知风险

- 内存 Adapter 只适合第一阶段契约验证和本地测试，不能代表真实存储性能、锁粒度或故障模式。
- SQLAlchemy Repository 需要在目标数据库上做事务隔离级别验证。
- Resource Registry 当前提供内存配置入口，后续需要接配置中心或元数据服务。
- BEST_EFFORT 已保留成功项，调用方必须按逐项结果处理部分失败。

## 14. 最终提交 SHA

提交对象 SHA 由 Git 在提交内容确定后生成，无法在同一提交内容中自包含自身 SHA。最终准确 SHA 以本次任务完成后的验收输出和 `git log -1 --format=%H` 为准。
