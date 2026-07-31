# Data Access Gateway 架构基线

## 1. 定位

Data Access Gateway（DAG）是面向 Agent、OpenClaw、Hermes 和其他受控 Tool 调用方的数据工具网关。

它位于 Agent Tool 层与数据库分发管控服务之间：

```text
Agent / OpenClaw / Hermes
        ↓
Data Access Gateway
GET  /tools/list
GET  /tools/schema
POST /tools/execute
        ↓
ToolRequest → DataRequest
        ↓
Data Control Service
POST /data/dispatch
        ↓
PostgreSQL / Redis / MinIO / future adapters
```

DAG 不直接访问 PostgreSQL、Redis、MinIO，也不持有这些存储的连接凭证。真实数据访问必须经过 Data Control Service。

## 2. 架构来源

实现必须以仓库 `其他服务/` 中的 Data Access Gateway 架构说明为最高业务架构依据。

`liuchuang164/claria` 中的旧 Demo 只用于参考 MinIO Tool 的动作设计、参数形态和 Agent 接入经验，不得复制其直连 MinIO、请求体自报权限、硬编码业务 Tool 或单文件路由模式。

## 3. 服务边界

DAG 负责：

1. Tool 发现与 Schema 输出；
2. ToolRequest 契约校验；
3. 可信 Agent 身份上下文解析；
4. Tool 权限和策略校验；
5. Tool 名称与版本解析；
6. ToolRequest 到 DataRequest 的确定性映射；
7. 调用 Data Control Service；
8. DataResponse 到 ToolResponse 的包装；
9. Tool 调用审计与错误码转换；
10. Tool Registry、版本和生命周期管理。

DAG 不负责：

- 直接连接任何数据库或对象存储；
- 执行 raw SQL、Redis command、S3/MinIO 原生命令；
- 业务任务规划或 Agent 编排；
- Hermes SOP 决策；
- OpenClaw Skill 推理；
- OCR、ASR、视频处理；
- 外部第三方 API 接入；
- 跨数据库事务。

## 4. 核心模块

```text
api/
  tools_list.py
  tools_schema.py
  tools_execute.py
application/
  tool_discovery_service.py
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
  audit_sink.py
infrastructure/
  registry/yaml_registry.py
  registry/in_memory_registry.py
  data_control/http_client.py
  auth/development_auth_provider.py
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

Domain 不得依赖 FastAPI、HTTPX、Pydantic Settings 或具体 SDK。

## 5. Tool 扩展模型

每个 Tool 必须由独立 Tool Module 定义，而不是在 Router 中增加 `if tool_name == ...`。

一个 Tool Module 至少提供：

- ToolDefinition；
- tool_name；
- version；
- description；
- actions；
- input schema；
- output schema；
- required permissions；
- risk level；
- idempotency requirements；
- ToolRequest → DataRequest mapper；
- DataResponse → ToolResponse mapper；
- contract tests。

新增 Tool 的标准步骤：

```text
新增 Tool Module
→ 注册 ToolDefinition
→ 自动出现在 /tools/list
→ 自动生成 /tools/schema
→ /tools/execute 统一执行
→ 不修改核心 Router
```

## 6. 第一阶段 Tool

第一阶段只实现：

```text
minio_file_access
```

建议动作：

- `list_objects`
- `get_metadata`
- `exists`
- `request_upload`
- `complete_upload`
- `request_download`
- `delete_object`

为兼容 Claria Demo，可提供受控 alias：

- `list_case_materials` → `list_objects`
- `get_file_metadata` → `get_metadata`
- `get_presigned_url` → `request_download`
- `upload_analysis_result` → `request_upload/complete_upload`

Alias 必须标记 deprecated，不得在核心领域模型中写死案件业务。

## 7. MinIO 调用链

```text
Agent Tool Call
→ POST /tools/execute
→ Tool schema validation
→ Agent identity and tenant scope
→ Tool permission check
→ minio_file_access mapper
→ DataRequest(target=MINIO)
→ POST /data/dispatch
→ MinIO Adapter
→ DataResponse
→ ToolResponse
```

DAG 不能接收或转发以下物理字段：

- bucket；
- object_key；
- endpoint；
- access_key；
- secret_key；
- local_path；
- connection string。

## 8. Tool Registry

Registry 必须支持：

- 按 tool_name + version 注册；
- 当前稳定版本解析；
- 重复注册拒绝；
- disabled Tool 不可发现和执行；
- action 级能力；
- schema 输出；
- permission 声明；
- Tool deprecation；
- Tool alias；
- Registry 启动校验；
- readiness 检查。

生产环境 Tool 定义优先来自受版本控制的配置或代码注册，不允许调用方动态上传任意 Tool 代码。

## 9. 安全边界

- 请求体只能声明 tenant_id、biz_domain、actor 和 Tool 参数；
- roles、permissions 必须来自可信 AuthProvider；
- Tool 参数必须 `extra=forbid`；
- 未知 Tool、未知 action、未知字段全部拒绝；
- Tool Mapper 只能生成白名单 DataRequest；
- 所有 Tool 调用必须携带 request_id、trace_id、tool_call_id；
- 错误响应不得泄露 Data Control Service URL、存储信息或内部堆栈；
- 预签名 URL 不写日志和长期审计正文。

## 10. API

### GET /tools/list

返回调用方有权发现的 Tool，不返回无权限 Tool。

### GET /tools/schema

参数：`tool_name`、可选 `version`、可选 `action`。

返回 Tool 输入输出 Schema、动作、风险和幂等要求。

### POST /tools/execute

统一 Tool 执行入口。禁止为每个 Tool 新增独立业务路由。

### GET /health/live

仅检查进程。

### GET /health/ready

检查 AuthProvider、Tool Registry、Data Control Client 和必需 Tool 定义。

## 11. 非目标

本阶段不实现 PostgreSQL Tool、Redis Tool、动态插件市场、用户上传 Python Tool、远程代码执行和 OpenClaw 原生插件发布。架构必须为后续扩展预留，但不能提前混入本阶段。