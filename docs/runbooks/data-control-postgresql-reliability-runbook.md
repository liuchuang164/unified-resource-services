# 数据库分发管控服务 PostgreSQL 可靠性运行手册

## 健康检查

```bash
curl -sS http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
```

`READY` 和 `DEGRADED` 返回 200；`NOT_READY` 返回 503。响应不得包含数据库地址、用户名、密码或 SQL。

## Migration

```bash
alembic -c alembic-control.ini current
alembic -c alembic-target.ini current
alembic -c alembic-control.ini upgrade head
alembic -c alembic-target.ini upgrade head
```

期望 head：

- control：`0005`
- target：`target_0001`

旧 Phase 2 环境使用 `scripts/stamp_split_migrations.py` 过渡，禁止直接删库。

## Control Database 故障

现象：`control_database`、control repository 或 `control_migration` 组件 error，ready=false。

处理：

```bash
pg_isready -d <control_db>
alembic -c alembic-control.ini current
```

恢复数据库后无需重启服务；`pool_pre_ping` 会丢弃失效连接。

## Target Database 故障

现象：`postgresql_adapter_database`、`target_migration` 或 `postgresql` adapter error，ready=false。

处理：

```bash
pg_isready -d <target_db>
alembic -c alembic-target.ini current
```

## Statement Timeout

服务通过连接参数设置 `statement_timeout`。超时应映射为 `ADAPTER_TIMEOUT`，事务应回滚。不得把 SQL 或参数返回给客户端。

## Pool Exhaustion

检查 pool 配置：

```bash
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT_SECONDS=30
```

耗尽时请求应失败为 `ADAPTER_UNAVAILABLE` 或 timeout 类错误，释放连接后自动恢复。

## Deadlock / Serialization Failure

Deadlock 应映射为 `TRANSACTION_DEADLOCK`，serialization failure 应映射为 `TRANSACTION_SERIALIZATION_FAILURE`。两者 `retryable=true`，调用方只有在复用同一 `idempotency_key` 时才能重试写操作。服务不做无限自动重试。

## Idempotency PROCESSING 超时

`SQLAlchemyIdempotencyRepository` 会按 `IDEMPOTENCY_PROCESSING_TIMEOUT_SECONDS` reclaim 超时 PROCESSING。

如果业务写已成功但 `mark_succeeded` 失败，记录进入 `RECOVERY_REQUIRED`。相同 key 后续请求返回 `IDEMPOTENCY_RECOVERY_REQUIRED`，不会重新执行目标 Adapter。

管理员诊断：

```bash
python scripts/recover_idempotency.py --limit 50 --dry-run
```

确认目标库事实后恢复：

```bash
python scripts/recover_idempotency.py --limit 50
```

## Audit

跨 control/target database 时，不声称审计与业务写入强一致。写操作成功后会写入 `control_plane.audit_outbox`，由显式 processor 将事件物化到正式审计表。

处理 pending outbox：

```bash
python scripts/process_audit_outbox.py --batch-size 100
```

如果 outbox health 中 failed 大于 0，先保留现场，检查 control database 可用性、migration head 和最近错误摘要。不得人工删除 outbox 事件来掩盖审计缺失。

## 服务重启和 PostgreSQL 重启

优雅关闭会 dispose control/target engine。PostgreSQL 重启后，不要求服务重启；readiness 应从 `NOT_READY` 自动恢复。

专用 stop/start 自动化只允许使用：

```bash
docker compose -f docker-compose.reliability.yml up -d
POSTGRESQL_RELIABILITY_COMPOSE=1 pytest tests/reliability/postgresql/test_stop_start.py -q
docker compose -f docker-compose.reliability.yml down -v
```

## 禁止操作

- 禁止在共享业务 PostgreSQL 上做 stop/start 故障测试。
- 禁止提交 `.env`、`config.txt`、数据库 dump 或真实凭据。
- 禁止使用旧 combined migration 创建新环境。
- 禁止将 gateway server 测试结果写成 GitHub CI 结果。
