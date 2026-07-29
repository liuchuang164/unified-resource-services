# ADR-0001：数据库分发管控服务架构基线冻结

- 状态：Accepted
- 日期：2026-07-29
- 分支：`feature/database-distribution-control-service`

## 背景

统一资源服务仓库将承载数据库分发管控服务。为避免 Vibe Coding 在编码阶段产生职责漂移、协议不一致、租户隔离缺失和各 Adapter 自行定义语义的问题，需要在实现前冻结架构基线。

## 决策

1. 业务服务和本体服务统一调用 `POST /data/dispatch`。
2. Agent/OpenClaw 通过 Data Access Gateway 的 Tool 接口进入，由 Gateway 转换为 `DataRequest`。
3. 数据库分发管控服务负责校验、可信上下文、RBAC/ABAC、策略、幂等、路由、事务编排和审计。
4. Adapter 只负责底层协议适配与执行。
5. 所有数据访问强制绑定 `tenant_id + biz_domain`。
6. 调用方仅使用逻辑资源，不得提交任意 SQL、命令、路径或连接信息。
7. 统一采用版本化 `DataRequest / DataResponse` 和冻结错误目录。
8. 跨异构存储不承诺强一致分布式事务；默认采用显式 `BEST_EFFORT` 逐项结果。
9. 写操作必须具备幂等语义和变更审计。
10. 任何协议或边界变化必须先新增 ADR，再修改代码。

## 本阶段明确不做

- 不实现案件、合同、证据等业务服务逻辑。
- 不实现开放式自然语言到任意查询的转换。
- 不建立跨 PostgreSQL、MinIO、Redis、Neo4j、Milvus、TimescaleDB 的全局事务管理器。
- 不在没有压测证据的情况下承诺吞吐和延迟数字。
- 不因追求“快速跑通”绕过真实依赖集成测试。

## 影响

正面影响：服务边界稳定，Adapter 可独立测试，错误与审计语义统一，租户隔离可系统验证。

成本：增加契约、策略、幂等和审计代码；调用方不能直接操作底层数据库；新资源需要先注册逻辑资源和路由。

## 变更流程

出现以下任一情况必须新增 ADR：

- 新增或删除入口；
- 修改顶层请求/响应语义；
- 新增跨租户能力；
- 放开 raw query；
- 改变幂等或事务语义；
- 引入新 Adapter 或改变作用域隔离方案；
- 改变审计失败时的 fail-open/fail-closed 策略。
