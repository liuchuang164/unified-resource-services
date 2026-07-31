# Data Access Gateway 开发约束

本目录中的所有开发必须遵守：

- `docs/architecture/data-access-gateway-architecture.md`
- `docs/architecture/data-access-gateway-tool-contract.md`
- `docs/governance/data-access-gateway-vibe-coding-constraints.md`
- 仓库 `其他服务/` 中 Data Access Gateway 架构资料

## 不可突破的边界

1. 本服务只提供 `/tools/list`、`/tools/schema`、`/tools/execute` 和健康检查。
2. 本服务不得直接连接 PostgreSQL、Redis、MinIO 或未来存储。
3. 数据访问必须调用 Data Control Service `/data/dispatch`。
4. Tool 模块不得出现在 Router 的条件分支里。
5. Tool 的 target、resource type、operation 由服务端 Mapper 决定，不能由请求 params 决定。
6. 请求体中的 roles、permissions 不可信且不得存在。
7. 禁止 raw SQL、Redis command、bucket、object_key、endpoint、credentials 和本地文件路径。
8. 第一阶段只开发 `minio_file_access`。

## 新 Tool 模块最低组成

```text
tools/<tool_name>/
  definition.py
  schemas.py
  mapper.py
  response.py
  tests/
```

新增 Tool 不得修改核心执行 Router。

## 真实性要求

只有真实通过：

```text
Agent-style ToolRequest
→ Data Access Gateway
→ Data Control Service
→ MinIO Adapter
→ MinIO
```

才能宣告 MinIO Tool 可用。直接 curl `/data/dispatch` 不属于 DAG 验收。