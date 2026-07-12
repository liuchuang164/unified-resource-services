# Data Control Service — Codex Vibe Coding 补充约束

> 本文件只定义 Codex 的开发护栏和交付方式，不实现数据库分发管控服务的业务代码。

## 0. 当前任务边界

本次约束整理属于 **约束维护模式**。允许的变更仅限：

- `AGENTS.md`；
- Vibe Coding / Codex 任务文档；
- 架构说明文档；
- 用户提供的原始架构图；
- 为上述文档增加的链接、校验值和索引。

本次禁止修改：

- `src/**`；
- `tests/**` 中的业务测试；
- `migrations/**`；
- `openapi/**` 中的正式接口实现；
- `package.json`、运行依赖和构建脚本；
- Dockerfile、Kubernetes、Helm 和运行配置；
- 任何数据库、缓存、对象存储或消息系统代码。

Codex 只有在后续用户明确指定“实现某个 Phase / 垂直切片 / 功能”时，才进入实现模式。不得把“补充开发约束”解释为“立即开发”。

## 1. 架构事实源与优先级

原始架构图固定保存为：

```text
docs/architecture/data-control-service-architecture-original.png
```

原文件 SHA-256：

```text
d06d11f29a829140ab62686c805b6b6fac620fc68a8c2963e053ba0320cbd291
```

该图片必须按原始字节保存，不得裁剪、压缩、重绘、改色、覆盖或用 Mermaid 图替代。可以另建“派生图”，但文件名和标题必须明确标注 `derived`，且原图始终保留。

发生冲突时按以下顺序处理：

1. 用户在当前任务中的明确指令；
2. 原始架构图；
3. 仓库根 `AGENTS.md`；
4. 本目录 `AGENTS.md`；
5. 本文件；
6. `VIBE_CODING.md`；
7. 当前仓库已有骨架；
8. 历史参考仓库。

文字文档只能解释原图，不能改变原图中的调用方向、层次职责、统一入口、审计链路和 Adapter 范围。发现无法消解的冲突时，不得自行“优化架构”，必须记录冲突并请求用户决定。

## 2. 历史仓库只读参考规则

历史参考位置：

```text
liuchuang164/claria / main / data-access-gateway
```

它只用于参考已经验证过的局部工程经验，不是目标服务模板，也不是可直接搬迁的架构。

### 2.1 可以参考

- Tool 请求和响应的字段组织经验；
- JSON Schema 校验方式；
- 数据库客户端的连接、关闭、超时和错误处理经验；
- 参数化查询与 MinIO 路径规范化思路；
- 审计字段、错误码和负向测试思路；
- Tool 注册、路由和测试夹具中可以独立复用的行为；
- 已知安全问题及修复经验。

参考不等于复制。迁移任何逻辑前，必须先证明它符合本架构图和本仓库 TypeScript 边界。

### 2.2 禁止继承

- 把 Data Access Gateway 当作完整数据服务；
- `Tool -> 数据库/MinIO` 的直接调用；
- 在 Gateway 内完成最终权限、业务策略、幂等、数据路由和事务；
- 信任请求体中的 `tenant_id`、`user_id`、`role`；
- 将旧仓库硬编码 Tool 路由表直接搬入核心流程；
- 将案件、律师、材料等庭策专属语义写入通用数据控制核心；
- 因旧仓库存在 MongoDB 就把 MongoDB 加入当前范围；
- 搬用旧仓库的环境变量、目录布局、部署模型或本地文件下载模型；
- 通过复制 Python 文件替代当前服务的领域建模；
- 为兼容旧接口而破坏统一 `/data/dispatch` 入口。

当前架构图中的真实数据适配器范围是：

```text
PostgreSQL
MinIO
Redis
Neo4j
Milvus
TimescaleDB
```

MongoDB 不在本期架构范围。增加任何新数据库类型必须由用户明确批准，并形成 ADR；不能以“旧仓库已有”为理由擅自加入。

## 3. 原图对应的不可变调用关系

### 3.1 Agent 调用方

原图包含：

```text
Hermes（任务规划 / SOP 控制）
Sub Agent（子智能体）
OpenClaw Skill / Tool
```

所有 Agent 路径必须先进入 Data Access Gateway，再进入统一数据入口：

```text
Agent
  -> Data Access Gateway
  -> 数据库分发管控服务统一入口
  -> Adapter
  -> 真实数据源 / 存储
```

Agent、Skill、Sub Agent 均不得直接访问 Adapter、数据库连接、对象存储凭据或数据路由配置。

### 3.2 业务本体服务调用方

原图包含庭策本体服务、机器狗本体服务、政务本体服务和其他业务本体服务。它们必须直接调用统一数据入口，而不是伪装成 Agent Tool：

```text
业务本体服务
  -> /data/dispatch
  -> 统一管控流水线
  -> Adapter
```

业务服务不得调用 Data Access Gateway 以绕过正式服务身份，也不得直接访问本服务内部 Adapter。

### 3.3 两条路径必须汇合

```text
Agent -> Gateway ---+
                    +-> 统一数据入口 -> Adapter
业务服务 -----------+
```

权限、数据权限、策略、幂等、数据路由、事务、访问审计和变更审计只能有一套权威实现，位于统一入口及其 Application/Domain 服务中。

## 4. Data Access Gateway 边界

原图定义的 Tool 端点语义：

```text
/tools/list
/tools/schema
/tools/execute
```

若实现时增加版本前缀或框架前缀，必须保留上述三个端点的语义和一一映射，并在 OpenAPI/ADR 中说明，不得借改名改变架构职责。

Gateway 执行顺序必须体现原图：

```text
Tool 协议校验
  tool_name / params / schema
-> Agent 上下文解析
  agent_id / tool_call_id / trace_id
-> Tool 路由映射
  tool_name <-> data_operation
-> 请求转换
  ToolRequest -> DataRequest
-> 调用统一数据入口
-> 响应包装
  DataResponse -> ToolResponse
-> Agent Tool Audit
```

Gateway 只负责：

- Tool 列表和 Tool Schema 的展示；
- Tool 协议、字段和参数 Schema 校验；
- Agent 调用上下文解析与关联；
- `tool_name + action` 到受控 `data_operation` 的映射；
- ToolRequest/DataRequest 转换；
- DataResponse/ToolResponse 转换；
- Agent Tool 调用级审计元数据。

Gateway 禁止：

- 建立真实数据库连接；
- 选择物理数据库、Schema、Bucket、Collection 或实例；
- 承担最终 RBAC、数据权限、资源归属和业务策略判断；
- 承担幂等权威状态；
- 开启业务数据事务；
- 直接调用 Adapter；
- 拼接 SQL、Cypher、Redis Key、MinIO Object Key 或 Milvus Filter；
- 把 Tool 是否可见当作最终授权。

## 5. 统一数据入口边界

原图的统一入口语义是：

```text
/data/dispatch
```

所有 Agent 转换后的 DataRequest 与业务服务 DataRequest 都必须进入同一 Application Service，不得在同一进程内通过 HTTP 自调用制造两套链路。

统一入口执行顺序必须体现原图，默认不得重排：

```text
1. 参数校验：request / operation / payload
2. 权限解析：tenant_id / user_id / roles
3. 角色权限检查：RBAC / 数据权限
4. 策略拦截：业务策略 / 数据策略
5. 幂等 Key 处理：idempotency_key
6. 数据路由：operation -> target_db / adapter
7. 事务编排：单库 / 多库事务策略
8. Adapter 受控执行
9. 数据访问审计：Access Audit
10. 数据变更审计：Change Audit
11. 统一 DataResponse
```

安全实现可以在不改变职责和先后依赖的前提下细化认证、资源归属、Capability、Outbox、错误归一化和 Trace；不得删除或旁路原图步骤。

统一入口必须 fail closed：未知调用方、租户、角色、业务、Operation、策略结果、Route、Adapter 或资源范围都必须拒绝。

## 6. 身份、租户和数据权限

原图中的 `tenant_id / user_id / roles` 表示权限解析所需上下文，不表示可以信任请求体自由填写的同名字段。

可信上下文只能来自：

- 已认证的业务服务身份；
- 已验签的 Capability Token；
- 受控的内部签名上下文；
- 认证中间件写入且不可被请求体覆盖的上下文。

请求体中的身份字段只能作为声明值参与一致性校验。只要声明值与可信上下文不一致，必须拒绝并记录 DENY Audit。

所有数据执行必须至少受以下范围约束：

```text
tenant_id
+ biz_domain
+ operation
+ resource_type
+ resource_id / data_scope
```

禁止先做全局查询、全局向量召回、全局图遍历或全 Bucket 列表，再在应用层过滤。

## 7. Operation、路由和 Adapter 约束

`data_operation` 是 Gateway Tool 与统一数据入口之间的稳定语义，不得等同于任意 SQL、任意 SDK 方法或任意数据库命令。

每个 Operation 必须声明：

- 唯一名称和版本；
- 请求与响应 Schema；
- 读/写属性；
- 所需角色、权限、Capability 和数据范围；
- 幂等策略；
- 目标 Adapter capability；
- 超时、最大结果、分页和取消语义；
- Access Audit / Change Audit 要求；
- 可公开错误码。

路由必须由受控规则得到：

```text
operation + trusted tenant/biz/resource context
  -> RouteDecision
  -> target_db / adapter
```

调用方不得传入最终数据库地址、连接串、表名、Schema、Bucket、Collection、Redis Key 前缀、SQL 或 Cypher。调用方的 route hint 只能是受控提示，不能覆盖服务端决策。

Adapter 只负责：

- 连接池和驱动生命周期；
- 参数化查询或受控 SDK 调用；
- 执行层租户业务过滤；
- 超时、取消和底层错误归一化；
- 受控事务句柄；
- 返回 AdapterResult。

Adapter 不负责 HTTP/Tool 协议、最终业务权限、路由决策或对外错误展示。

## 8. 各 Adapter 的硬边界

### PostgreSQL

- 只允许 Repository 方法、参数化 SQL 或受控模板；
- 禁止任意 SQL、表名和 Schema；
- 查询执行层强制 `tenant_id + biz_domain`；
- 共享表、租户 Schema、租户 Database 均不得弱化数据范围；
- 写操作必须明确事务、幂等和 Change Audit。

### MinIO

- Bucket/Prefix/Object Key 由服务端受控生成；
- 所有操作强制租户业务 Prefix；
- 禁止 `..`、编码穿越、绝对路径和跨租户猜测；
- 不把大文件内容写入审计，只记录摘要、Hash、大小、MIME 和对象引用。

### Redis

- Cache、Lock、Idempotency Key 全部带租户业务命名空间；
- Redis 不是路由、审计和幂等完成状态的唯一权威源；
- 禁止全局业务 Key。

### Neo4j

- 只允许受控 Cypher 模板或 Repository 方法；
- 节点和关系均保留租户业务隔离字段；
- 禁止任意 Cypher 和无范围图遍历。

### Milvus

- 在向量检索执行阶段强制租户业务 Scalar Filter；
- 禁止全局召回后应用层过滤；
- Collection 选择必须来自 RouteDecision。

### TimescaleDB

- Hypertable/业务表包含租户、业务和时间范围；
- 聚合、分页、保留策略和降采样不得跨租户业务范围；
- 禁止无时间边界的大范围扫描。

## 9. 事务、幂等和审计

### 9.1 幂等

写 Operation 必须显式声明幂等策略。幂等 Scope 至少包含：

```text
tenant_id + biz_domain + operation + caller + idempotency_key
```

同 Key 同 Payload 返回已保存结果；同 Key 不同 Payload 返回冲突。禁止仅在 Gateway 内存中实现生产幂等。

### 9.2 事务

- 单库写优先使用 Adapter 提供的本地事务；
- 多库/多存储不得宣称分布式 ACID；
- 跨资源写使用明确的 Saga、Outbox、补偿或可恢复状态机；
- 重试只允许幂等操作；
- 超时必须支持取消并保留结果不确定性的审计状态。

### 9.3 审计

原图至少要求：

```text
Agent Tool Audit
Access Audit
Change Audit
```

实现时还必须覆盖拒绝、路由和执行审计。拒绝请求必须满足：

```text
明确拒绝
零业务副作用
DENY Audit
Trace 可关联
```

日志与审计不得记录密码、Token、私钥、完整连接串、完整预签名 URL、大文件正文或未脱敏敏感 Payload。

## 10. Codex 实现流程

进入实现模式后，每个 Phase 必须按以下方式工作：

1. 重新阅读原始架构图和所有 AGENTS/Vibe 文档；
2. 输出“架构映射表”，列出本 Phase 触及的原图节点和明确不触及的节点；
3. 输出文件级计划；
4. 只实现用户点名的 Phase，不顺手扩展其他 Adapter；
5. 先完成一条真实垂直切片，再抽象；
6. 运行 lint、typecheck、单元、契约、集成和相关安全测试；
7. 修复全部失败；
8. 更新 OpenAPI、Schema、Migration、README 和验收清单；
9. 提交小而可审查的 Commit；
10. 报告实际执行的命令和真实结果，不得伪造。

任何架构级变更必须先提交 ADR 并获得用户明确批准。Codex 不得以“更优雅”“更现代”“旧仓库已经这样做”为理由自行改变原图。

## 11. 首轮开发前置输出

用户以后要求 Codex 开始开发时，Codex 在写代码前必须先给出：

```text
A. 原图节点 -> 计划模块/文件 的映射
B. 新架构与历史 data-access-gateway 的差异清单
C. 当前 Phase 的 In Scope / Out of Scope
D. 安全失败路径与零副作用断言
E. 计划运行的质量门禁
```

这份前置输出用于证明 Codex 理解的是“数据库分发管控服务”，而不是把历史 Data Access Gateway 原样重写一遍。

## 12. 本次约束提交的完成条件

- [ ] 只修改约束文档和架构资产；
- [ ] 原始架构图按原字节保存；
- [ ] SHA-256 与本文件一致；
- [ ] 明确原图高于历史仓库；
- [ ] 明确 Gateway、统一入口和 Adapter 三层边界；
- [ ] 明确 Agent 路径和业务服务路径；
- [ ] 明确六类 Adapter，未擅自加入 MongoDB；
- [ ] 明确约束维护模式不得开发业务代码；
- [ ] 后续 Codex 可以依据 `VIBE_CODING.md` 分 Phase 实现。
