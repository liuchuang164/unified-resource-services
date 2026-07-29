# Phase 0 API 与 Tool 契约

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | 进程健康 |
| GET | `/ready` | Phase 0 依赖就绪 |
| POST | `/api/v1/operations/execute` | 业务服务及 Gateway 的 Unified Entry |
| GET | `/api/v1/tools` | Tool 列表及 Schema |
| GET | `/api/v1/tools/{tool_name}/schema` | 单个 Tool Schema |
| POST | `/api/v1/tools/execute` | Agent Tool 执行入口 |

请求使用 `api_version`, `operation`, `context`, `payload`。统一响应固定为
`request_id`, `trace_id`, `success`, `data`, `error`。失败时 `data=null`，错误包含稳定
`code`, `message`, `retryable`, `details`；不返回堆栈和 SDK 原始异常。

## RequestContext

必填：`request_id`, `trace_id`, `tenant_id`, `biz_domain`, `caller_type`, `caller_id`。
Agent 额外必填 `agent_id`, `tool_call_id`, `capability_token`, `nonce`。写操作按契约要求
`idempotency_key`；`nonce` 用于 replay protection。HTTP 业务入口拒绝
`caller_type=agent`，只有进程内 Gateway 调用携带可信来源标记。上下文显式传递，不使用
全局/线程局部。

## Operations

| Operation | Payload | Idempotent |
|---|---|---|
| `file.initialize_upload` | filename, mime_type, size_bytes, owner_type, owner_id | yes |
| `file.get_resource` | resource_id | no |
| `media.create_stream_session` | protocol, direction | yes |
| `media.get_stream_session` | session_id | no |
| `media.close_stream_session` | session_id | yes |
| `media.submit_processing_job` | operation, input_resource_id, processor_type, options | yes |
| `media.get_processing_job` | job_id | no |

客户端传入 `bucket`, `object_key`, `physical_path`, `disk_path`,
`media_internal_path` 会因严格 Schema 被拒绝。
公共响应使用字段白名单，不返回 object key 或媒体服务器内部 endpoint。上传初始化只返回
不可反推物理位置的 opaque `upload_reference`。

## Tools

`file_media.list_tools`, `file_media.get_tool_schema`, `file.initialize_upload`,
`file.get_resource`, `media.create_stream_session`, `media.get_stream_session`,
`media.close_stream_session`, `media.submit_processing_job`,
`media.get_processing_job`。

两个 `file_media.*` 元数据 Tool 通过 GET discovery 接口提供；其余执行 Tool 均按固定 mapping
转换为同名 operation，再调用 Unified Entry。Gateway 不持有 Adapter。

## Idempotency

作用域为
`tenant_id + biz_domain + caller_id + operation + idempotency_key`。请求体按 canonical JSON
计算 SHA-256。Idempotency Port 以 `reserve / wait / complete / fail` 状态协议原子认领作用域，
持久化 Adapter 不回调业务逻辑；并发相同键也只产生一次 Adapter 副作用。相同键/相同请求
返回原结果；相同键/不同请求返回
`IDEMPOTENCY_CONFLICT`。

## Error codes

`INVALID_REQUEST`, `UNSUPPORTED_API_VERSION`, `UNSUPPORTED_OPERATION`,
`UNAUTHENTICATED`, `PERMISSION_DENIED`, `TENANT_SCOPE_MISMATCH`,
`RESOURCE_NOT_FOUND`, `FILE_RESOURCE_NOT_FOUND`, `STREAM_SESSION_NOT_FOUND`,
`PROCESSING_JOB_NOT_FOUND`, `INVALID_STATE_TRANSITION`, `IDEMPOTENCY_CONFLICT`,
`QUOTA_EXCEEDED`, `REPLAY_DETECTED`, `INVALID_OBJECT_NAME`, `ADAPTER_TIMEOUT`,
`ADAPTER_UNAVAILABLE`, `INTERNAL_ERROR`。
