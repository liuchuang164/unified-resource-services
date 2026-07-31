# Data Access Gateway 架构基线

## 1. 架构定位

Data Access Gateway（DAG）是面向 Agent、OpenClaw、Hermes 的上层 Tool 网关；数据库分发管控服务是面向 Gateway 和业务服务的中层统一数据入口。

两层必须独立部署、独立契约、独立鉴权，禁止合并：

```text
Agent / OpenClaw / Hermes
        ↓
Layer 1：Data Access Gateway
GET  /dag/tools
GET  /dag/tools/{tool_name}/schema
POST /dag/tools/execute
        ↓
ToolRequest → DataRequest
        ↓
Layer 2：数据库分发管控服务
GET  /data/operations
GET  /data/operations/{operation}/schema
POST /data/dispatch
        ↓
PostgreSQL / Redis / MinIO / future adapters
```

DAG 不直接访问 PostgreSQL、Redis、MinIO，也不持有存储连接凭证。所有数据操作必须通过 Layer 2。

## 2. 架构来源与优先级

实现必须以仓库 `其他服务/` 中的架构说明和“两层接口定义”为最高业务架构依据。

接口路径冻结如下：

### Layer 1：Data Access Gateway

| 接口 | 调用方 | 作用 | 核心字段 |
|---|---|---|---|
| `GET /dag/tools` | Agent / OpenClaw | 查询当前 Agent 可见的 Tool 列表 | `agent_id`, `tenant_id`, `biz_domain` |
| `GET /dag/tools/{tool_name}/schema` | Agent / OpenClaw | 查询指定 Tool 的参数 Schema 与 action 列表 | `tool_name` |
| `POST /dag/tools/execute` | Agent / OpenClaw | 执行 Tool，并将 ToolRequest 转换为 DataRequest | `tool_name`, `action`, `params`, `capability_token` |

### Layer 2：数据库分发管控服务

| 接口 | 调用方 | 作用 | 核心字段 |
|---|---|---|---|
| `GET /data/operations` | Gateway / 业务服务 | 查询支持的数据操作 | `tenant_id`, `biz_domain` |
| `GET /data/operations/{operation}/schema` | Gateway / 业务服务 | 查询 operation 对应的请求、权限和路由规则 | `operation` |
| `POST /data/dispatch` | Gateway / 业务服务 | 统一校验、权限、策略、幂等、路由、适配器执行和审计 | `auth_context`, `biz_context`, `operation`, `resource`, `payload` |

`liuchuang164/claria` 仅用于参考 MinIO Tool 的动作设计和 Agent 接入经验，不得复制其 DAG 直连 MinIO、案件业务硬编码或单 Router 分支模式。

## 3. 不可偏离的服务边界

### DAG 负责

1. Tool 发现与 Schema 输出；
2. Agent 身份与 capability token 解析；
3. ToolRequest 严格校验；
4. Tool 权限和策略校验；
5. Tool Registry、版本、action 和生命周期管理；
6. ToolRequest 到 DataRequest 的确定性映射；
7. 调用 Layer 2 的 operation/schema 与 dispatch 接口；
8. DataResponse 到 ToolResponse 的包装；
9. Tool 调用审计与错误码转换。

### DAG 不负责

- 直接连接数据库或对象存储；
- 执行 raw SQL、Redis command、S3/MinIO 原生命令；
- 重复实现 Layer 2 的资源路由、存储幂等、适配器或控制面持久化；
- Agent 任务规划、Hermes SOP 决策或 OpenClaw Skill 推理；
- OCR、ASR、视频处理；
- 外部第三方 API 接入；
- 跨数据库事务。

### Layer 2 负责

- 数据 operation 发现和 Schema；
- DataRequest 契约校验；
- 权限、策略、配额、幂等；
- logical resource mapping；
- Adapter Registry 和真实存储执行；
- Audit Outbox、Recovery、Readiness。

## 4. 核心模块

```text
api/
  dag_tools.py
  dag_tool_schema.py
  dag_tool_execute.py
application/
  tool_discovery_service.py
  tool_schema_service.py
  tool_execution_service.py
  tool_context_resolver.py
  tool_authorization_service.py
  tool_request_mapper.py
  tool_response_mapper.py
  tool_audit_service.py
domain/
  tool_definition.py
  tool_version.py
  tool_context.py
  tool_errors.py
ports/
  tool_registry.py
  data_control_client.py
  auth_provider.py
  capability_verifier.py
  audit_sink.py
infrastructure/
  registry/code_registry.py
  data_control/http_client.py
  auth/development_auth_provider.py
  capability/signed_token_verifier.py
  audit/structured_audit_sink.py
tools/
  minio_file_access/
    definition.py
    schemas.py
    mapper.py
    response.py
```

依赖方向：

```text
API → Application → Domain / Ports ← Infrastructure
                         ↑
                    Tool Modules
```

Domain 不得依赖 FastAPI、HTTPX、Pydantic Settings 或具体存储 SDK。

## 5. Tool 快速扩展模型

每个 Tool 必须由独立 Tool Module 定义，核心 Router 不能出现持续增长的 `if tool_name == ...`。

Tool Module 至少提供：

- `ToolDefinition`；
- `tool_name` 和 SemVer version；
- action 列表；
- input/output JSON Schema；
- required capability/permission；
- risk level；
- idempotency requirement；
- ToolRequest → DataRequest mapper；
- DataResponse → ToolResponse mapper；
- contract/security tests。

新增 Tool 标准流程：

```text
新增 Tool Module
→ Registry 注册
→ 自动出现在 GET /dag/tools
→ 自动生成 GET /dag/tools/{tool_name}/schema
→ POST /dag/tools/execute 统一执行
→ 核心 Router 不修改
```

生产环境禁止调用方上传任意 Tool 代码。

## 6. 第一阶段 Tool：minio_file_access

第一阶段只实现 `minio_file_access`，正式 action：

- `list_objects`
- `get_metadata`
- `exists`
- `request_upload`
- `complete_upload`
- `request_download`
- `delete_object`

Claria Demo 的案件类动作只能作为迁移 alias，必须标记 deprecated，不能进入核心领域模型。

## 7. MinIO Tool 调用链

```text
Agent Tool Call
→ POST /dag/tools/execute
→ capability_token verification
→ Agent / tenant / biz context
→ Tool Registry resolve
→ action schema validation
→ minio_file_access mapper
→ 可选查询 GET /data/operations/{operation}/schema
→ DataRequest(target=MINIO)
→ POST /data/dispatch
→ MinIO Adapter
→ DataResponse
→ ToolResponse
```

DAG 不能接收或转发：

- `bucket`
- `object_key`
- `endpoint`
- `access_key`
- `secret_key`
- `local_path`
- `connection_string`
- raw SQL / Redis command / S3 command

## 8. Tool Registry

Registry 必须支持：

- `tool_name + version` 唯一注册；
- stable version 唯一解析；
- 重复注册拒绝；
- disabled Tool 不可发现和执行；
- action 级 Schema、capability 和风险声明；
- deprecation 和 alias 无环校验；
- Registry 启动校验与 readiness。

## 9. 身份与 capability token

- `GET /dag/tools` 必须依据可信 `agent_id + tenant_id + biz_domain` 过滤 Tool；
- `POST /dag/tools/execute` 必须验证 `capability_token`，不能信任请求体自报 roles/permissions；
- token 至少绑定 agent、tenant、biz_domain、tool、actions、有效期和 token id；
- 请求声明与 token claims 不一致时拒绝；
- capability token 不得传给存储 Adapter；
- DAG 应转换为 Layer 2 可验证的服务身份和受控上下文。

## 10. API 冻结

### `GET /dag/tools`

返回当前 Agent 有权发现的 Tool，未授权 Tool 不得出现。

### `GET /dag/tools/{tool_name}/schema`

返回指定 Tool 的版本、action、输入输出 Schema、capability、风险、幂等和 deprecation 信息。

### `POST /dag/tools/execute`

唯一 Tool 执行入口。禁止为每个 Tool 新增独立业务路由。

### 健康检查

可提供 `/health/live` 与 `/health/ready`，但不得替代上述正式接口。

## 11. Layer 2 依赖约束

DAG 必须通过 Data Control Client 使用：

- `GET /data/operations`
- `GET /data/operations/{operation}/schema`
- `POST /data/dispatch`

当前 Layer 2 若尚未实现 operation discovery/schema，必须先补齐或明确 feature gate；不得由 DAG 私自定义一套与 Layer 2 不一致的 operation 契约。

## 12. 禁止兼容偏离

不得将旧路径作为正式接口：

- `/tools/list`
- `/tools/schema`
- `/tools/execute`

如确需临时兼容，必须独立 deprecated adapter、增加 ADR、设置移除日期，核心代码和文档仍只认 `/dag/tools*`。

## 13. 非目标

本阶段不实现 PostgreSQL Tool、Redis Tool、动态插件市场、用户上传 Python Tool、远程代码执行和 OpenClaw 原生插件发布。