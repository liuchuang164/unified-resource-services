# 错误码目录

## 1. 设计规则

- 错误码稳定、机器可读、全大写下划线格式。
- HTTP 状态码表达传输层类别，业务处理以 `DataResponse.code` 为准。
- 每个错误明确 `retryable`。
- 不以 `500` 代替所有失败，不将权限拒绝伪装成资源不存在，除非安全策略明确要求。

## 2. HTTP 映射

| HTTP | 场景 |
|---:|---|
| 200 | 成功；批量逐项结果也可使用 200。 |
| 400 | 协议、字段、操作组合非法。 |
| 401 | 未认证或凭据失效。 |
| 403 | 已认证但无权限、作用域不匹配或策略拒绝。 |
| 404 | 已授权作用域内的逻辑资源不存在。 |
| 409 | 幂等冲突、版本冲突、锁冲突、并发冲突。 |
| 413 | Payload 或批量大小超限。 |
| 422 | 请求结构合法但资源语义不满足。 |
| 429 | 限流或容量保护。 |
| 500 | 未分类内部故障。 |
| 502 | Adapter/依赖返回无效结果或网关错误。 |
| 503 | 依赖不可用、连接池耗尽、熔断。 |
| 504 | 下游超时。 |

## 3. 冻结错误码

### 3.1 Contract

| Code | HTTP | Retryable | 含义 |
|---|---:|---:|---|
| `CONTRACT_VERSION_UNSUPPORTED` | 400 | 否 | 协议版本不支持。 |
| `REQUEST_SCHEMA_INVALID` | 400 | 否 | 请求结构或字段非法。 |
| `OPERATION_NOT_SUPPORTED` | 422 | 否 | 目标 Adapter 不支持该操作。 |
| `RESOURCE_TYPE_UNKNOWN` | 422 | 否 | 逻辑资源未注册。 |
| `PAYLOAD_TOO_LARGE` | 413 | 否 | 请求体或批量超限。 |

### 3.2 Authentication / Authorization

| Code | HTTP | Retryable | 含义 |
|---|---:|---:|---|
| `AUTH_REQUIRED` | 401 | 否 | 缺少认证。 |
| `AUTH_TOKEN_INVALID` | 401 | 否 | 凭据无效。 |
| `AUTH_TOKEN_EXPIRED` | 401 | 否 | 凭据过期。 |
| `AUTH_SCOPE_MISMATCH` | 403 | 否 | tenant_id 或 biz_domain 与可信声明不一致。 |
| `PERMISSION_DENIED` | 403 | 否 | RBAC/资源权限拒绝。 |
| `POLICY_DENIED` | 403 | 否 | ABAC 或高风险策略拒绝。 |
| `FIELD_ACCESS_DENIED` | 403 | 否 | 字段级访问被拒绝。 |

### 3.3 Idempotency / Concurrency

| Code | HTTP | Retryable | 含义 |
|---|---:|---:|---|
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | 否 | 写操作缺少幂等 Key。 |
| `IDEMPOTENCY_IN_PROGRESS` | 409 | 是 | 同 Key 请求仍在执行。 |
| `IDEMPOTENCY_KEY_CONFLICT` | 409 | 否 | 同 Key 对应不同请求摘要。 |
| `IDEMPOTENCY_RECOVERY_REQUIRED` | 409 | 否 | 业务写已成功但幂等完成记录需要管理员恢复，重试不会重新写目标库。 |
| `RESOURCE_VERSION_CONFLICT` | 409 | 是 | 乐观锁版本冲突。 |
| `LOCK_CONFLICT` | 409 | 是 | 锁被其他执行持有。 |
| `LOCK_NOT_ACQUIRED` | 409 | 是 | Redis 锁未获得，通常表示同一逻辑资源已有有效租约。 |
| `LOCK_TOKEN_MISMATCH` | 409 | 否 | 解锁 token 与当前锁 owner 不一致，禁止释放他人锁。 |

### 3.4 Routing / Adapter

| Code | HTTP | Retryable | 含义 |
|---|---:|---:|---|
| `ROUTE_NOT_FOUND` | 422 | 否 | 无匹配路由。 |
| `ADAPTER_NOT_REGISTERED` | 500 | 否 | 配置声明的 Adapter 未注册。 |
| `ADAPTER_UNAVAILABLE` | 503 | 是 | Adapter 或连接池不可用。 |
| `ADAPTER_AUTHENTICATION_FAILED` | 401 | 否 | Adapter 依赖认证失败，如 Redis ACL/密码错误。 |
| `ADAPTER_CAPACITY_EXCEEDED` | 503 | 是 | Adapter 连接池、并发或容量保护耗尽。 |
| `ADAPTER_TIMEOUT` | 504 | 是 | 下游执行超时。 |
| `ADAPTER_RESPONSE_INVALID` | 502 | 视情况 | 下游响应不符合契约。 |
| `DEPENDENCY_RATE_LIMITED` | 429 | 是 | 下游或本服务限流。 |
| `CIRCUIT_OPEN` | 503 | 是 | 熔断器开启。 |

### 3.5 Data / Transaction

| Code | HTTP | Retryable | 含义 |
|---|---:|---:|---|
| `RESOURCE_NOT_FOUND` | 404 | 否 | 授权范围内资源不存在。 |
| `DATA_CONFLICT` | 409 | 是 | 数据状态冲突但不属于版本或锁专用错误，例如条件写未满足。 |
| `DATA_CONSTRAINT_VIOLATION` | 422 | 否 | 唯一性、引用或字段约束失败。 |
| `TRANSACTION_NOT_SUPPORTED` | 422 | 否 | 请求的事务语义无法满足。 |
| `TRANSACTION_ROLLED_BACK` | 409 | 是 | 事务因并发或暂时错误回滚。 |
| `TRANSACTION_DEADLOCK` | 409 | 是 | PostgreSQL deadlock，事务已回滚。 |
| `TRANSACTION_SERIALIZATION_FAILURE` | 409 | 是 | PostgreSQL serialization failure，事务已回滚。 |
| `PARTIAL_FAILURE` | 200/502 | 视逐项结果 | BEST_EFFORT 批次存在失败。 |

### 3.6 Audit / Internal

| Code | HTTP | Retryable | 含义 |
|---|---:|---:|---|
| `AUDIT_WRITE_FAILED` | 500/503 | 是 | 必须审计的操作无法落审计。 |
| `CONFIGURATION_INVALID` | 500 | 否 | 启动或运行配置非法。 |
| `INTERNAL_ERROR` | 500 | 是 | 未分类内部错误，必须带 incident_id。 |

## 4. 重试规则

- 只有 `retryable=true` 才允许自动重试。
- 写操作重试必须复用同一 `idempotency_key`。
- 权限、Schema、语义和幂等冲突不得盲目重试。
- 退避、最大次数和总时限由调用策略明确配置。
- `INTERNAL_ERROR` 虽可标为可重试，也必须告警和保留 incident_id。
