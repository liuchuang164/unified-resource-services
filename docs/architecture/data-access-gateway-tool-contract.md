# Data Access Gateway Tool 契约

## 1. 两层接口冻结

### Layer 1：Data Access Gateway

```text
GET  /dag/tools
GET  /dag/tools/{tool_name}/schema
POST /dag/tools/execute
```

### Layer 2：数据库分发管控服务

```text
GET  /data/operations
GET  /data/operations/{operation}/schema
POST /data/dispatch
```

旧路径 `/tools/list`、`/tools/schema`、`/tools/execute` 不是正式接口。

## 2. ToolDefinition

```json
{
  "tool_name": "minio_file_access",
  "version": "1.0.0",
  "description": "受控对象存储访问工具",
  "enabled": true,
  "deprecated": false,
  "actions": [
    "list_objects",
    "get_metadata",
    "exists",
    "request_upload",
    "complete_upload",
    "request_download",
    "delete_object"
  ],
  "required_capabilities": ["tool:minio_file_access:execute"],
  "risk_level": "MEDIUM"
}
```

Tool 名称必须满足 `^[a-z][a-z0-9_.-]{2,127}$`，版本使用 SemVer。

## 3. ToolRequest

```json
{
  "protocol_version": "1.0",
  "request_id": "req_...",
  "trace_id": "trace_...",
  "tool_call_id": "toolcall_...",
  "agent_id": "agent_demo",
  "tenant_id": "tenant_demo",
  "biz_domain": "demo",
  "tool_name": "minio_file_access",
  "tool_version": "1.0.0",
  "action": "get_metadata",
  "params": {
    "logical_object_id": "obj_..."
  },
  "capability_token": "opaque-or-signed-token",
  "idempotency_key": null,
  "metadata": {}
}
```

约束：

- `extra=forbid`；
- roles、permissions 不得出现在请求体；
- `capability_token` 必须由可信 verifier 验证；
- token 必须绑定 agent、tenant、biz_domain、tool、action、有效期；
- 写 action 必须有 `idempotency_key`；
- `params` 必须由对应 action Schema 校验；
- 深层嵌套禁止物理存储字段。

## 4. ToolResponse

```json
{
  "protocol_version": "1.0",
  "request_id": "req_...",
  "trace_id": "trace_...",
  "tool_call_id": "toolcall_...",
  "tool_name": "minio_file_access",
  "tool_version": "1.0.0",
  "action": "get_metadata",
  "success": true,
  "code": "OK",
  "message": "Tool executed successfully.",
  "data": {},
  "error": null,
  "meta": {
    "latency_ms": 12,
    "downstream_request_id": "req_data_..."
  }
}
```

不得暴露 Data Control Service URL、bucket、physical object key、endpoint、credentials、SQL、Redis command 或内部堆栈。

## 5. `GET /dag/tools`

调用方必须提供或通过认证上下文解析：

```text
agent_id
tenant_id
biz_domain
```

返回当前 Agent 可发现的 Tool：

```json
{
  "tools": [
    {
      "tool_name": "minio_file_access",
      "version": "1.0.0",
      "description": "受控对象存储访问工具",
      "actions": ["list_objects", "get_metadata", "exists", "request_upload", "complete_upload", "request_download", "delete_object"]
    }
  ]
}
```

未授权 Tool 不得出现。

## 6. `GET /dag/tools/{tool_name}/schema`

Path 参数：`tool_name`。

可选 Query 参数：`version`、`action`。

输出必须包含：

- Tool 描述与版本；
- action 列表；
- 输入输出 JSON Schema；
- required capability；
- risk level；
- idempotency requirement；
- deprecation 信息。

## 7. `POST /dag/tools/execute`

执行流程：

```text
ToolRequest parse
→ capability token verify
→ agent / tenant / biz scope compare
→ Registry resolve
→ action schema validation
→ Tool authorization
→ ToolRequest Mapper
→ Data Control Client
→ ToolResponse Mapper
→ Tool audit
```

唯一执行入口，禁止每个 Tool 建独立业务路由。

## 8. Layer 2 operation discovery

DAG 通过以下接口确认 Layer 2 支持能力：

### `GET /data/operations`

按 tenant/biz context 返回可用 operation。

### `GET /data/operations/{operation}/schema`

返回 operation 的 DataRequest Schema、权限、限制和路由规则。

DAG 不得私自发明与 Layer 2 不一致的 operation。

## 9. MinIO Action Schemas

### `list_objects`

```json
{
  "resource_name": "asset",
  "page_size": 50,
  "page_token": null,
  "filters": {
    "status": "AVAILABLE",
    "content_type": "application/pdf"
  }
}
```

禁止 `prefix`、`bucket`、`object_key`。

### `get_metadata`

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_..."
}
```

### `exists`

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_..."
}
```

### `request_upload`

```json
{
  "resource_name": "asset",
  "filename": "contract.pdf",
  "content_type": "application/pdf",
  "size_bytes": 12345,
  "checksum_sha256": "..."
}
```

必须有 idempotency key。

### `complete_upload`

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_...",
  "checksum_sha256": "..."
}
```

必须有 idempotency key。

### `request_download`

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_...",
  "ttl_seconds": 300
}
```

预签名 URL 是临时敏感凭据，不得写日志、Metrics 或长期审计正文。

### `delete_object`

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_..."
}
```

必须有 idempotency key。

## 10. ToolRequest → DataRequest 映射

Mapper 必须确定且由服务端定义：

```text
minio_file_access.get_metadata
→ operation = GET
→ target = MINIO
→ resource.type = OBJECT_ASSET
→ resource.name = asset
→ payload.data.logical_object_id = ...
```

`target`、`resource_type`、`operation` 不得来自 `params`。

Layer 2 请求必须符合 `/data/operations/{operation}/schema` 和 `/data/dispatch` 契约。

## 11. capability token 最低要求

Token claims 至少包括：

```text
jti
issuer
audience
agent_id
tenant_id
biz_domain
tool_name
actions
issued_at
expires_at
```

要求：

- 签名或可信不透明 token 校验；
- audience 必须是 Data Access Gateway；
- token action 必须覆盖请求 action；
- token 不得过期；
- token 不得写入日志；
- token 不得透传给 MinIO Adapter。

## 12. 错误码

至少包含：

- `TOOL_NOT_FOUND`
- `TOOL_VERSION_NOT_FOUND`
- `TOOL_DISABLED`
- `TOOL_ACTION_NOT_SUPPORTED`
- `TOOL_SCHEMA_INVALID`
- `TOOL_CAPABILITY_REQUIRED`
- `TOOL_CAPABILITY_INVALID`
- `TOOL_CAPABILITY_EXPIRED`
- `TOOL_PERMISSION_DENIED`
- `TOOL_SCOPE_MISMATCH`
- `TOOL_MAPPING_FAILED`
- `DOWNSTREAM_UNAVAILABLE`
- `DOWNSTREAM_TIMEOUT`
- `DOWNSTREAM_SCHEMA_MISMATCH`
- `DOWNSTREAM_ERROR`
- `TOOL_EXECUTION_FAILED`

Downstream 错误必须转换为 Tool 语义，同时保留 code、retryable 和 trace 关联，不得泄露内部正文。

## 13. 扩展兼容性

新增 Tool 不得修改：

- `POST /dag/tools/execute` Router 主流程；
- ToolRequest 基础模型；
- Data Control Client；
- 其他 Tool Module。

新增 Tool 只新增 Definition、Schema、Mapper、Response Mapper、Registry registration 和测试。