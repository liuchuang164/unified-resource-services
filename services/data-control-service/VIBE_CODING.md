# Data Control Service — Vibe Coding 执行方案

本文件可直接作为 Codex 的阶段任务书。开始编码前必须先阅读：

1. 仓库根 `AGENTS.md`；
2. 本目录 `AGENTS.md`；
3. 根 `README.md`；
4. 本目录 `README.md`。

`AGENTS.md` 中的 MUST / 禁止项优先级高于本文件。

## 1. 总目标

实现一个可独立部署的数据库分发管控服务：

```text
Agent → Data Access Gateway → 统一数据入口 → Adapter
业务服务 ───────────────→ 统一数据入口 → Adapter
```

需要证明：

- Agent Tool 接口只是协议适配层；
- 两类调用方在同一个统一入口执行权限、策略、幂等、路由和审计；
- 新增 Tool/Operation 不修改核心流水线；
- 数据先按租户隔离，再按租户内业务隔离；
- 越权被硬拒绝且没有副作用；
- 服务可以独立构建、部署、迁移和扩缩容。

## 2. 工作方式

每个 Phase 必须：

1. 输出简短文件级计划；
2. 只实现当前 Phase；
3. 实际运行 lint、typecheck 和相关测试；
4. 修复全部失败；
5. 更新 README/契约/验收清单；
6. 提交小而可审查的 Commit；
7. 不伪造测试输出。

不要在第一个垂直切片前创建万能 Policy Engine、万能 Repository 或所有数据库的抽象层。

## Phase 0 — 已有公共骨架复核

目标：确认 Monorepo、TypeScript strict 和最小公共包可用。

任务：

- 检查 workspace；
- 检查 `contracts`、`common-errors`、`capability-token-sdk`、`observability`、`test-kit`；
- 不要立即扩充公共包；
- 将当前原生 HTTP 健康检查替换为正式 Web Framework 时，保持接口不变；
- 添加服务自己的测试配置和配置加载器；
- 添加 `/health/live`、`/health/ready`、`/metrics`。

Gate：

```bash
pnpm lint
pnpm typecheck
pnpm --filter @urs/data-control-service build
```

## Phase 1 — PostgreSQL 最小垂直切片

只实现一条真正可运行链路，不做其他数据库。

建议 Demo Operation：

```text
DEMO_RECORD_UPSERT
DEMO_RECORD_GET
```

服务自有 Demo 表：

```text
controlled_record(
  tenant_id,
  biz_domain,
  resource_type,
  resource_id,
  payload,
  created_at,
  updated_at
)
```

必须实现：

```http
GET  /api/v1/data/operations
GET  /api/v1/data/operations/{operation}/schema
POST /api/v1/data/dispatch
```

执行链：

```text
Schema
→ Trusted TenantBizContext
→ Permission Stub with fail-closed contract
→ Policy Stub with explicit decision
→ Idempotency
→ Static Route Rule for PostgreSQL
→ PostgreSQL Adapter
→ Audit + Outbox
→ Response
```

测试矩阵：

```text
tenant_A + LEGAL + case_001
tenant_A + ROBOT_DOG + case_001
tenant_B + LEGAL + case_001
```

同名资源必须完全隔离。Repository API 必须要求 `TenantBizScope` 参数，不能存在无 Scope 的 `findById(resourceId)`。

Gate：单元、契约、PostgreSQL 集成和越权测试通过。

## Phase 2 — Registry 与插件化扩展

实现：

```text
ToolRegistry
OperationRegistry
AdapterRegistry
TrustedPluginLoader
```

要求：

- Registry 重复键启动失败；
- 一个可信插件文件可以注册 Tool Action 和 Operation；
- 新增 Operation 不修改 Controller 和 Dispatch Pipeline；
- 新增已有 Adapter 上的 Tool 不修改 Adapter；
- 插件清单可观察；
- 不允许请求指定模块路径；
- 插件失败导致 readiness 失败；
- 为新增插件写自动发现测试。

完成后，将 Phase 1 的 Operation 改为插件注册，而不是硬编码。

## Phase 3 — Data Access Gateway

实现：

```http
GET  /api/v1/dag/tools
GET  /api/v1/dag/tools/{tool_name}/schema
POST /api/v1/dag/tools/execute
```

要求：

- Tool Action 映射 Phase 1 Operation；
- Gateway 只做 Tool 协议和请求转换；
- 通过 Application Service 调统一入口，不做 HTTP 自调用；
- Agent 路径和 Business 路径产生相同的数据权限、路由和数据结果；
- Tool list/schema 按当前 Capability Context 过滤；
- ToolResponse 保留 request_id / trace_id / audit reference。

负向测试：未知 Tool、未知 Action、Action 未授权、Token 错租户、Token 错业务、Replay。

## Phase 4 — 租户优先路由引擎

实现版本化 `data_route_rule`、Route Resolver 和 Route Audit。

必须支持并测试：

```text
SHARED_TABLE
TENANT_SCHEMA
TENANT_DATABASE
```

优先级：

```text
tenant+biz+operation+resource
tenant+biz+operation
tenant+biz
tenant
platform topology default
```

平台默认规则不得移除租户业务过滤。Schema/Database 名称由受控 Tenant Key 映射生成，禁止直接拼接原始 ID。

测试：

- 精确规则覆盖默认规则；
- 禁用规则不生效；
- Route 目标未注册时拒绝；
- 两个并发更新使用版本/乐观锁；
- Route 变更有审计和回滚信息。

## Phase 5 — MinIO Adapter

实现受控对象操作：

```text
LIST_OBJECTS
GET_OBJECT_METADATA
CREATE_PRESIGNED_UPLOAD
CREATE_PRESIGNED_DOWNLOAD
PUT_METADATA
```

必须由服务端生成：

```text
tenants/{tenant_key}/{biz_domain}/...
```

禁止调用方突破 Prefix。测试 `../`、编码穿越、猜测其他租户 object key、跨业务 Prefix。

大对象内容不写 PostgreSQL Audit；只记录 Hash、大小、MIME 和对象引用。

## Phase 6 — Neo4j、Milvus、Redis、TimescaleDB

每个 Adapter 分独立小阶段完成，不允许一次性生成全部实现。

每个 Adapter 都必须先定义：

- 支持的受控 Operation；
- 租户业务过滤如何在存储执行层强制；
- 最大结果和超时；
- 取消语义；
- 错误归一化；
- 集成测试容器；
- 负向隔离测试。

Milvus 特别要求：不得全局向量召回后应用层过滤。

Neo4j 特别要求：不得执行任意 Cypher。

Redis 特别要求：所有 Key/Lock/Idempotency 都有租户业务命名空间。

## Phase 7 — Capability Token 与安全强化

将 Phase 1 权限 Stub 替换为真实验签与授权链：

```text
签名
aud/iss
expiry
jti
agent/session/task
tenant/biz
tool/action
resource/data scope
replay / revocation
```

业务服务路径采用正式服务身份和可信上下文，不要求伪装成 Agent Token。

完成安全负向矩阵，并验证每次拒绝：

```text
API 拒绝
零业务副作用
DENY Audit
Trace 可关联
```

## Phase 8 — 事务、Outbox、恢复与故障测试

实现：

- Audit/Outbox 一致性；
- 幂等恢复；
- Adapter 超时与取消；
- 只对幂等操作重试；
- PostgreSQL、Redis、MinIO 短暂故障；
- 并发写与重复请求；
- 服务重启后幂等和 Outbox 恢复；
- readiness 反映关键依赖或 Route 可用性。

不要宣称跨 PostgreSQL、MinIO、Neo4j、Milvus 的分布式 ACID；需要跨资源编排时明确使用 Saga/Outbox。

## Phase 9 — 独立部署与验收

必须证明：

```bash
pnpm --filter @urs/data-control-service build
pnpm --filter @urs/data-control-service typecheck
```

并提供：

- 独立 Dockerfile；
- 服务自己的迁移命令；
- OpenAPI 3.1；
- `/health/live`、`/health/ready`、`/metrics`；
- Kubernetes/Helm 定义；
- 最小权限 Secret 引用；
- 资源限制；
- 滚动升级和迁移说明；
- 脱敏验证报告。

## 3. 建议首轮 Codex 启动提示

```text
你现在负责 unified-resource-services 中的 data-control-service。

先完整阅读根 AGENTS.md、根 README.md、services/data-control-service/AGENTS.md、README.md 和 VIBE_CODING.md。

只执行 Phase 0 和 Phase 1，不要提前实现其他数据库，不要创建万能共享框架。

先输出文件级计划，然后实现 PostgreSQL 的 DEMO_RECORD_UPSERT / DEMO_RECORD_GET 垂直切片。Agent Tool API 暂不在 Phase 1 实现，但 Application Service 必须允许 Phase 3 复用。

必须使用 tenant_A+LEGAL、tenant_A+ROBOT_DOG、tenant_B+LEGAL，并让不同 Scope 都拥有 case_001，证明 Repository 和 SQL 在执行层强制 tenant_id + biz_domain。

完成后运行 lint、typecheck、unit、contract、integration、security tests，修复所有失败，更新文档并提交清晰 commit。不要只输出建议，开始实际编码。
```

## 4. 每次提交检查清单

- [ ] 未违反 Data Access Gateway / 统一入口 / Adapter 三层边界；
- [ ] 没有服务间源码导入；
- [ ] 没有为了本服务专属逻辑修改公共包；
- [ ] tenant_id + biz_domain 在存储执行层生效；
- [ ] 写操作有幂等；
- [ ] 拒绝有 DENY Audit 且零副作用；
- [ ] 没有任意 SQL/Cypher/路径；
- [ ] 没有 Secret 或敏感日志；
- [ ] lint/typecheck/tests 真实运行；
- [ ] README、OpenAPI、Migration 同步更新；
- [ ] Commit 小而可审查。
