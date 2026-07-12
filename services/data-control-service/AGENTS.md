# AGENTS.md — Data Control Service

本文件适用于 `services/data-control-service/**`，并继承仓库根目录 `AGENTS.md`。这是 Codex、AI Coding Agent 和人工开发必须遵守的最高优先级服务约束。

## 1. 服务定位

`data-control-service` 是完整的数据库分发管控微服务，负责：

- 面向 Agent 的 Data Access Gateway；
- 面向 Agent 和业务服务共同使用的数据统一入口；
- 可信租户业务上下文；
- 参数、Operation 和资源 Schema 校验；
- Role、Capability、Action 和资源归属检查；
- 数据安全与策略拦截；
- 幂等、事务和 Outbox；
- 租户优先、租户内按业务的分库路由；
- PostgreSQL、MinIO、Neo4j、Milvus、Redis、TimescaleDB 等 Adapter；
- 数据访问、变更、拒绝、路由和执行审计；
- 统一错误与响应。

它不是一个单纯的 Agent Tool 插件，也不是一个允许 Agent 直连数据库的代理。

## 2. 不可变的三层架构

```text
第一层：Data Access Gateway
    Agent Tool 协议、Schema、上下文映射、ToolResponse

第二层：数据库分发管控服务统一入口
    参数、可信上下文、权限、策略、幂等、路由、事务、审计、统一响应

第三层：Adapter / Driver
    真实 PostgreSQL、MinIO、Neo4j、Milvus、Redis、TimescaleDB 执行
```

调用关系必须是：

```text
Agent → Data Access Gateway → 统一入口 → Adapter
业务服务 ───────────────→ 统一入口 → Adapter
```

禁止：

- Data Access Gateway 绕过统一入口直接访问 Adapter；
- 业务服务绕过统一入口直接调用本服务 Adapter；
- 在 Data Access Gateway 和统一入口分别复制权限、策略、路由和审计实现；
- 将 Adapter 暴露为公网或 Agent Tool API；
- 允许 Agent 传入任意数据库地址、表名、SQL、Bucket 或 Collection。

## 3. 层级职责

### 3.1 Data Access Gateway 只负责

- `GET /api/v1/dag/tools`；
- `GET /api/v1/dag/tools/{tool_name}/schema`；
- `POST /api/v1/dag/tools/execute`；
- Tool 名称和 Action 是否存在；
- Tool 参数 JSON Schema 校验；
- Agent Execution Context 和 Capability Token 的接收；
- `tool_name + action → operation` 映射；
- `ToolRequest → DataDispatchRequest`；
- 调用同一进程内的统一入口 Application Service，不通过 HTTP 自调用；
- `DataDispatchResponse → ToolResponse`；
- Agent Tool 调用级 Trace 和审计元数据。

Data Access Gateway 不得负责：

- 真实数据库连接；
- 业务角色最终判定；
- 资源归属最终判定；
- 分库路由最终决策；
- 数据事务；
- Provider 或 Adapter 直接选择；
- 任意 SQL 拼接。

### 3.2 数据统一入口负责

- 建立并验证可信 `TenantBizContext`；
- 请求 Envelope 和 Operation Payload Schema；
- 租户是否启用、业务是否开通；
- Role / Permission / Capability / Tool Action；
- Resource Ownership 和 Data Scope；
- 业务与数据安全策略；
- 幂等状态机；
- Route Rule 解析；
- Adapter 选择与执行；
- 事务、Outbox 和补偿语义；
- Access Audit、Change Audit、Deny Audit、Execution Audit；
- 统一 DataResponse。

### 3.3 Adapter 负责

- 连接池和真实驱动；
- 参数化查询或受控 SDK 调用；
- 超时、取消和底层错误归一化；
- 事务句柄；
- 返回受控 `AdapterResult`。

Adapter 不得：

- 自己解析 HTTP 或 Tool 协议；
- 信任 Payload 中的租户字段；
- 绕过 Route Decision 自行切换租户库；
- 承担业务权限；
- 将凭据、连接串或原始数据库错误泄露给调用方。

## 4. 两层接口契约

所有公开接口必须使用 `/api/v1`，并有 OpenAPI 3.1 和 JSON Schema。

### 4.1 Agent Tool 接口

```http
GET  /api/v1/dag/tools
GET  /api/v1/dag/tools/{tool_name}/schema
POST /api/v1/dag/tools/execute
```

Tool Execute 至少包含：

```text
request_id
trace_id
agent_id
session_id
task_id
tool_call_id
tool_name
action
params
idempotency_key（写操作必填）
```

可信的 `tenant_id`、`biz_domain`、Capability 和 Data Scope 必须来自认证中间件或已验签 Capability Token；不能直接信任模型生成的请求体字段。

### 4.2 统一数据入口

```http
GET  /api/v1/data/operations
GET  /api/v1/data/operations/{operation}/schema
POST /api/v1/data/dispatch
```

Dispatch Request 的逻辑字段：

```text
request_id
trace_id
request_source
caller
auth_context
biz_context
operation
resource
payload
idempotency_key
```

其中必须存在并已可信解析：

```text
tenant_id
biz_domain
```

写操作缺少幂等键必须拒绝。未知 Operation、未知 Resource Type、未知 Route 或未知 Adapter 必须 fail closed。

### 4.3 统一响应

成功与失败都必须包含：

```text
request_id
trace_id
success
operation / tool_name
```

失败响应只返回稳定错误码、可公开消息和脱敏详情。禁止返回连接串、SQL、堆栈、Token、对象存储凭据和 Provider 密钥。

## 5. 统一执行流水线

统一入口必须按下列顺序执行；调整顺序需要 ADR：

```text
1. Ingress envelope validation
2. Request ID / Trace context establishment
3. Authentication and trusted TenantBizContext resolution
4. Capability Token signature / expiry / audience / replay checks
5. Operation lookup and payload schema validation
6. Tenant business entitlement check
7. Role, permission, action and resource ownership check
8. Policy evaluation
9. Idempotency begin / replay decision
10. Tenant-first route resolution
11. Adapter acquisition
12. Controlled execution and transaction
13. Audit + Outbox persistence
14. Idempotency complete/fail
15. Error normalization
16. Unified response
```

拒绝请求也必须产生 `DENY` Audit 和可关联 Trace，并且不得产生业务副作用。

## 6. 插件化快速扩展

目标：增加已有数据库类型上的新 Tool/Operation 时，只增加一个插件文件和测试，不修改 Controller、核心流水线或硬编码路由。

建议结构：

```text
src/
├── api/
│   ├── dag/
│   └── data/
├── application/
│   ├── gateway-pipeline.ts
│   └── dispatch-pipeline.ts
├── registries/
│   ├── tool-registry.ts
│   ├── operation-registry.ts
│   └── adapter-registry.ts
├── plugins/
│   ├── tools/
│   │   └── *.tool-plugin.ts
│   ├── operations/
│   │   └── *.operation-plugin.ts
│   └── adapters/
│       └── *.adapter-plugin.ts
├── routing/
├── security/
├── policy/
├── idempotency/
├── audit/
├── adapters/
└── persistence/
```

插件契约应支持一个文件同时注册相关 Tool Action 和 Operation：

```ts
export function register(context: PluginRegistrationContext): void {
  context.tools.register(/* ToolSpec */);
  context.operations.register(/* OperationSpec */);
}
```

必须满足：

- Tool 唯一键：`tool_name + action`；
- Operation 唯一键：`operation`；
- 重复注册时启动失败；
- Tool Action 必须显式映射一个 Operation；
- Operation 必须显式声明 input schema、required permissions、idempotency mode、resource type 和 target adapter capability；
- Loader 只能加载随构建产物发布的可信 `*.plugin.js`；
- 禁止请求参数指定模块路径；
- 禁止从租户上传目录动态执行代码；
- 插件加载失败时服务 readiness 失败，不得静默跳过；
- Tool/Operation 列表必须基于当前租户业务 Capability 过滤；
- Registry 定义是全局元数据，不代表任意租户都被授权。

新增数据库类型时允许增加一个 Adapter 插件，但仍不得修改统一入口主流程。

禁止核心路由出现不断增长的：

```text
switch (tool_name)
switch (operation)
if (databaseType === ...)
```

## 7. 租户优先、租户内按业务路由

最高数据隔离键是：

```text
tenant_id
```

租户内部第二隔离键是：

```text
biz_domain
```

完整路由上下文：

```text
tenant_id → biz_domain → operation → resource_type → resource_id
```

Route Resolver 的匹配优先级：

```text
1. tenant_id + biz_domain + operation + resource_type
2. tenant_id + biz_domain + operation
3. tenant_id + biz_domain
4. tenant_id
5. platform topology default
```

重要：低优先级规则只能决定物理拓扑，不得降低查询中的租户业务过滤条件。任何 Route Decision 都必须回传并审计：

```text
route_rule_id
isolation_mode
target_type
target_instance
target_database / schema / table / bucket / collection
adapter_name
adapter_method
```

Schema、Database、Bucket 和 Collection 名称必须由受控配置生成，不能把原始 `tenant_id` 直接拼接进标识符；应使用规范化且不可注入的稳定映射。

### 7.1 PostgreSQL

支持三种演进模式：

```text
SHARED_TABLE
  共享实例和表，所有表强制 tenant_id + biz_domain；
  必须有复合索引，建议 RLS；
  Repository 禁止无 TenantBizScope 查询。

TENANT_SCHEMA
  一个租户一个受控 Schema；
  Schema 内按业务使用前缀表或独立表组，例如 legal_case、robot_device；
  仍保留 tenant_id / biz_domain 作为纵深校验字段。

TENANT_DATABASE
  一个租户一个 Database；
  Database 内按业务建立 legal、robot_dog 等 Schema；
  适合大客户和私有化。
```

禁止从请求接收任意 SQL、任意表名、任意 Schema。查询必须使用参数化语句、受控模板或明确 Repository 方法，并配置最大行数、超时和取消。

### 7.2 MinIO

默认对象路径：

```text
tenants/{tenant_key}/{biz_domain}/{resource_type}/{resource_id}/...
```

普通租户可共享 Bucket；大租户可独立 Bucket。任何 List/Get/Put/Delete 都必须在服务端补全租户业务 Prefix，禁止只靠调用方传 object key。

### 7.3 Milvus

普通租户可共享按用途划分的 Collection，但每次检索必须在向量数据库查询阶段强制 Scalar Filter：

```text
tenant_id == currentTenant AND biz_domain == currentBiz
```

禁止全局向量召回后在应用层过滤。大租户可以由 Route Rule 切到独立 Collection。

### 7.4 Neo4j

使用独立 Database、Label/Property 或二者组合隔离。任何 Cypher 模板都必须强制 tenant_id + biz_domain；节点和关系均不得缺失隔离字段。禁止执行调用方提供的任意 Cypher。

### 7.5 Redis

Key 必须以受控命名空间开头：

```text
tenant:{tenant_key}:{biz_domain}:...
```

分布式锁、幂等键和缓存也必须包含租户业务 Scope。禁止使用全局业务 Key。

### 7.6 TimescaleDB

Hypertable 或业务表必须包含 `tenant_id`、`biz_domain` 和时间列。查询、聚合和保留策略必须保留租户业务边界。

## 8. Route Rule 元数据

服务可维护自己的 `data_route_rule` 元数据，至少包含：

```text
rule_id / rule_code
tenant_id（可选，精确租户规则）
biz_domain
operation
resource_type
isolation_mode
target_type
target_instance
target_database
target_schema
target_table
target_bucket
target_collection
adapter_name
adapter_method
priority
enabled
version
```

Route Rule 变更必须版本化、审计、支持回滚，并在使用前验证目标 Adapter 已注册且健康。

## 9. 权限与安全

必须实施纵深校验：

```text
API Authentication
  → Trusted TenantBizContext
  → Capability Token
  → Tool + Action / Operation Permission
  → Tenant Business Entitlement
  → Resource Ownership / Data Scope
  → Policy
  → Route Scope
  → Adapter Guard
```

Agent 路径必须校验 Capability Token：签名、issuer、audience、expiry、jti、agent/session/task、tenant、biz、tool、action、resource scope。写请求必须防重放。

禁止：

- 仅依赖 Prompt 或 Tool 可见性作为权限；
- 仅校验 Tool 名，不校验 Action；
- 仅校验 tenant_id，不校验 biz_domain；
- 将调用方传入的 Route Hint 当作最终路由；
- 将原始凭据传给 Agent 或业务服务；
- 任意 SQL/Cypher、任意文件路径和任意集合名称；
- 越权后仍写入缓存、幂等结果或审计以外的业务数据。

## 10. 幂等

写操作必须声明幂等策略：

```text
REQUIRED
OPTIONAL
NOT_APPLICABLE
```

幂等 Scope 至少包含：

```text
tenant_id + biz_domain + operation + caller + idempotency_key
```

状态机：

```text
STARTED → COMPLETED
STARTED → FAILED
```

同 Key 同 Payload 返回已保存结果；同 Key 不同 Payload 返回 Conflict。外部数据库提交成功但幂等记录失败的风险必须通过事务、Outbox 或可恢复流程处理。

## 11. 审计与 Trace

至少区分：

```text
access_audit
execution_audit
data_change_audit
deny_audit
route_audit
```

每条审计必须包含：

```text
tenant_id
biz_domain
request_id
trace_id
caller_type / caller_id
operation
tool_name / action（Agent 路径）
resource
route_rule_id
adapter
result / error_code
latency
occurred_at
```

禁止记录密码、Token、完整连接串、大文件内容和未脱敏业务 Payload。大结果保存到对象存储，审计只保存摘要、Hash 和引用。

## 12. 一致性与故障处理

- PostgreSQL 是服务自身路由、幂等、审计和 Outbox 元数据的权威源；
- Redis 只做缓存、锁和短期状态，不是权威状态源；
- 写操作和审计必须定义一致性边界；
- 未知错误统一归一化；
- 依赖超时必须支持取消；
- 重试只允许幂等操作；
- Adapter 健康失败必须影响 readiness 或该 Route 的可用状态；
- 不得因为审计写入失败而静默返回成功；
- 对跨库写入明确采用 Saga/Outbox，不承诺不存在的分布式 ACID。

## 13. 推荐代码结构

```text
services/data-control-service/
├── src/
│   ├── api/
│   │   ├── dag/
│   │   ├── data/
│   │   └── health/
│   ├── application/
│   ├── domain/
│   ├── registries/
│   ├── plugins/
│   ├── routing/
│   ├── security/
│   ├── policy/
│   ├── idempotency/
│   ├── audit/
│   ├── adapters/
│   ├── persistence/
│   ├── observability/
│   └── config/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── security/
│   └── e2e/
├── migrations/
├── openapi/
├── deploy/
├── AGENTS.md
└── VIBE_CODING.md
```

领域层不得依赖 HTTP、数据库驱动或具体 Adapter。API 层不得包含业务路由和 SQL。

## 14. 测试硬约束

### 单元测试

- Registry 重复检测；
- Tool Action 到 Operation 映射；
- Capability Scope；
- Route 优先级；
- 租户键规范化；
- Idempotency 状态机；
- 错误归一化；
- 敏感字段脱敏。

### 契约测试

- OpenAPI 和 JSON Schema；
- Tool list/schema/execute；
- Operation list/schema/dispatch；
- 稳定错误码；
- 公共包契约兼容性。

### 集成测试

必须至少有：

```text
tenant_A + LEGAL
tenant_A + ROBOT_DOG
tenant_B + LEGAL
```

两个租户都创建相同 `resource_id = case_001`。验证所有读写只能返回当前租户业务数据。

### 负向安全测试

- tenant_A Token + tenant_B 请求体；
- LEGAL Context 请求 ROBOT_DOG Resource；
- 允许 Tool 但不允许 Action；
- 过期、篡改、错 audience、错 session 的 Token；
- 无 Token 直调 Agent Tool API；
- 传入任意 SQL、Schema、Bucket、Collection；
- MinIO Prefix 穿越；
- Milvus 全局召回；
- 写请求 replay。

每个负向测试必须断言：

```text
明确拒绝
零业务副作用
DENY Audit
Trace 可关联
```

## 15. Definition of Done

一个功能只有在下列条件全部满足时才算完成：

- 符合三层架构；
- Agent 和业务服务路径在统一入口汇合；
- tenant_id + biz_domain 在查询执行层强制生效；
- Tool/Operation/Adapter 可由 Registry 管理；
- 无硬编码核心 switch；
- 有 OpenAPI/Schema；
- 有成功、失败和越权测试；
- 审计和 Trace 可关联；
- lint、typecheck、unit、integration、security 测试通过；
- 文档更新；
- 没有 Secret；
- 未夸大未验证能力。

## 16. 严禁的 Vibe Coding 反模式

- 一次性生成万能框架但没有可运行垂直切片；
- 先实现所有数据库 Adapter 再做第一条业务路径；
- 复制三套校验逻辑；
- 把全部代码放进 `shared`；
- 用内存 Map 作为生产路由、幂等或审计权威源；
- 只写 Happy Path；
- Mock 掉所有安全边界后宣称隔离通过；
- 为追求“几行扩展”而运行不可信动态代码；
- 未运行测试就提交；
- 修改根公共包以适配本服务专属需求，而未证明第二个服务真实需要。
