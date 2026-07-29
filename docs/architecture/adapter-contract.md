# Data Adapter 契约

## 1. 目标

Adapter 层将统一数据操作转换为具体数据资源调用。Adapter 只负责协议适配和底层执行，不负责权限决策、租户推断、领域业务判断和开放式查询生成。

## 2. 统一 SPI

概念接口：

```ts
interface DataAdapter {
  readonly name: string;
  readonly target: DataTarget;
  capabilities(): AdapterCapabilities;
  health(): Promise<AdapterHealth>;
  execute(command: AdapterCommand, context: AdapterExecutionContext): Promise<AdapterResult>;
  beginTransaction?(options: TransactionOptions): Promise<AdapterTransaction>;
}
```

### 2.1 AdapterCommand

必须包含：

- `operation`
- `logical_resource`
- `validated_payload`
- `scope`：可信 `tenant_id + biz_domain`
- `timeout_ms`
- `route_id`
- 可选 `expected_version`
- 可选事务句柄

不得包含：客户端直接提供且未经验证的 SQL、命令、脚本或凭据。

### 2.2 AdapterResult

必须包含：

- `status`
- `data` 或逐项结果
- `affected_count`
- 可选 `resource_version`
- 可选分页 Cursor
- `adapter_metadata`（受控、可审计、不可泄密）

Adapter 不返回驱动堆栈给 API 层；原始异常先映射为内部异常类别。

## 3. 通用行为契约

- 所有调用必须执行作用域约束，不能只相信上层已经校验。
- 超时和取消信号必须向下游传播。
- 查询必须参数化或使用受控构造器。
- 支持能力由 `capabilities()` 显式声明。
- 不支持的操作必须快速失败。
- 连接池、客户端实例和重试策略集中配置。
- Adapter 内不得无限重试。
- 日志不得记录 Secret、完整 Token、原始敏感 Payload。
- 健康检查不得执行破坏性写操作。

## 4. PostgreSQL Adapter

职责：结构化事务数据读写。

约束：

- 仅使用参数化 SQL 或预注册 Repository/Query Template。
- 每个查询和写入强制携带 `tenant_id`、`biz_domain` 条件。
- 推荐启用 RLS 作为第二道隔离。
- 支持本地事务、乐观锁和受控悲观锁。
- 禁止将物理表名直接暴露给调用方。
- Schema migration 不由运行时请求触发。

首阶段能力：`GET/LIST/CREATE/UPDATE/UPSERT/DELETE/BATCH`。

## 5. MinIO Adapter

职责：对象、文档、图片、音视频及其元数据访问。

约束：

- Object Key 固定前缀：`tenant/{tenant_id}/{biz_domain}/...`。
- Bucket 和 Key 由逻辑资源映射器生成，不接受任意绝对路径。
- 上传必须校验大小、MIME、扩展名和可选哈希。
- 下载优先返回短时效受控 URL 或流，不返回存储凭据。
- 删除默认软删除/墓碑；物理删除需显式高风险策略。
- Multipart Upload 必须支持会话过期和清理。

首阶段能力：对象 `GET/CREATE/DELETE/LIST`，以及受控上传会话。

## 6. Redis Adapter

职责：缓存、运行态、锁和幂等记录。

约束：

- Key 固定命名空间：`{prefix}:{tenant_id}:{biz_domain}:{resource}:{logical_key}`，默认 prefix 为 `dcs`。
- Resource Mapping 必须服务端持久化 Redis 物理配置，包括 `resource_name`、TTL 上限、默认 TTL、value 类型和 value size 上限。
- 只允许预注册操作，不开放任意 Redis Command。
- 所有缓存项必须有 TTL 策略；永久项必须显式声明，本阶段默认不允许永久 key。
- 分布式锁必须有 owner token、租约和安全释放逻辑；锁使用 `SET key token PX ttl NX`，解锁只允许固定 compare-and-delete Lua。
- 幂等记录状态转换必须原子化。
- 禁止跨租户 Scan；本阶段运行时禁用 `SCAN/KEYS/FLUSH/CONFIG/MODULE/ACL/AUTH/SELECT/EVAL` 等客户端透传。
- 序列化只允许 UTF-8 string、JSON 和 integer，不使用 pickle。
- Redis driver 使用 `redis.asyncio` 与连接池；shutdown 必须关闭 client/pool，readiness 必须 ping 真实 Redis。

首阶段能力：`GET/EXISTS/UPSERT/DELETE/LOCK/UNLOCK`。

## 7. Neo4j Adapter

职责：实体关系、本体图谱和路径查询。

约束：

- 使用参数化 Cypher 和预注册查询模板。
- 节点与关系必须带 `tenant_id`、`biz_domain`。
- 所有 MATCH/MERGE/DELETE 均强制加入作用域条件。
- 路径深度、返回数量和执行时间必须有限制。
- 禁止开放任意 Cypher。
- 批量写入需有明确事务边界和失败语义。

首阶段能力：受控 `GET/SEARCH/CREATE/UPDATE/DELETE/BATCH`。

## 8. Milvus Adapter

职责：向量写入、相似度检索和索引资源访问。

约束：

- 租户隔离采用分区、分区键或强制标量过滤，策略必须固定一种并测试。
- Collection、向量维度、Metric 和 Index 由资源注册表定义。
- 查询必须限制 topK、过滤范围和超时。
- 不接受调用方自定义任意表达式。
- Embedding 生成不属于本 Adapter；Adapter 只接收已校验向量及元数据。
- 删除必须按租户作用域和资源标识执行。

首阶段能力：`CREATE/UPSERT/SEARCH/DELETE`。

## 9. TimescaleDB Adapter

职责：时序指标、设备数据和审计类时间序列访问。

约束：

- 基于 PostgreSQL 参数化访问，时间窗口必须有上限。
- 每条数据必须包含租户、业务域和时间戳。
- Retention、压缩和连续聚合由平台配置管理。
- 查询必须限制时间范围、粒度和点数。
- 禁止无时间边界的大范围扫描。

首阶段能力：`CREATE/BATCH/LIST/SEARCH`。

## 10. 能力矩阵

| Adapter | 事务 | 游标分页 | 乐观锁 | 批量 | 主要数据类型 |
|---|---:|---:|---:|---:|---|
| PostgreSQL | 是，本地 | 是 | 是 | 是 | 结构化数据 |
| MinIO | 否 | 是 | 可用 ETag | 是 | 对象数据 |
| Redis | 原子命令/Lua | 有限 | CAS 语义 | 是 | 缓存与状态 |
| Neo4j | 是，本地 | 是 | 受限 | 是 | 图数据 |
| Milvus | 否 | 搜索分页受限 | 否 | 是 | 向量数据 |
| TimescaleDB | 是，本地 | 是 | 是 | 是 | 时序数据 |

## 11. Adapter 测试门禁

每个 Adapter 合入前至少通过：

- SPI 契约测试；
- 租户隔离正反向测试；
- 超时与取消测试；
- 错误归一化测试；
- 幂等/重复写相关测试；
- 真实依赖集成测试；
- 故障注入：连接失败、超时、部分失败、容量耗尽；
- 日志与审计 Secret 扫描。
