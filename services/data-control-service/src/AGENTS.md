# AGENTS.md — data-control-service/src

本文件继承仓库根目录和 `services/data-control-service/AGENTS.md`，并适用于 `src/**`。

开始修改源码前，必须额外完整阅读：

- `../VIBE_CODING_CONSTRAINTS.md`；
- `../VIBE_CODING.md`；
- `../../../docs/architecture/data-control-service-architecture-original.png`；
- `../../../docs/architecture/data-control-service-architecture.md`。

## 任务模式

当用户当前要求是补充约束、上传架构图或整理 Codex 任务书时，禁止修改本目录任何业务源码。只有用户明确要求实现某个 Phase 或功能时，才可进入实现模式。

## 架构事实源

原始 PNG 高于代码、README、派生 Mermaid 图和历史仓库。禁止通过重构改变以下调用关系：

```text
Agent -> Data Access Gateway -> 统一 /data/dispatch -> Adapter
业务服务 ---------------------> 统一 /data/dispatch -> Adapter
```

## 源码硬边界

- Gateway 只做 Tool 协议、Schema、Agent 上下文、Tool/Operation 映射、请求/响应转换和 Agent Tool Audit；
- 权限、数据权限、业务/数据策略、幂等、路由、事务、Access Audit、Change Audit 只有一套权威实现，位于统一入口；
- Adapter 只做受控驱动执行、连接生命周期、超时取消、执行层租户业务过滤和底层错误归一化；
- 禁止 Gateway 或业务服务绕过统一入口直接调用 Adapter；
- 禁止信任请求体自由填写的 `tenant_id`、`user_id`、`roles`；
- 禁止任意 SQL、Cypher、Bucket、Collection、Schema、表名、Redis Key 前缀和连接地址；
- 禁止把历史 `claria/data-access-gateway` 的整体结构、硬编码 Tool 路由或 MongoDB 范围搬入本服务；
- 当前 Adapter 范围仅为 PostgreSQL、MinIO、Redis、Neo4j、Milvus、TimescaleDB；
- 新增数据库类型或改变原图步骤必须先有用户批准的 ADR。

## 实现前输出

每次进入实现模式，先输出：

1. 原图节点到计划模块/文件的映射；
2. 本 Phase 的 In Scope / Out of Scope；
3. 与历史 Gateway 的差异；
4. 安全失败路径和零副作用断言；
5. 计划运行的质量门禁。

不得先写代码再补计划。
