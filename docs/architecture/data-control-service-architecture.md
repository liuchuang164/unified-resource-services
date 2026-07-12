# 数据库分发管控服务原始架构图说明

## 原始文件

```text
data-control-service-architecture-original.png
```

SHA-256：

```text
d06d11f29a829140ab62686c805b6b6fac620fc68a8c2963e053ba0320cbd291
```

该 PNG 是用户提供的原始架构事实源，必须按原始字节保存。禁止裁剪、压缩、重绘、改色或覆盖。派生图必须另存，并在文件名和标题中标注 `derived`。

## 阅读优先级

当代码、README、Mermaid 图、历史仓库与本图冲突时，以本图为准。任何改变调用方向、层级职责、统一入口、审计链路或 Adapter 范围的提议，都必须先形成 ADR 并获得用户明确批准。

## 原图文字索引

本节只为搜索和 Codex 阅读提供文字索引，不替代 PNG。

### 调用方

Agent / 智能体调用方：

- Hermes：任务规划 / SOP 控制；
- Sub Agent：子智能体；
- OpenClaw Skill / Tool 调用。

业务本体服务调用方：

- 庭策本体服务；
- 机器狗本体服务；
- 政务本体服务；
- 其他业务本体服务。

### Data Access Gateway

原图节点：

```text
/tools/list       工具列表
/tools/schema     工具参数 Schema
/tools/execute    工具执行入口
Tool 协议校验     tool_name / params / schema
Agent 上下文解析  agent_id / tool_call_id / trace_id
Tool 路由映射     tool_name <-> data_operation
请求转换器        ToolRequest -> DataRequest
响应包装器        DataResponse -> ToolResponse
Tool 调用审计     Agent Tool Audit
```

Gateway 是 Agent 数据访问工具网关，不是数据库分发管控服务的全部实现。

### 数据库分发管控服务统一入口

原图节点：

```text
/data/dispatch
参数校验       request / operation / payload
权限解析       tenant_id / user_id / roles
角色权限检查   RBAC / 数据权限
策略拦截       业务策略 / 数据策略
幂等 Key 处理  idempotency_key
数据路由       operation -> target_db / adapter
事务编排       单库 / 多库事务策略
数据访问审计   Access Audit
数据变更审计   Change Audit
统一数据响应   DataResponse
```

Agent 请求经 Gateway 转换后进入该入口；业务本体服务直接进入该入口。两条路径在此汇合并共享同一套权限、策略、幂等、路由、事务和审计实现。

### Adapter 与真实数据源

原图中的 Adapter：

```text
PostgreSQL Adapter   结构化业务数据
MinIO Adapter        文件 / 材料 / 音视频
Redis Adapter        缓存 / 状态 / 锁
Neo4j Adapter        图谱关系
Milvus Adapter       向量检索
TimescaleDB Adapter  时序数据
```

对应真实数据源 / 存储：

```text
PostgreSQL
MinIO
Redis
Neo4j
Milvus
TimescaleDB
```

MongoDB 不在该原图范围内，不能因为历史参考仓库使用 MongoDB 就自动加入目标架构。

## 不可改变的调用关系

```text
Hermes / Sub Agent / OpenClaw Skill/Tool
  -> Data Access Gateway
  -> /data/dispatch
  -> Adapter
  -> 真实数据源

庭策 / 机器狗 / 政务 / 其他业务本体服务
  -> /data/dispatch
  -> Adapter
  -> 真实数据源
```

禁止 Gateway 或业务本体服务绕过统一入口直接访问 Adapter。

## 完整开发约束

- `services/data-control-service/AGENTS.md`
- `services/data-control-service/VIBE_CODING_CONSTRAINTS.md`
- `services/data-control-service/VIBE_CODING.md`
