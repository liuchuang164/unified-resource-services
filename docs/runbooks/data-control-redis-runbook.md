# 数据库分发管控服务 Redis 运行手册

## 前置约束

- 只通过 `POST /data/dispatch` 访问 Redis，不提供直连 Redis API。
- 不提交 `.env`、`config.txt`、Redis URL、密码、dump 或真实 token。
- GitHub CI 使用仓库内 Redis service/compose，不依赖 gateway server。

## 本地开发

```bash
cd services/data-control-service
docker compose -f docker-compose.redis.yml up -d
CONTROL_DATABASE_MIGRATION_URL=postgresql+psycopg://data_control:change_me@localhost:56432/data_control alembic -c alembic-control.ini upgrade head
TARGET_DATABASE_MIGRATION_URL=postgresql+psycopg://data_control:change_me@localhost:56433/data_target alembic -c alembic-target.ini upgrade head
CONTROL_DATABASE_URL=postgresql+asyncpg://data_control:change_me@localhost:56432/data_control REDIS_ADAPTER_ENABLED=true REDIS_URL=redis://localhost:56379/0 python scripts/bootstrap_postgresql.py
```

启动服务：

```bash
CONTROL_DATABASE_URL=postgresql+asyncpg://data_control:change_me@localhost:56432/data_control \
POSTGRESQL_ADAPTER_DATABASE_URL=postgresql+asyncpg://data_control:change_me@localhost:56433/data_target \
REDIS_ADAPTER_ENABLED=true \
REDIS_ADAPTER_REQUIRED=true \
REDIS_URL=redis://localhost:56379/0 \
uvicorn data_control_service.main:app --reload
```

## 健康检查

```bash
curl -sS http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
```

`live` 只表示进程可响应。`ready` 会检查 `redis_connection`、`redis_resource_mapping` 和 `redis_adapter`。Redis 为 required 时失败返回 503；optional 时服务可 `DEGRADED`，但 Redis 请求仍返回稳定错误。

## Key 与 TTL

物理 key 格式：

```text
{REDIS_KEY_PREFIX}:{tenant_id}:{biz_domain}:{resource_name}:{logical_key}
```

默认 prefix 为 `dcs`。调用方只能传 `logical_key`，不能传完整物理 key、URL、host、password 或连接参数。TTL 必须大于 0 且不超过 Resource Mapping 的 `max_ttl_seconds`；本阶段默认不允许永久 cache key。

## 锁语义

- `LOCK`：`SET lock_key token PX ttl NX`。
- `UNLOCK`：固定 Lua compare-and-delete。
- token 长度 16 到 256，禁止空白字符。
- 锁未获得返回 `LOCK_NOT_ACQUIRED`。
- token 不匹配返回 `LOCK_TOKEN_MISMATCH`。
- 锁过期后旧 token 不再拥有释放权；调用方应重新获取锁并使用新 token。

## 故障处理

Redis 不可用：

```bash
redis-cli -u <redacted-url> ping
curl -i http://127.0.0.1:8000/health/ready
```

期望 `/health/live` 仍为 200，`/health/ready` 在 required 模式下为 503，Redis 请求映射为 `ADAPTER_UNAVAILABLE` 或 `ADAPTER_TIMEOUT`。

连接池耗尽：

```bash
REDIS_MAX_CONNECTIONS=20
REDIS_SOCKET_TIMEOUT_SECONDS=2
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS=2
```

耗尽映射为 `ADAPTER_CAPACITY_EXCEEDED`，释放连接后 readiness 和请求应自动恢复。

认证失败：

检查 Redis ACL、密码和 `REDIS_USERNAME`/`REDIS_PASSWORD`。响应只能返回 `ADAPTER_AUTHENTICATION_FAILED`，不得泄露凭据。

## 故障注入

只允许在专用 compose 环境执行：

```bash
docker compose -f docker-compose.redis.yml up -d
REDIS_RELIABILITY_COMPOSE=1 pytest tests/reliability/redis/test_stop_start.py -q
docker compose -f docker-compose.redis.yml down -v
```

禁止在共享 Redis、gateway server 或生产环境执行 stop/start 故障测试。

## 测试与基准

```bash
pytest -m redis -q
pytest tests/reliability/redis/test_pool_timeout_recovery.py -q
pytest tests/performance/test_benchmark_redis.py -q
python scripts/benchmark_redis.py --url http://127.0.0.1:8000 --scenario set_get --iterations 100
```

基准脚本只输出统计 JSON，不输出 Redis URL 或密码。

## 审计与排障

Redis 写操作仍走统一幂等与审计路径。排障时保留 `request_id`、`trace_id`、`operation`、`resource`、错误码和时间窗口，不记录 value、lock token、物理 key 或连接信息。

重点指标：

- `redis_operation_total`
- `redis_operation_latency_ms`
- `redis_timeout_total`
- `redis_connection_failure_total`
- `redis_pool_exhaustion_total`
- `redis_lock_acquired_total`
- `redis_lock_conflict_total`
- `redis_unlock_success_total`
- `redis_unlock_token_mismatch_total`
