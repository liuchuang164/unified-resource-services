# 数据库分发管控服务架构文档

本目录冻结数据库分发管控服务（Database Distribution Control Service）的开发基线。实现、测试、评审和后续变更必须以本目录为准。

## 文档清单

1. `database-distribution-control-service-architecture.md`：服务定位、边界、模块划分、核心流程和非功能约束。
2. `data-request-response-contract.md`：统一请求、统一响应、上下文、幂等和版本兼容规则。
3. `error-code-catalog.md`：错误码命名、HTTP 映射、重试语义和错误目录。
4. `adapter-contract.md`：统一 Adapter SPI 以及 PostgreSQL、MinIO、Redis、Neo4j、Milvus、TimescaleDB 的行为契约。
5. `architecture-decision-record.md`：本轮冻结项、明确不做项和变更流程。

## 约束优先级

发生冲突时按以下顺序处理：

1. 安全、租户隔离和数据完整性要求；
2. 本目录冻结的契约；
3. `AGENTS.md`；
4. `docs/governance/vibe-coding-constraints.md`；
5. 具体实现细节。

未经 ADR 审批，不得在代码中隐式改变请求字段、错误语义、路由规则、租户作用域和 Adapter 行为。
