# ADR-0004: Redis Adapter 与锁语义

- 状态：Accepted
- 日期：2026-07-29
- 分支：`feature/database-distribution-control-service`
- 基线：Phase 2.2 commit `2c217d2ca9ee5824c5c1892ee55c7ab85257c7ef`

## 背景

Phase 3 引入真实 Redis 控制面访问能力，但服务边界不变化：业务调用方仍只能通过 `POST /data/dispatch` 提交统一 `DataRequest`。Redis 不能暴露为直接命令代理，也不能允许调用方传入连接信息、物理 key、Lua 或管理命令。

## 决策

1. Redis Adapter 使用 `redis.asyncio`、Redis 7.x 兼容协议和集中连接池。
2. Resource Mapping 持久化 Redis 物理配置，包含 `key_prefix`、`resource_name`、`default_ttl_seconds`、`max_ttl_seconds`、`lock_default_ttl_seconds`、`lock_max_ttl_seconds`、`value_type` 和 `max_value_bytes`。
3. Redis key 只能由服务端生成，格式为 `{prefix}:{tenant_id}:{biz_domain}:{resource}:{logical_key}`。
4. 调用方只能提交逻辑字段：`logical_key`、`value`、`ttl_seconds`、`only_if_absent`、`only_if_present`、`lock_token`。
5. 支持操作冻结为 `GET / EXISTS / UPSERT / DELETE / LOCK / UNLOCK`。
6. `UPSERT` 使用 Redis `SET`，支持 TTL、`NX` 和 `XX` 条件写；条件未满足映射为 `DATA_CONFLICT`。
7. `LOCK` 使用 `SET lock_key token PX ttl NX`，锁未获得映射为 `LOCK_NOT_ACQUIRED`。
8. `UNLOCK` 只使用固定 compare-and-delete Lua，只有 token 匹配才删除锁；不匹配映射为 `LOCK_TOKEN_MISMATCH`。
9. 默认不允许永久 cache key；永久 key 只能在 Resource Mapping 中显式放开并经过评审。
10. 禁止 raw Redis command、Lua、`KEYS`、`SCAN`、`FLUSH*`、`CONFIG`、`MODULE`、`ACL`、`AUTH`、`SELECT` 等管理或逃逸面，校验必须递归检查 payload。
11. Adapter 错误统一映射为稳定错误码，不向 API 响应泄露 Redis URL、host、password、driver stack 或物理 key。
12. Readiness 必须 ping 真实 Redis，并验证 Redis Resource Mapping 可从 control database 读取。

## 后果

正面影响：Redis 能作为真实依赖进入 `/data/dispatch`，同时保持统一鉴权、策略、幂等、审计和错误语义。锁释放具备 owner token 保护，避免误删他人锁。

成本：调用方不能使用任意 Redis 数据结构和命令；新增 Redis 资源需要先登记 Resource Mapping 和 Policy Binding；永久 key 和管理扫描需要单独 ADR。

## 非目标

- 不实现 Redis Cluster/Sentinel 拓扑自动发现。
- 不把 Redis 作为跨 Adapter 全局事务协调器。
- 不开放通用 Lua、Pipeline、Pub/Sub、Stream、Sorted Set 或 Hash 命令。
- 不实现真实 MinIO、Neo4j、Milvus、TimescaleDB Adapter。
