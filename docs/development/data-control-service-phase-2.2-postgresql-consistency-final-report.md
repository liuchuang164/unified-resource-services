# 数据库分发管控服务 Phase 2.2 PostgreSQL 一致性收口报告

## 1. 阶段目标

Phase 2.2 在 Phase 2.1 的真实 PostgreSQL 可靠性基线上，补齐 Audit Outbox、Idempotency Recovery、业务写成功但控制面完成失败时的防重复机制、专用 stop/start 自动化、精简性能基线和 CI 门禁。

## 2. Migration

Control migration head 推进到 `0005`：

- 新增 `control_plane.audit_outbox`
- 扩展 `control_plane.idempotency_records` recovery 字段

Target migration head 保持 `target_0001`。

## 3. Audit Outbox

请求路径写入 `audit_outbox`，正式审计表由 `AuditOutboxProcessor.run_once()` 物化。Outbox 使用唯一 `event_id` 去重，并通过 worker lock、`FOR UPDATE SKIP LOCKED`、attempts、`next_retry_at` 和 FAILED 状态支持补偿处理。

该机制提供最终一致审计恢复，不声明业务库和控制库的跨数据库强一致。

## 4. Idempotency Recovery

幂等状态新增 `RECOVERY_REQUIRED`。当 target 写入成功但 `mark_succeeded` 失败时，服务记录业务结果引用和恢复元数据，并返回 `IDEMPOTENCY_RECOVERY_REQUIRED`。

相同 `idempotency_key` 后续请求会直接命中 recovery-required 状态，不会重新执行目标 Adapter。

管理员脚本：

```bash
python scripts/recover_idempotency.py --limit 50 --dry-run
python scripts/recover_idempotency.py --limit 50
```

## 5. 事务错误语义

PostgreSQL SQLSTATE 映射已细分：

- `40P01` -> `TRANSACTION_DEADLOCK`
- `40001` -> `TRANSACTION_SERIALIZATION_FAILURE`

两者均为 retryable，但写操作重试必须复用同一 `idempotency_key`。

## 6. Stop/Start 自动化

新增 `docker-compose.reliability.yml`，使用专用 control/target PostgreSQL 容器和独立端口。测试 `tests/reliability/postgresql/test_stop_start.py` 只有在 `POSTGRESQL_RELIABILITY_COMPOSE=1` 时才会控制容器，禁止用于共享数据库。

## 7. 性能基线

`scripts/benchmark_postgresql.py` 输出 JSON，覆盖 6 个场景：

- `1000_get_serial`
- `1000_upsert_serial`
- `100_concurrent_different_keys`
- `20_concurrent_same_key`
- `100_atomic_batch`
- `500_idempotency_replay`

输出包含 `duplicate_write_count` 和 `pool_timeout_count`。

## 8. CI 门禁

Workflow 已加入：

- `pytest -m consistency -q`
- `pytest -m migration -q`
- `pytest -m performance -q`
- coverage 追加 consistency
- dedicated PostgreSQL stop/start job

## 9. 本地验证

本地 Python 3.12.13：

```text
ruff check .
ruff format --check .
mypy src
pytest -q
pytest -m postgresql -q
pytest -m reliability -q
pytest -m consistency -q
pytest -m migration -q
pytest -m performance -q
```

结果：

```text
ruff / format / mypy passed
pytest -q: 61 passed, 13 skipped
pytest -m postgresql -q: 11 skipped
pytest -m reliability -q: 5 skipped
pytest -m consistency -q: 1 passed, 1 skipped
pytest -m migration -q: 2 skipped
pytest -m performance -q: 1 skipped
```

本地没有 Docker 和 PostgreSQL URL，因此真实 PostgreSQL marker 在本地按预期 skip。

## 10. Gateway 验证

已在 gateway server 上传当前工作树测试包，并启动本任务专用 control/target PostgreSQL 容器。未停止共享数据库。

阻塞项：

- gateway Docker Hub 拉取 `postgres:16` 超时，改用 gateway 已缓存的 `postgres:16-alpine` 在临时测试副本中启动专用容器。
- gateway 系统 Python 为 3.10，且 apt 源无 Python 3.12；项目代码依赖 Python 3.12 语义，3.10 运行在 `datetime.UTC` 处失败。

处理结果：

- 已清理 gateway 专用 PostgreSQL compose 容器和网络。
- gateway 未形成有效 Python 3.12 真实 PostgreSQL pytest 结果。
- 最终真实 PostgreSQL 验收以 GitHub Actions Python 3.12 + PostgreSQL service/compose 结果为准。

## 11. GitHub Actions

待推送后回填最终 run URL 和结论。

## 12. 风险声明

- 不提供跨 database 原子性。
- 不实现两阶段提交、消息队列、CDC 或跨 Adapter 分布式事务。
- 不通过生产 API 暴露 fault injection。
- `config.txt`、`.env`、数据库 dump 和真实凭据不得提交。
