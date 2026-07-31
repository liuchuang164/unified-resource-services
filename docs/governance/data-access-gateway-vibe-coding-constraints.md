# Data Access Gateway Vibe Coding 约束

## 1. 目标

所有 AI/Codex 开发必须将 Data Access Gateway 实现为可扩展的 Tool 网关，而不是新的数据库代理、MinIO 代理或业务服务。

## 2. 强制架构

```text
API
→ Application Tool Pipeline
→ Domain / Ports
→ Tool Modules + Infrastructure
→ Data Control Service HTTP API
```

禁止 DAG 直接依赖：

- asyncpg / psycopg；
- redis-py；
- MinIO/S3 SDK；
- 数据库存储凭证；
- 物理表、bucket、object key。

## 3. 单一数据出口

所有 Tool 数据访问只能调用：

```text
Data Control Service POST /data/dispatch
```

不得为测试方便增加存储直连后门。

## 4. Tool 快速扩展要求

新增 Tool 必须在不修改核心 Router 的情况下完成。

每个 Tool Module 必须独立提供：

- definition；
- schemas；
- mapper；
- response mapper；
- registration；
- contract tests；
- security tests。

核心代码中禁止出现持续增长的：

```python
if tool_name == "...":
    ...
elif tool_name == "...":
    ...
```

Registry 必须是唯一解析入口。

## 5. Claria Demo 使用边界

可以参考：

- MinIO Tool action 命名；
- list/read/presign/upload 的用户体验；
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

## 6. 第一阶段范围

只实现 `minio_file_access`。

不得同时开发 PostgreSQL Tool、Redis Tool、OCR Tool、ASR Tool、External API Tool。

第一阶段允许的动作：

- list_objects；
- get_metadata；
- exists；
- request_upload；
- complete_upload；
- request_download；
- delete_object。

## 7. 安全约束

- 请求体不能声明 roles/permissions；
- 身份必须由 AuthProvider 生成；
- tenant_id、biz_domain、actor 与认证事实不一致时拒绝；
- params 使用严格模型和 `extra=forbid`；
- 深层递归阻断 bucket、object_key、endpoint、secret、raw SQL、Redis command；
- 预签名 URL 不进入日志、Metrics 和长期审计；
- Tool discovery 必须按权限过滤；
- 禁止返回内部 DataRequest 全文。

## 8. HTTP Client 约束

Data Control Client 必须具备：

- 连接池；
- connect/read/write/pool timeout；
- 最大并发；
- retry 仅用于明确安全的连接失败；
- 写请求重试必须复用 idempotency key；
- 熔断或失败计数接口；
- graceful shutdown；
- URL 脱敏；
- 统一错误映射。

禁止无限 retry。

## 9. Tool Registry 约束

必须验证：

- tool_name 唯一；
- tool_name + version 唯一；
- stable version 唯一；
- alias 无循环；
- action Schema 存在；
- Mapper 存在；
- permission 非空；
- 写 action 标记幂等要求；
- disabled Tool 不执行。

Registry 校验失败时 readiness=false。

## 10. 测试门禁

至少建立：

```text
tests/unit/
tests/contract/
tests/security/
tests/integration/
tests/architecture/
```

必须覆盖：

- `/tools/list`；
- `/tools/schema`；
- `/tools/execute`；
- 未知 Tool；
- 未知 version；
- 未知 action；
- Tool 参数严格校验；
- 权限过滤；
- scope mismatch；
- ToolRequest 到 DataRequest 映射；
- Downstream success/error/timeout；
- MinIO Tool 全动作；
- 物理字段阻断；
- 预签名 URL 脱敏；
- 新增测试 Tool 不修改 Router；
- Domain 不依赖 FastAPI/HTTPX；
- DAG 不依赖存储 SDK。

## 11. 真实端到端测试

必须使用真实 Data Control Service 验证：

```text
/tools/execute
→ Data Control Service /data/dispatch
→ MinIO Adapter
→ MinIO
```

禁止只 Mock Downstream 就宣告完成。

必须同时保留 Mock/Stub 测试以覆盖故障路径。

## 12. 质量命令

```bash
ruff check .
ruff format --check .
mypy src
pytest -q
pytest --cov=src --cov-report=term-missing
```

核心覆盖率不得低于 85%。

## 13. 禁止测试作弊

禁止：

- 固定成功响应；
- Mock 被测试的 ToolExecutionService；
- 删除失败测试；
- 弱化断言；
- 将所有异常转为成功；
- 仅检查类是否存在；
- 用 curl 直接调 `/data/dispatch` 冒充 Tool Gateway 端到端测试。

## 14. Definition of Done

只有满足以下条件才能宣告第一阶段完成：

- 三个 Tool API 已实现；
- MinIO Tool 全动作已实现；
- Tool Registry 可扩展；
- DAG 不直连存储；
- 身份可信；
- Tool 参数安全；
- 真实 DAG → DCS → MinIO 链路通过；
- 原 PostgreSQL/Redis/MinIO DCS 回归通过；
- CI 全绿；
- 架构、运行手册和报告完成。