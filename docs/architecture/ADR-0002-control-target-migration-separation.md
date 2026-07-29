# ADR-0002：Control / Target Migration 拆分

- 状态：Accepted
- 日期：2026-07-29
- 分支：`feature/database-distribution-control-service`

## 背景

Phase 2 将控制面表与 PostgreSQL target 示例表放在同一 Alembic chain 中。该结构便于首轮验证，但会让 control database 与 target database 在生产拆分时共享 revision history，导致独立升级、回滚和 readiness 判断不清晰。

## 决策

1. 新增 `alembic-control.ini`，只管理 `control_plane` schema。
2. 新增 `alembic-target.ini`，只管理 `data_target` schema。
3. Phase 2.1 拆分时 control revision head 为 `0004`，包含 idempotency、access audit、change audit、resource mappings、policy bindings；后续 head 由新增 migration 和运行手册声明。
4. Target revision head 为 `target_0001`，只包含 `platform_records` 示例业务表。
5. 旧 `alembic.ini` 标记为 deprecated，仅指向 `migrations/legacy_phase2_combined` 作为 Phase 2 过渡参考。
6. Readiness 分别检查 `control_plane.alembic_version` 与 `data_target.alembic_version`。

## 既有环境影响

已经执行旧 `0001` 到 `0005` combined chain 的环境，不要求删库。迁移方式：

```bash
CONTROL_DATABASE_MIGRATION_URL=... TARGET_DATABASE_MIGRATION_URL=... \
python scripts/stamp_split_migrations.py
```

该脚本只执行 `stamp`，不会 drop 表或重放 DDL。执行前应确认：

- control database 已包含 `control_plane` 下控制面表；
- target database 已包含 `data_target.platform_records`；
- 若 Phase 2 使用同一个 database 承载 control/target，两个 URL 可以指向同一 database。

## 回滚策略

- Control 回滚：`alembic -c alembic-control.ini downgrade -1`。
- Target 回滚：`alembic -c alembic-target.ini downgrade -1`。
- 回滚前必须确认业务和审计保留要求；不得用删库代替迁移回滚。

## 风险

- 旧 combined chain 仍保留在 legacy 目录，后续不得用于新环境。
- Control 与 target 分库后，业务写入和审计/幂等 completion 不能跨库强一致；本 ADR 不引入两阶段提交。
- 若已有环境中 control/target 表实际分布与 URL 不一致，必须先人工核对再 stamp。
