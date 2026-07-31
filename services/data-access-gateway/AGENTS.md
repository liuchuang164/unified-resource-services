# Data Access Gateway 开发约束

本目录中的所有开发必须遵守：

- `docs/architecture/data-access-gateway-architecture.md`
- `docs/architecture/data-access-gateway-tool-contract.md`
- `docs/governance/data-access-gateway-vibe-coding-constraints.md`
- 仓库 `其他服务/` 中 Data Access Gateway 架构资料

## 两层接口必须严格分离

### Layer 1：本服务对 Agent / OpenClaw / Hermes

```text
GET  /dag/tools
GET  /dag/tools/{tool_name}/schema
POST /dag/tools/execute
```

### Layer 2：数据库分发管控服务对 Gateway / 业务服务

```text
GET  /data/operations
GET  /data/operations/{operation}/schema
POST /data/dispatch
```

不得使用 `/tools/list`、`/tools/schema`、`/tools/execute` 作为正式接口。

## 不可突破的边界

1. 本服务只提供 `/dag/tools*`、健康检查以及必要的内部管理能力。
2. 本服务不得直接连接 PostgreSQL、Redis、MinIO 或未来存储。
3. 数据访问必须调用 Data Control Service 的 `/data/operations*` 和 `/data/dispatch`。
4. Tool 模块不得进入 Router 条件分支。
5. Tool 的 target、resource type、operation 由服务端 Mapper 决定，不能由 params 决定。
6. `POST /dag/tools/execute` 必须验证 `capability_token`。
7. 请求体中的 roles、permissions 不可信且不得存在。
8. 禁止 raw SQL、Redis command、bucket、object_key、endpoint、credentials 和本地文件路径。
9. 第一阶段只开发 `minio_file_access`。
10. 不能用直接 curl `/data/dispatch` 冒充 DAG 验收。

## 新 Tool 模块最低组成

```text
tools/<tool_name>/
  definition.py
  schemas.py
  mapper.py
  response.py
  tests/
```

新增 Tool 不得修改核心执行 Router；注册后必须自动出现在 `/dag/tools` 和 `/dag/tools/{tool_name}/schema`。

## capability token 最低边界

Token 必须绑定：

```text
agent_id
tenant_id
biz_domain
tool_name
actions
audience
expires_at
```

请求声明与 token claims 不一致必须拒绝。Token 不得写日志或透传给存储层。

## 真实性要求

只有真实通过：

```text
Agent-style ToolRequest
→ POST /dag/tools/execute
→ Data Access Gateway
→ POST /data/dispatch
→ MinIO Adapter
→ MinIO
```

并同时验证 `/dag/tools`、Tool Schema、Layer 2 operation discovery/schema，才能宣告 MinIO Tool 可用。