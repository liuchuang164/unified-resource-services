# 平台架构边界

## 1. 仓库边界

`unified-resource-services` 是一个 Monorepo，但运行时由三个独立微服务组成。公共包只解决稳定协议和无状态基础能力，不能拥有任何一个服务的业务核心。

## 2. 服务边界

### File Media Service

拥有文件、对象、音视频流和转码任务的生命周期。它可以使用对象存储，但对象业务权限、元数据和流会话归该服务所有。

### Data Control Service

拥有统一数据访问、租户业务路由、数据资源授权、数据操作审计和各类数据库 Adapter。Data Access Gateway 只是它面向 Agent 的上层 Tool 协议入口。

### External Integration Service

拥有第三方 Provider 接入、凭据引用、调用策略、限流、重试、熔断、成本和调用审计。External Access Gateway 只是它面向 Agent 的上层 Tool 协议入口。

## 3. 共享边界

`packages/` 中不得出现下列对象：

- 业务数据库连接；
- 服务 Repository；
- Provider SDK 实例；
- 服务路由表；
- 具体授权决策；
- 具体幂等 TTL；
- 具体审计存储；
- 跨服务事务。

## 4. 调用原则

业务服务可以直接调用三个服务各自的统一入口。Agent 必须通过各服务的 Tool Adapter/Gateway，再进入同一统一入口。两种路径必须在统一入口处汇合，避免产生两套权限、路由和审计实现。
