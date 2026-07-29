# 数据库分发管控服务总体架构

- 状态：Frozen for Phase 1 implementation
- 适用分支：`feature/database-distribution-control-service`
- 架构来源：压缩包中的“数据库分发管控服务”架构图及统一访问平面技术报告

## 1. 服务定位

数据库分发管控服务是统一访问平面中的数据访问控制与分发层。它位于业务系统、本体服务、Agent Data Access Gateway 与底层数据资源之间，负责把统一的数据请求安全、可审计、可幂等地路由到正确的数据 Adapter。

核心链路：

```text
业务服务 / 本体服务 ───────────────┐
                                    ├─> POST /data/dispatch
Agent / OpenClaw -> Data Access Gateway ┘
                           |
                           v
参数校验 -> 租户上下文 -> RBAC/ABAC -> 策略 -> 幂等 -> 路由 -> 事务编排
                           |
                           v
PostgreSQL / MinIO / Redis / Neo4j / Milvus / TimescaleDB Adapter
                           |
                           v
访问审计 -> 变更审计 -> DataResponse
```

## 2. 职责边界

### 2.1 必须负责

- 统一接收 `DataRequest`。
- 校验协议版本、请求结构、操作类型和资源描述。
- 解析并强制校验 `tenant_id`、`biz_domain`、主体身份和调用来源。
- 执行 RBAC、ABAC、资源级策略和数据范围策略。
- 对写操作实施幂等、防重放和并发冲突保护。
- 根据 `operation + resource.target + resource.type` 选择 Adapter。
- 对需要原子性的同库操作执行事务编排。
- 记录访问审计、变更审计、失败审计和追踪信息。
- 将底层异常归一化为稳定的 `DataResponse` 和错误码。

### 2.2 明确不负责

- 不承担案件、合同、证据、本体等领域业务判断。
- 不向调用方暴露数据库连接串、物理表、Bucket 密钥等内部细节。
- 不允许调用方提交任意 SQL、任意脚本或任意存储路径。
- 不替代 Agent 的任务规划、SOP 编排或模型推理。
- 不负责跨异构数据源的强一致分布式事务。
- 不在 Adapter 内实现权限决策和领域逻辑。
- 不静默吞掉失败、降级为成功或伪造执行结果。

## 3. 调用入口

### 3.1 业务入口

`POST /data/dispatch`

适用于业务服务、本体服务和可信内部网关。调用方提交标准 `DataRequest`。

### 3.2 Agent Tool 入口

Data Access Gateway 暴露：

- `GET /tools/list`
- `GET /tools/schema`
- `POST /tools/execute`

Gateway 负责 Tool 协议校验、Agent 上下文提取、Tool 到数据操作的映射，以及 `ToolRequest -> DataRequest` 转换。数据库分发管控服务不直接理解开放式 Tool Prompt。

## 4. 模块划分

### 4.1 API Layer

- HTTP 路由与版本协商。
- 请求体大小、Content-Type、超时和基础格式检查。
- Trace ID / Request ID 注入。
- 统一响应编码。

禁止：在 Controller 中直接访问数据库或写业务路由分支。

### 4.2 Contract Validation

- JSON Schema / DTO 校验。
- `operation` 与 `resource.type` 组合校验。
- Payload 白名单和字段级约束。
- 兼容版本检查。

### 4.3 Context Resolver

生成可信 `ExecutionContext`：

- `tenant_id`
- `biz_domain`
- `subject_id`
- `subject_type`
- `roles`
- `permissions`
- `source`
- `trace_id`
- `request_id`

客户端输入的租户字段不得无条件覆盖鉴权凭据中的可信租户声明。

### 4.4 Authorization & Policy Engine

依次执行：

1. 身份有效性；
2. 租户和业务域作用域；
3. RBAC；
4. ABAC；
5. 资源级权限；
6. 字段级和数据范围策略；
7. 高风险操作策略。

默认拒绝。任何无法判定的权限结果都必须返回拒绝。

### 4.5 Idempotency Service

- 写操作必须提供 `idempotency_key`。
- Key 的有效作用域至少包含 `tenant_id + biz_domain + caller + operation`。
- 相同 Key、相同请求摘要：返回首次确定性结果。
- 相同 Key、不同请求摘要：返回冲突错误。
- 幂等记录必须有明确状态：`PROCESSING / SUCCEEDED / FAILED_RETRYABLE / FAILED_FINAL`。

### 4.6 Routing Service

路由键：

```text
operation + resource.target + resource.type + optional data_class
```

输出稳定的 `RouteDecision`，包含 Adapter 名称、逻辑资源、读写模式、超时、事务要求和策略版本。

禁止仅根据调用方传入的任意字符串动态反射加载 Adapter。

### 4.7 Transaction Orchestrator

- 单一事务型 Adapter 内支持本地事务。
- 多操作批次只有在同一事务域内才允许 `ATOMIC`。
- 跨异构 Adapter 默认 `BEST_EFFORT`，必须返回逐项结果。
- 不以“看似成功”的方式掩盖部分失败。

### 4.8 Adapter Registry

- 注册受支持的 Adapter 与能力矩阵。
- 启动时校验重复名称、缺失能力和错误配置。
- Adapter 必须通过统一 SPI 调用。

### 4.9 Audit Service

访问审计至少记录：

- 谁，在什么租户和业务域；
- 何时，以何种来源；
- 对哪个逻辑资源执行什么操作；
- 权限和策略结果；
- 路由到哪个 Adapter；
- 执行耗时、结果状态、错误码；
- `trace_id`、`request_id`、`idempotency_key` 摘要。

变更审计还必须记录变更前后摘要或字段差异，敏感值必须脱敏，不记录密钥、令牌和完整隐私数据。

### 4.10 Observability

必须提供：

- 结构化日志；
- Metrics：吞吐、延迟、错误率、拒绝率、幂等命中、Adapter 饱和度；
- Trace：入口、策略、路由、Adapter 调用；
- 健康检查：进程存活与依赖就绪分离。

## 5. 标准处理流程

1. API 接收请求并生成/校验追踪标识。
2. Contract Validation 拒绝非法协议和字段。
3. Context Resolver 建立可信租户与主体上下文。
4. Authorization & Policy Engine 执行默认拒绝策略。
5. 对写请求进行幂等认领。
6. Routing Service 生成不可变路由决策。
7. Transaction Orchestrator 调用目标 Adapter。
8. Adapter 返回标准执行结果，不泄露驱动异常。
9. Audit Service 写访问审计；写操作追加变更审计。
10. API 返回统一 `DataResponse`。

审计主链路失败时：高风险写操作必须失败关闭；普通读操作是否允许降级由显式策略决定，禁止代码自行猜测。

## 6. 多租户隔离

- 所有资源操作都必须绑定 `tenant_id + biz_domain`。
- PostgreSQL 查询必须包含作用域条件，优先叠加数据库 RLS。
- Redis Key 必须使用 `tenant:{tenant_id}:{biz_domain}:...` 前缀。
- MinIO Object Key 必须位于租户业务域前缀下。
- Neo4j 节点/关系必须带租户与业务域属性并在查询中约束。
- Milvus 必须采用租户分区、分区键或强制标量过滤。
- TimescaleDB 必须在查询与写入中携带租户维度。
- 禁止无作用域 fallback、跨租户扫描和“管理员默认全租户”隐式行为。

## 7. 安全约束

- 外部输入不可直接形成 SQL、Cypher、Milvus 表达式、Redis 命令或对象存储路径。
- 只允许逻辑资源名和预注册操作模板。
- Secrets 仅来自安全配置源，不进入请求、日志和审计正文。
- 所有写操作必须受权限、幂等、审计三重门禁。
- 删除默认使用受控软删除；物理删除必须单独授权并记录原因。
- 导出、批量读取和跨范围查询属于高风险操作，必须限额和审计。

## 8. 非功能目标

首阶段目标不是虚构性能数字，而是建立可测量基线：

- 每个请求具备确定性超时；
- Adapter 支持连接池与背压；
- 分页、批量大小和 Payload 有上限；
- 错误明确区分可重试与不可重试；
- 核心路径具备单元、契约、集成、租户隔离和故障注入测试；
- 性能结论只能来自可重复压测报告。

## 9. 推荐代码边界

```text
src/
  api/
  application/
    dispatch/
    authorization/
    idempotency/
    routing/
    transaction/
    audit/
  domain/
    contracts/
    policy/
    routing/
    errors/
  infrastructure/
    adapters/
      postgresql/
      minio/
      redis/
      neo4j/
      milvus/
      timescaledb/
    persistence/
    observability/
  config/
```

依赖方向必须由外向内：`api/infrastructure -> application -> domain`。Domain 不依赖具体驱动。
