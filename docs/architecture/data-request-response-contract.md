# 统一 DataRequest / DataResponse 契约

## 1. 版本规则

- 当前协议版本：`1.0`。
- 请求必须携带 `contract_version`。
- 小版本只允许向后兼容地增加可选字段。
- 删除字段、改变语义、改变默认值或收紧枚举必须升级主版本。

## 2. DataRequest

```json
{
  "contract_version": "1.0",
  "request_id": "req_01J...",
  "trace_id": "trace_01J...",
  "source": "BUSINESS_SERVICE",
  "auth_context": {
    "tenant_id": "tenant_001",
    "biz_domain": "demo",
    "actor": {
      "subject_id": "svc_demo",
      "subject_type": "SERVICE"
    }
  },
  "operation": "CREATE",
  "resource": {
    "target": "POSTGRESQL",
    "type": "DOCUMENT_RECORD",
    "name": "record",
    "resource_id": "doc_202607290001"
  },
  "payload": {
    "data": {},
    "query": {},
    "options": {}
  },
  "idempotency_key": "idem_01J...",
  "transaction": {
    "mode": "LOCAL",
    "isolation": "READ_COMMITTED"
  },
  "timeout_ms": 5000,
  "metadata": {
    "caller_service": "ontology-service"
  }
}
```

### 2.1 顶层字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `contract_version` | 是 | 协议版本。 |
| `request_id` | 是 | 调用方请求唯一标识；服务端校验格式与长度。 |
| `trace_id` | 否 | 未提供时由服务端生成。 |
| `source` | 是 | `BUSINESS_SERVICE`、`ONTOLOGY_SERVICE`、`DATA_ACCESS_GATEWAY`、`INTERNAL_JOB`。 |
| `auth_context` | 是 | 请求期望作用域；只允许声明 tenant、biz_domain、actor，最终可信权限来自服务端鉴权结果。 |
| `operation` | 是 | 标准操作枚举。 |
| `resource` | 是 | 逻辑资源描述，不允许物理连接信息。 |
| `payload` | 是 | 操作数据、查询和选项。 |
| `idempotency_key` | 写操作必填 | 不得含秘密或个人敏感信息。 |
| `transaction` | 否 | 事务期望；最终能力由服务端决定。 |
| `timeout_ms` | 否 | 服务端会应用上下限。 |
| `metadata` | 否 | 受限扩展字段，不参与授权事实。 |

### 2.2 Operation 枚举

首阶段冻结：

- `GET`
- `LIST`
- `SEARCH`
- `CREATE`
- `UPDATE`
- `UPSERT`
- `DELETE`
- `BATCH`
- `LOCK`
- `UNLOCK`

Adapter 只实现其声明支持的能力。未支持操作返回稳定错误，不做隐式降级。

### 2.3 Resource

- `target`：`POSTGRESQL | MINIO | REDIS | NEO4J | MILVUS | TIMESCALEDB`。
- `type`：平台注册的逻辑资源类型。
- `name`：逻辑资源名，禁止传物理表名、Bucket 凭据或连接串。
- `resource_id`：单资源操作使用。
- 可选 `data_class`：如 `TRANSACTIONAL`、`OBJECT`、`CACHE`、`GRAPH`、`VECTOR`、`TIME_SERIES`。

### 2.4 Payload

`payload.data` 用于写入；`payload.query` 用于过滤；`payload.options` 用于分页、排序、字段投影等。

禁止：

- raw SQL / raw Cypher；
- 任意 Redis 命令；
- 任意表达式拼接；
- 未注册对象路径；
- 绕过最大分页和批量限制的参数。

## 3. DataResponse

成功：

```json
{
  "contract_version": "1.0",
  "request_id": "req_01J...",
  "trace_id": "trace_01J...",
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {},
  "page": {
    "cursor": null,
    "limit": 50,
    "has_more": false
  },
  "meta": {
    "adapter": "postgresql",
    "route_id": "route_01J...",
    "duration_ms": 18,
    "idempotency_replayed": false
  }
}
```

失败：

```json
{
  "contract_version": "1.0",
  "request_id": "req_01J...",
  "trace_id": "trace_01J...",
  "success": false,
  "code": "AUTH_SCOPE_MISMATCH",
  "message": "request scope is not permitted",
  "error": {
    "category": "AUTHORIZATION",
    "retryable": false,
    "details": [],
    "incident_id": "inc_01J..."
  },
  "meta": {
    "duration_ms": 4
  }
}
```

## 4. 响应规则

- `success=true` 时 `code` 必须为 `OK` 或显式成功码。
- `success=false` 时必须存在目录中定义的错误码。
- 不把驱动堆栈、SQL、存储路径、连接信息和 Secret 返回给调用方。
- 批量请求使用逐项结果；部分成功不能伪装成完整成功。
- 删除、更新等写操作返回受影响数量和资源版本，但不默认返回完整敏感记录。

## 5. 分页与排序

- 默认采用 Cursor Pagination。
- `limit` 由服务端设置最大值。
- 排序字段必须来自资源注册表白名单。
- Cursor 必须签名或不可伪造，并绑定租户、资源、过滤条件和排序。

## 6. 幂等语义

- `CREATE / UPDATE / UPSERT / DELETE / BATCH / LOCK / UNLOCK` 默认视为写操作。
- 幂等摘要由规范化后的关键请求字段计算。
- 首次请求处于 `PROCESSING` 时，重复请求返回 `IDEMPOTENCY_IN_PROGRESS`，或在限定时间内等待同一结果。
- 已成功请求返回原结果并标记 `idempotency_replayed=true`。
- Key 相同而摘要不同返回 `IDEMPOTENCY_KEY_CONFLICT`。

## 7. ToolRequest 映射

Data Access Gateway 必须通过预注册映射完成：

```text
tool_name + action -> operation + resource.target + resource.type + payload schema
```

Tool 参数不得直接决定物理数据源、表名或查询语句。映射失败返回 Tool 层错误，不能把未知 Tool 透传给 `/data/dispatch`。
