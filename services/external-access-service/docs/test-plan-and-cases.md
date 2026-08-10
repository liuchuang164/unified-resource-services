# External Access Service 测试文档

适用范围：`services/external-access-service`

本文档描述完整测试项、测试用例、输入和预期输出，供 QA、研发和运维验收使用。

## 1. 测试范围

覆盖内容：

- Agent Tool entry：`/eag/tools`、`/eag/tools/{tool_name}/schema`、`/eag/tools/execute`
- Business unified entry：`/external/operations`、`/external/operations/{operation}/schema`、`/external/dispatch`
- Provider Runtime：`ALI_FARUI` 注册、路由、健康状态、fallback 行为
- Governance：可信上下文、capability token、policy、quota、rate limit、retry、circuit breaker
- Security：租户隔离、敏感信息脱敏、审计不落原文和密钥
- Real Farui gate：真实法睿链路，显式开启后执行

不覆盖内容：

- 其他 provider 的真实生产接入。
- 独立 `farui-service` 或 `farui-gateway`。
- 前端页面。

## 2. 测试命令

### 2.1 默认完整测试

```bash
cd services/external-access-service
PYTHONPATH=src python -m pytest -q
```

当前基线结果：

```text
56 passed, 2 skipped
```

说明：2 个 skipped 是真实法睿门禁，需要显式设置 `RUN_REAL_FARUI_GATE=1`。

### 2.2 静态检查

```bash
PYTHONPATH=src python -m ruff check .
PYTHONPATH=src python -m mypy src/external_access_service
```

预期：

```text
All checks passed!
Success: no issues found in 58 source files
```

### 2.3 真实法睿门禁

```bash
RUN_REAL_FARUI_GATE=1 PYTHONPATH=src python -m pytest tests/integration/test_real_farui_gate.py -q
```

预期：

```text
2 passed
```

真实门禁输入来自受控环境变量或 CSV 凭据文件，不得把密钥写入测试报告。

## 3. 公共测试数据

### 3.1 租户和业务域

| 字段 | 默认值 |
|---|---|
| `tenant_id` | `tenant_A` |
| `biz_domain` | `LEGAL` |
| `user_id` | `user_001` |
| Agent role | `AGENT` |
| Business role | `LAWYER` |

### 3.2 Tool 和 operation

| Tool | Action | Operation |
|---|---|---|
| `ali_farui` | `legal_consult` | `ALI_FARUI_LEGAL_CONSULT` |
| `ali_farui` | `law_search` | `ALI_FARUI_LAW_SEARCH` |
| `ali_farui` | `case_search` | `ALI_FARUI_CASE_SEARCH` |
| `ali_farui` | `legal_research_full` | `ALI_FARUI_LEGAL_RESEARCH_FULL` |

### 3.3 合法 payload

```json
{
  "query": "民间借贷纠纷中只有转账记录时如何主张还款",
  "limit": 2
}
```

### 3.4 Business dispatch 输入模板

```json
{
  "request_id": "req_001",
  "trace_id": "trace_001",
  "request_source": "BUSINESS_SERVICE",
  "auth_context": {
    "tenant_id": "tenant_A",
    "user_id": "user_001",
    "roles": ["LAWYER"]
  },
  "biz_context": {
    "biz_domain": "LEGAL",
    "biz_scene": "LEGAL_RESEARCH"
  },
  "operation": "ALI_FARUI_CASE_SEARCH",
  "provider": {
    "provider_code": "ALI_FARUI",
    "capability": "LEGAL_RESEARCH"
  },
  "payload": {
    "query": "民间借贷纠纷中只有转账记录时如何主张还款",
    "limit": 2
  },
  "policy": {
    "timeout_ms": 60000,
    "retry": {
      "enabled": false,
      "max_attempts": 1
    }
  }
}
```

预期输出关键字段：

```json
{
  "status": "SUCCEEDED",
  "provider": "ALI_FARUI",
  "operation": "ALI_FARUI_CASE_SEARCH",
  "data": {
    "summary": "非空"
  },
  "error": null
}
```

### 3.5 Agent Tool execute 输入模板

```json
{
  "request_id": "req_agent_001",
  "trace_id": "trace_agent_001",
  "agent_id": "agent_001",
  "tool_call_id": "tool_call_001",
  "tenant_id": "tenant_A",
  "biz_domain": "LEGAL",
  "tool_name": "ali_farui",
  "action": "case_search",
  "capability_token": "<signed capability token>",
  "input": {
    "query": "民间借贷纠纷中只有转账记录时如何主张还款",
    "limit": 2
  }
}
```

预期输出关键字段：

```json
{
  "tool_name": "ali_farui",
  "action": "case_search",
  "response": {
    "status": "SUCCEEDED",
    "provider": "ALI_FARUI",
    "operation": "ALI_FARUI_CASE_SEARCH",
    "data": {
      "summary": "非空"
    },
    "error": null
  }
}
```

## 4. 测试用例矩阵

### 4.1 HTTP Contract

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| HTTP-001 | `test_health_and_ready` | 健康和就绪检查 | `GET /health`, `GET /ready` | HTTP 200；`health.status=ok`；`ready.status=ready` |
| HTTP-002 | `test_external_operations_and_schema` | operation 列表和 schema | `tenant_id=tenant_A`, `biz_domain=LEGAL`; schema 查询 | 返回 4 个 `ALI_FARUI_*` operations；schema 要求 `query` |
| HTTP-003 | `test_external_dispatch_success` | 业务统一入口成功调用 | 合法 Business dispatch payload | `status=SUCCEEDED`，provider 为 `ALI_FARUI` |
| HTTP-004 | `test_missing_tenant_is_rejected` | 缺少租户参数 | 不传 `tenant_id` | HTTP 422 或失败响应 |
| HTTP-005 | `test_unknown_operation_fails_closed` | 未知 operation fail closed | `operation=UNKNOWN` | 返回失败，错误码表示 operation 未注册 |
| HTTP-006 | `test_scope_conflict_fails_closed` | Header 与 body scope 冲突 | Header tenant 与 body tenant 不一致 | 返回失败，不允许跨 scope |
| HTTP-007 | `test_agent_tools_contracts` | Agent tools/schema 合约 | `GET /eag/tools`, `GET /eag/tools/ali_farui/schema` | 返回 `ali_farui` 和 4 个 actions |
| HTTP-008 | `test_tool_execute_goes_through_unified_entry` | Agent Tool 执行统一入口 | 合法 Tool execute payload + token | `response.status=SUCCEEDED`，走 canonical operation |

### 4.2 E2E

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| E2E-001 | `test_business_and_agent_paths_share_unified_response` | Business 和 Agent 路径一致性 | 同类法律问题，分别走 `/external/dispatch` 和 `/eag/tools/execute` | 两条路径 operation/provider 一致，均经统一入口 |

### 4.3 ALI_FARUI Adapter 故障注入

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| FARUI-001 | `test_farui_request_mapping_and_signature` | ACS3 请求映射和签名 | `ALI_FARUI_LEGAL_RESEARCH_FULL` payload | path 为 `/{workspace}/farui/search/case/fulltext`；Authorization 以 `ACS3-HMAC-SHA256` 开头 |
| FARUI-002 | `test_farui_http_error_mapping[401]` | 401 映射 | Provider 返回 401 | `PROVIDER_AUTH_FAILED` |
| FARUI-003 | `test_farui_http_error_mapping[403]` | 403 映射 | Provider 返回 403 | `PROVIDER_AUTH_FAILED` |
| FARUI-004 | `test_farui_http_error_mapping[429]` | 限流映射 | Provider 返回 429 | `PROVIDER_RATE_LIMITED` |
| FARUI-005 | `test_farui_http_error_mapping[500]` | 服务不可用映射 | Provider 返回 500 | `PROVIDER_UNAVAILABLE` |
| FARUI-006 | `test_farui_non_json_response` | 非 JSON 响应 | Provider 返回 `not-json` | `PROVIDER_BAD_RESPONSE` |
| FARUI-007 | `test_farui_empty_response` | 空响应 | Provider 返回 `{}` | `PROVIDER_BAD_RESPONSE` |
| FARUI-008 | `test_farui_retry_success` | 可重试错误后成功 | 第一次 500，第二次 200 | 最终 `SUCCEEDED`，attempt=2 |
| FARUI-009 | `test_farui_retry_exhausted` | 重试耗尽 | 多次 500 | `PROVIDER_UNAVAILABLE` |
| FARUI-010 | `test_farui_connection_failure` | 网络连接失败 | transport 抛出连接错误 | `PROVIDER_UNAVAILABLE` |

### 4.4 真实法睿门禁

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| REAL-001 | `test_real_farui_gate_business_path_three_tools` | Business path 三工具真实外呼 | `legal_consult`、`law_search`、`case_search`，真实 CSV 或 env 凭据 | 每个 operation `SUCCEEDED`，`data.summary` 非空 |
| REAL-002 | `test_real_farui_gate_agent_path_three_tools` | Agent path 三工具真实外呼 | `legal_consult`、`law_search`、`case_search`，capability token + 真实凭据 | 每个 action `response.status=SUCCEEDED`，`summary` 非空 |

运行条件：

```bash
RUN_REAL_FARUI_GATE=1
```

未设置时预期输出：

```text
2 skipped
```

### 4.5 Unified Entry 集成

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| UE-001 | `test_unified_entry_audits_allowed_call` | 允许调用审计 | 合法 dispatch request | 成功响应；审计记录存在 |
| UE-002 | `test_biz_domain_mismatch_is_rejected` | biz_domain 不匹配 | 不允许的 biz_domain | 失败响应 |
| UE-003 | `test_unregistered_provider_is_rejected` | 未注册 provider | 未注册 provider code | 失败响应 |
| UE-004 | `test_payload_unknown_sensitive_fields_rejected` | payload 敏感字段拒绝 | payload 中含 `authorization` 等敏感字段 | 失败响应，不进入 provider |

### 4.6 审计、用量、配额

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| AUDIT-001 | `test_audit_query_is_persistent_and_scoped` | 审计持久化和 scope | 合法调用后按租户查询 | 只返回当前 `tenant_id + biz_domain` 审计 |
| AUDIT-002 | `test_failed_call_is_audited` | 失败调用审计 | 构造失败调用 | 审计记录状态为失败 |
| AUDIT-003 | `test_usage_query_groups_by_operation` | 用量按 operation 聚合 | 多次调用后查询 usage | 按 operation 返回用量 |
| AUDIT-004 | `test_usage_isolation_blocks_cross_tenant_query` | 用量租户隔离 | 跨租户查询 | 不返回其他租户数据 |
| AUDIT-005 | `test_quota_exceeded` | 配额超限 | 超过 quota 调用 | 返回 quota 错误 |

### 4.7 Capability Governance

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| CAP-001 | `test_valid_capability_token_allows_tool_execution` | 有效 token 允许调用 | 未过期、scope 匹配 token | Tool 调用成功 |
| CAP-002 | `test_expired_capability_token_rejected` | 过期 token 拒绝 | expires_at 已过期 | 调用失败 |
| CAP-003 | `test_invalid_signature_rejected` | 签名错误拒绝 | 篡改 token | 调用失败 |
| CAP-004 | `test_operation_scope_denied` | operation scope 拒绝 | token 不含当前 action | 调用失败 |
| CAP-005 | `test_tenant_scope_denied` | tenant scope 拒绝 | token tenant 与请求不一致 | 调用失败 |

### 4.8 身份上下文

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| ID-001 | `test_header_trusted_context_overrides_legacy_body` | Header 可信上下文优先 | Header 和 body 都带 scope | 使用 Header 可信 scope |
| ID-002 | `test_header_tenant_conflict_rejected` | Header tenant 冲突 | Header tenant 与 body tenant 冲突 | 调用失败 |
| ID-003 | `test_context_spoofing_inside_payload_rejected` | payload 伪造上下文拒绝 | payload 内含 `tenant_id` 或 `biz_domain` | 调用失败 |

### 4.9 安全加固

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| SEC-001 | `test_sensitive_data_masker_covers_phase2_terms` | 敏感字段脱敏 | 包含 token、secret、authorization 的结构 | 输出中敏感值被 mask |
| SEC-002 | `test_logs_do_not_include_secret_values` | 日志不泄密 | 产生带密钥的异常或日志上下文 | 日志中不出现 secret 原值 |
| SEC-003 | `test_recursive_redaction` | 递归脱敏 | 嵌套 dict/list 中包含 secret | 所有层级敏感字段被 mask |
| SEC-004 | `test_tenant_a_cannot_use_tenant_b_scope` | 跨租户 scope 拒绝 | tenant_A 请求 tenant_B 数据 | 调用失败 |
| SEC-005 | `test_audit_does_not_store_query_or_secrets` | 审计不存原文和密钥 | payload 含 query 与密钥形态字段 | 审计仅存 hash/safe summary |

### 4.10 生产治理

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| PROD-001 | `test_audit_publisher_failure_does_not_affect_business` | 审计发布失败不影响业务 | 审计 publisher 抛错 | 业务调用仍按规则返回 |
| PROD-002 | `test_quota_policy_repository_enforces_operation_quota` | 配额策略仓库 | operation quota 超限 | 拒绝调用 |
| PROD-003 | `test_rate_limit_token_consumption_and_retry_after` | Rate limit token 消耗 | 连续请求超过容量 | 返回限流和 retry-after |
| PROD-004 | `test_circuit_breaker_open_half_open_and_recovery` | 熔断器状态转换 | 多次失败后恢复 | open -> half-open -> closed |
| PROD-005 | `test_retry_after_header_is_used_for_429` | 429 retry-after 处理 | Provider 返回 429 + retry-after | 错误 details 含 retry-after |
| PROD-006 | `test_400_does_not_retry` | 400 不重试 | Provider 返回 400 | 不触发 retry |

### 4.11 Provider Runtime

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| RT-001 | `test_provider_registry_register_query_and_disable` | Provider 注册和禁用 | 注册、查询、disable provider | 状态变化符合预期 |
| RT-002 | `test_provider_lifecycle_enable_degraded_unavailable` | Provider 生命周期 | enable/degraded/unavailable | 状态符合预期 |
| RT-003 | `test_provider_routing_priority_and_unavailable_fallback` | 路由优先级和 fallback | primary unavailable | fallback provider 被选中 |
| RT-004 | `test_provider_apis` | Provider 管理 API | `/external/providers*` | 返回 provider、health、operations |
| RT-005 | `test_multi_provider_fallback_to_mock` | 多 provider fallback | ALI_FARUI 不可用，mock enabled | fallback 到 mock provider |
| RT-006 | `test_ali_farui_success_uses_primary_provider` | ALI_FARUI primary 成功 | ALI_FARUI 正常 | 使用 primary provider |

### 4.12 Unit

| ID | Pytest 用例 | 测试项 | 输入 | 预期输出 |
|---|---|---|---|---|
| UNIT-001 | `test_operation_registry_filters_by_tenant_and_biz_domain` | Operation registry 过滤 | `tenant_A + LEGAL` | 返回已启用 operations |
| UNIT-002 | `test_operation_registry_unknown_operation` | 未知 operation | 不存在 operation | 抛出或返回 operation not found |
| UNIT-003 | `test_tool_mapping_uses_canonical_operations` | Tool action 映射 | 4 个 action | 映射到 4 个 canonical operations |

## 5. 手工 Smoke Test

### 5.1 健康检查

输入：

```bash
curl -s http://127.0.0.1:8000/health
```

预期输出：

```json
{"status":"ok"}
```

### 5.2 Agent tools 列表

输入：

```bash
curl -s "http://127.0.0.1:8000/eag/tools?tenant_id=tenant_A&biz_domain=LEGAL"
```

预期输出关键字段：

```json
{
  "tools": [
    {
      "tool_name": "ali_farui",
      "provider": "ALI_FARUI",
      "actions": [
        "legal_consult",
        "law_search",
        "case_search",
        "legal_research_full"
      ]
    }
  ]
}
```

### 5.3 Operations 列表

输入：

```bash
curl -s "http://127.0.0.1:8000/external/operations?tenant_id=tenant_A&biz_domain=LEGAL"
```

预期输出：包含 4 个 operations：

- `ALI_FARUI_LEGAL_CONSULT`
- `ALI_FARUI_LAW_SEARCH`
- `ALI_FARUI_CASE_SEARCH`
- `ALI_FARUI_LEGAL_RESEARCH_FULL`

## 6. 测试结论模板

```text
测试日期:
代码版本:
测试环境:

默认 pytest:
Ruff:
Mypy:
真实法睿门禁:

结论: PASS / FAIL / NOT_RUN
失败说明:
风险:
```

真实法睿门禁必须明确写 `PASS`、`FAIL` 或 `NOT_RUN`，不得用 mock 结果替代真实结果。
