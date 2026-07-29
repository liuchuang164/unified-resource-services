# Phase 3 Redis Adapter 开发报告

## 基线

- 仓库：`https://github.com/liuchuang164/unified-resource-services`
- 分支：`feature/database-distribution-control-service`
- Phase 2.2 基线 commit：`2c217d2ca9ee5824c5c1892ee55c7ab85257c7ef`
- 本阶段目标：真实 Redis 控制面 Adapter、TTL、锁、readiness、metrics、测试与 CI/CD 门禁。

## 范围

已实现：

- `redis.asyncio` 真实 Adapter 与连接池生命周期。
- `/data/dispatch` Redis 路径：`GET / EXISTS / UPSERT / DELETE / LOCK / UNLOCK`。
- Resource Mapping 持久化 Redis `physical_config`。
- 服务端 key 生成：`{prefix}:{tenant_id}:{biz_domain}:{resource}:{logical_key}`。
- JSON/string/integer 安全序列化和 value size 限制。
- TTL 默认值、上限和禁止默认永久 key。
- `SET NX PX` 获取锁，固定 compare-and-delete Lua 释放锁。
- Redis readiness、required/optional 模式和 manager graceful shutdown。
- Redis 错误映射、指标、连接池耗尽与 timeout 恢复测试。
- Docker Compose Redis/PostgreSQL 专用环境和 GitHub Actions Redis gates。

明确未做：

- 未实现真实 MinIO、Neo4j、Milvus、TimescaleDB Adapter。
- 未开放 raw Redis command、Lua、Scan、Keys、Flush 或管理命令。
- 未实现 Redis Cluster/Sentinel 自动拓扑管理。
- 未提供直连 Redis HTTP API。

## 关键文件

- `services/data-control-service/src/data_control_service/adapters/redis.py`
- `services/data-control-service/src/data_control_service/infrastructure/redis/`
- `services/data-control-service/migrations/control/versions/0006_add_resource_mapping_physical_config.py`
- `services/data-control-service/scripts/bootstrap_postgresql.py`
- `services/data-control-service/docker-compose.redis.yml`
- `.github/workflows/data-control-service.yml`
- `docs/architecture/adr/ADR-0004-redis-adapter-and-lock-semantics.md`
- `docs/runbooks/data-control-redis-runbook.md`

## 本地验证

已执行：

```text
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy src
pytest -q
pytest -m redis -q
pytest -m migration -q
pytest -m performance -q
pytest -m consistency -q
pytest -m reliability -q
```

当前本机无已确认的真实 Redis/Docker/PostgreSQL 端到端结果；未配置依赖的真实测试按 marker 自动 skip。真实依赖验证由 GitHub Actions Redis service 与 compose job 承担。

## CI 门禁

Workflow 增加：

- quality job Redis service：`redis:7-alpine`。
- `pytest -m redis -q`。
- Redis 覆盖率追加。
- dedicated `redis-stop-start` job，使用 `docker-compose.redis.yml`。

CI 结果将在 push 后以 commit checks 为准更新最终交付说明。

## 安全结论

- 递归拒绝 raw command、Lua、keys/scan/flush/config/module/acl/auth/select 等字段。
- 请求体禁止 Redis URL、host、password、connection string。
- API 响应不返回 Redis URL、密码、driver stack 或完整物理 key。
- `config.txt` 保持本地未跟踪，不纳入 commit。

## 运行手册

详见 `docs/runbooks/data-control-redis-runbook.md`。
