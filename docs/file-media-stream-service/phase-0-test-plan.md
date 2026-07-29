# Phase 0 测试计划

| Layer | Assertions |
|---|---|
| Unit | 实体创建、允许/禁止状态迁移、重复关闭、文件名清洗、object key、上下文、响应形状、请求哈希、Tool mapping、日志脱敏 |
| Contract | OpenAPI 路径、Unified schema/response、Tool list/schema、版本错误、未知 operation、框架校验错误 |
| Integration | InMemory repository 的 tenant/domain 先行查询、上传撤销补偿 |
| E2E | Agent Tool → Gateway → Unified Entry → Use Case → Port → Adapter；业务服务直达 Unified Entry |
| Security | 跨 tenant/domain、Agent 直调拒绝、缺失 scope/caller、默认拒绝、Agent token/nonce、replay、路径穿越/双扩展、客户端物理路径、并发幂等、配额消费、真实日志秘密 |
| Failure injection | Adapter 异常不泄漏 SDK 信息、event 失败上传补偿、processor 失败持久 FAILED、close 元数据失败发 reconciliation 事件 |

门禁命令：

```bash
ruff check .
ruff format --check .
mypy src
pytest
pytest --cov=src --cov-report=term-missing
```

Domain、Application、Security 均须不低于 85%；总覆盖率门禁同为 85%。测试不得仅断言 HTTP
状态，必须断言资源作用域、状态、Adapter 副作用、审计、幂等结果和错误码。
