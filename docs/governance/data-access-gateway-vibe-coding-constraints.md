# Data Access Gateway Vibe Coding 约束

## 1. 目标

所有 AI/Codex 开发必须将 Data Access Gateway 实现为独立、可扩展的 Tool 网关，而不是新的数据库代理、MinIO 代理或业务服务。

## 2. 两层接口不可变

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

任何实现不得将两层合并，不得把 Layer 2 的 `/data/dispatch` 当作 Agent Tool 接口。

以下旧接口不得作为正式实现：

```text
/tools/list
/tools/schema
/tools/execute
```

## 3. 强制架构

```text
Agent / OpenClaw / Hermes
→ Layer 1 DAG API
→ Application Tool Pipeline
→ Tool Registry / Tool Module
→ ToolRequest → DataRequest Mapper
→ Layer 2 Data Control Client
→ /data/operations* + /data/dispatch
```

禁止 DAG 直接依赖：

- asyncpg / psycopg；
- redis-py；
- MinIO/S3 SDK；
- 数据库存储凭证；
- 物理表、bucket、object key。

## 4. 单一数据出口

所有 Tool 数据访问只能调用 Layer 2：

```text
GET  /data/operations
GET  /data/operations/{operation}/schema
POST /data/dispatch
```

不得为测试增加存储直连后门。

Layer 2 尚未实现 operation discovery/schema 时，必须补齐或通过明确 feature gate 阻止 DAG 上线；不得由 DAG 自建不一致契约。

## 5. Tool 快速扩展

每个 Tool Module 独立提供：

- definition；
- schemas；
- mapper；
- response mapper；
- registration；
- contract tests；
- security tests。

核心 Router 禁止出现：

```python
if tool_name == "...":
    ...
elif tool_name == "...":
    ...
```

Registry 是唯一 Tool 解析入口。

新增 Tool 必须自动进入：

```text
GET /dag/tools
GET /dag/tools/{tool_name}/schema
POST /dag/tools/execute
```

而不修改核心执行 Router。

## 6. 身份和 capability token

- `GET /dag/tools` 按可信 `agent_id + tenant_id + biz_domain` 过滤；
- `POST /dag/tools/execute` 必须验证 `capability_token`；
- 请求体不能声明可信 roles/permissions；
- token 必须绑定 agent、tenant、biz_domain、tool、actions、audience、有效期；
- 请求声明与 token claims 不一致时拒绝；
- capability token 不得写日志或透传给 Adapter；
- DAG 调 Layer 2 时必须使用受控服务身份和业务上下文。

## 7. Claria Demo 使用边界

可以参考：

- MinIO action 命名和用户体验；
- Tool manifest；
- OpenClaw 插件适配经验。

禁止复制：

- DAG 直连 MinIO；
- 请求体自报 role/permission；
- 本地路径上传；
- `download_file` 写服务器任意目录；
- 案件业务硬编码；
- 单 Router + 大量分支；
- 捕获所有异常并返回 HTTP 200；
- 将内部异常字符串原样返回。

## 8. 第一阶段范围

只实现 `minio_file_access`：

- `list_objects`
- `get_metadata`
- `exists`
- `request_upload`
- `complete_upload`
- `request_download`
- `delete_object`

不得同时开发 PostgreSQL Tool、Redis Tool、OCR Tool、ASR Tool、External API Tool。

## 9. 安全约束

- Pydantic 严格模型，`extra=forbid`；
- 深层递归阻断 bucket、object_key、endpoint、secret、local_path、raw SQL、Redis command；
- target、resource type、operation 由 Mapper 决定；
- 预签名 URL 不进入日志、Metrics 和长期审计；
- Tool discovery 必须按 capability 过滤；
- 禁止返回完整内部 DataRequest；
- 未知 Tool/version/action/字段全部拒绝。

## 10. Data Control Client

必须具备：

- 连接池；
- connect/read/write/pool timeout；
- 最大并发；
- graceful shutdown；
- URL 脱敏；
- 统一错误映射；
- operation/schema 缓存及版本失效策略；
- 写请求重试复用 idempotency key；
- retry 仅限明确安全的连接失败；
- 禁止无限 retry。

DAG 不得绕过 `/data/operations/{operation}/schema` 长期维护一套独立数据 operation 定义。

## 11. Tool Registry

必须验证：

- `tool_name + version` 唯一；
- stable version 唯一；
- alias 无循环；
- action Schema 存在；
- Mapper 存在；
- required capability 非空；
- 写 action 标记幂等要求；
- disabled Tool 不发现、不执行。

Registry 校验失败时 readiness=false。

## 12. 测试门禁

至少建立：

```text
tests/unit/
tests/contract/
tests/security/
tests/integration/
tests/architecture/
```

必须覆盖：

- `GET /dag/tools`；
- `GET /dag/tools/{tool_name}/schema`；
- `POST /dag/tools/execute`；
- 旧 `/tools/*` 不作为正式接口；
- capability token 缺失、无效、过期和 scope mismatch；
- 未知 Tool/version/action；
- Tool 参数严格校验；
- ToolRequest → DataRequest 映射；
- `/data/operations*` 契约兼容；
- downstream success/error/timeout；
- MinIO Tool 全动作；
- 物理字段阻断；
- 预签名 URL 脱敏；
- 新增测试 Tool 不修改 Router；
- Domain 不依赖 FastAPI/HTTPX；
- DAG 不依赖存储 SDK。

## 13. 真实端到端测试

必须使用真实链路：

```text
POST /dag/tools/execute
→ Data Control Service /data/dispatch
→ MinIO Adapter
→ MinIO
```

并验证：

```text
GET /dag/tools
GET /dag/tools/{tool_name}/schema
GET /data/operations
GET /data/operations/{operation}/schema
```

直接 curl `/data/dispatch` 不能证明 DAG 可用。

## 14. 质量命令

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
pytest --cov=src --cov-report=term-missing
```

核心覆盖率不得低于 85%。

## 15. 禁止测试作弊

禁止固定成功响应、Mock ToolExecutionService 本身、删除失败测试、弱化断言、将异常转成功、仅检查类存在、用 `/data/dispatch` 冒充 DAG 端到端测试。

## 16. Definition of Done

只有满足以下条件才能宣告第一阶段完成：

- 三个 `/dag/tools*` 接口实现；
- 两个 Layer 2 operation discovery/schema 接口可用；
- MinIO Tool 全动作实现；
- Tool Registry 可快速扩展；
- capability token 可信；
- DAG 不直连存储；
- 真实 DAG → DCS → MinIO 链路通过；
- PostgreSQL/Redis/MinIO DCS 回归通过；
- CI 全绿；
- 架构、运行手册和报告完成。