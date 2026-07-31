# Data Access Gateway Tool 契约

## 1. ToolDefinition

```json
{
  "tool_name": "minio_file_access",
  "version": "1.0.0",
  "description": "受控对象存储访问工具",
  "enabled": true,
  "deprecated": false,
  "actions": ["list_objects", "get_metadata", "exists", "request_upload", "complete_upload", "request_download", "delete_object"],
  "required_permissions": ["tool:minio_file_access:execute"],
  "risk_level": "MEDIUM"
}
```

Tool 名称必须满足：

```text
^[a-z][a-z0-9_.-]{2,127}$
```

Version 使用 SemVer。

## 2. ToolRequest

```json
{
  "protocol_version": "1.0",
  "request_id": "req_...",
  "trace_id": "trace_...",
  "tool_call_id": "toolcall_...",
  "tool_name": "minio_file_access",
  "tool_version": "1.0.0",
  "action": "get_metadata",
  "tenant_id": "tenant_demo",
  "biz_domain": "demo",
  "actor": {
    "subject_id": "agent_demo",
    "subject_type": "AGENT"
  },
  "params": {
    "logical_object_id": "obj_..."
  },
  "idempotency_key": null,
  "metadata": {}
}
```

约束：

- `extra=forbid`；
- roles 和 permissions 不得出现在请求体；
- 写操作必须有 `idempotency_key`；
- tenant、biz_domain、actor 必须和可信 AuthProvider 结果一致；
- metadata 只允许白名单字段且有限长；
- params 必须由对应 Tool Action Schema 校验；
- 禁止 params 深层嵌套出现物理存储字段。

## 3. ToolResponse

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

ToolResponse 不得暴露：

- Data Control Service URL；
- bucket；
- physical object key；
- endpoint；
- credentials；
- SQL、Redis command；
- 内部异常堆栈。

## 4. GET /tools/list

返回当前调用方可发现的 Tool：

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

未授权 Tool 不得出现在结果中。

## 5. GET /tools/schema

输入：

```text
tool_name
version（可选）
action（可选）
```

输出必须包含：

- Tool 描述；
- version；
- action；
- JSON Schema；
- required permission；
- risk level；
- idempotency requirement；
- deprecation 信息。

## 6. POST /tools/execute

执行流程：

```text
ToolRequest parse
→ Trusted identity
→ scope comparison
→ Registry resolve
→ action schema validation
→ permission/policy
→ mapper
→ Data Control HTTP client
→ response mapper
→ audit
→ ToolResponse
```

## 7. MinIO Action Schemas

### list_objects

输入：

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

### get_metadata

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_..."
}
```

### exists

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_..."
}
```

### request_upload

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

### complete_upload

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_...",
  "checksum_sha256": "..."
}
```

必须有 idempotency key。

### request_download

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_...",
  "ttl_seconds": 300
}
```

返回的预签名 URL 视为临时敏感凭据，不得写日志。

### delete_object

```json
{
  "resource_name": "asset",
  "logical_object_id": "obj_..."
}
```

必须有 idempotency key。

## 8. ToolRequest → DataRequest 映射

Mapper 必须是确定性的，调用方不能覆盖映射结果。

映射示例：

```text
minio_file_access.get_metadata
→ target = MINIO
→ operation = GET
→ resource.type = OBJECT_ASSET
→ resource.name = asset
→ payload.data.logical_object_id = ...
```

Tool Mapper 必须从服务端定义中取得 target、resource_type、允许 operation，不得从 Tool params 中读取 target。

## 9. 错误码

至少包含：

- `TOOL_NOT_FOUND`
- `TOOL_VERSION_NOT_FOUND`
- `TOOL_DISABLED`
- `TOOL_ACTION_NOT_SUPPORTED`
- `TOOL_SCHEMA_INVALID`
- `TOOL_PERMISSION_DENIED`
- `TOOL_SCOPE_MISMATCH`
- `TOOL_MAPPING_FAILED`
- `DOWNSTREAM_UNAVAILABLE`
- `DOWNSTREAM_TIMEOUT`
- `DOWNSTREAM_ERROR`
- `TOOL_EXECUTION_FAILED`

Downstream 的存储错误必须转换为 Tool 语义，但保留可判定的 code 和 retryable，不得原样泄露内部错误正文。

## 10. 扩展兼容性

新增 Tool 不得修改：

- `/tools/execute` Router 主流程；
- ToolRequest 基础模型；
- Data Control Client；
- 其他 Tool Module。

新增 Tool 只允许新增定义、Schema、Mapper、Response Mapper、注册和测试。