# Codex 启动提示词 — 数据库分发管控服务

把下面内容作为后续 Codex 开发任务的起始提示。请把 `{PHASE}` 和 `{目标}` 替换成当次明确范围。

```text
你负责 unified-resource-services 仓库中的 services/data-control-service。

先完整阅读并遵守：
1. 根 AGENTS.md；
2. services/data-control-service/AGENTS.md；
3. services/data-control-service/VIBE_CODING_CONSTRAINTS.md；
4. services/data-control-service/VIBE_CODING.md；
5. docs/architecture/data-control-service-architecture-original.png；
6. docs/architecture/data-control-service-architecture.md；
7. 当前准备修改目录内更深层的 AGENTS.md。

原始 PNG 是架构事实源。claria/main/data-access-gateway 只可作为只读局部参考；发生差异时必须以原始 PNG 和当前仓库约束为准，禁止把旧 Gateway 整体搬过来。

本次只实现：{PHASE} — {目标}。
不要提前实现其他 Phase，不要顺手加入 MongoDB，不要建立万能共享框架，不要改变原图的调用关系。

写代码前先输出：
A. 原图节点到计划模块/文件的映射；
B. 当前实现与历史 data-access-gateway 的关键差异；
C. In Scope / Out of Scope；
D. 失败路径、零副作用与审计断言；
E. 文件级计划和质量门禁。

必须保持：
Agent -> Data Access Gateway -> 统一 /data/dispatch -> Adapter；
业务本体服务 ---------------------> 统一 /data/dispatch -> Adapter。

Gateway 只做 Tool 协议、Schema、Agent 上下文、Tool/Operation 映射、请求/响应转换和 Agent Tool Audit；最终权限、数据权限、业务/数据策略、幂等、路由、事务、Access Audit、Change Audit 只在统一入口实现一套；Adapter 只做受控执行。

可信 tenant/user/roles 必须来自认证上下文或已验签 Token，不能信任请求体自由填写。所有执行在存储层强制 tenant_id + biz_domain。未知 Tool、Action、Operation、Route、Adapter 或 Scope 必须 fail closed。

完成后实际运行 lint、typecheck、相关 unit/contract/integration/security tests，修复全部失败，更新契约和文档，并报告真实命令与结果。不得伪造验证。
```

## 仅调整约束时使用的提示

```text
本次是约束维护模式，只允许修改 AGENTS、Vibe/Codex 文档、架构说明和原始架构图资产。禁止修改 src、业务测试、迁移、OpenAPI 实现、依赖、Dockerfile、部署清单和运行配置。不要开发业务功能。
```
