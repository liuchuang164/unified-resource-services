# AGENTS.md — data-control-service/openapi

继承仓库根目录和服务目录全部约束。

约束维护模式下禁止生成声称已经实现的正式 OpenAPI。只有对应 Phase 已实际实现并通过契约测试后，才可发布接口契约。

OpenAPI 必须保留原图的两类接口语义：

```text
Data Access Gateway: /tools/list, /tools/schema, /tools/execute
统一数据入口:        /data/dispatch
```

允许经 ADR 增加版本前缀或资源化路径，但不得改变以下事实：业务本体服务直接进入统一数据入口；Agent 先经过 Gateway；两条路径共享同一权限、策略、幂等、路由、事务和审计流水线。

身份、租户、角色和数据范围必须区分“请求声明字段”与“可信认证上下文”。契约不得暗示调用方可以通过请求体自由选择租户、角色、数据库、Schema、表、Bucket、Collection、Redis Key 前缀、SQL 或 Cypher。

失败响应只暴露稳定错误码、公开消息和脱敏详情，不得泄露堆栈、连接串、Token、凭据或原始数据库错误。
