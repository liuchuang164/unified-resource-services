# AGENTS.md — data-control-service/migrations

继承仓库根目录和服务目录全部约束。

约束维护模式下禁止新增或修改业务迁移。只有用户明确要求实现某个 Phase，且该 Phase 需要持久化结构时，才允许创建迁移。

迁移只能归本服务所有，不得修改其他微服务的数据表。路由、幂等、审计、Outbox 和服务控制面元数据必须明确所有权、索引、唯一约束、回滚或前滚策略。

任何共享表模型都必须在存储层保留并索引 `tenant_id + biz_domain`。禁止通过迁移引入无租户业务范围的生产 Repository 路径。

不得因为历史 `claria/data-access-gateway` 使用某个数据库或表结构就直接复制迁移。MongoDB 不在当前原图 Adapter 范围。
