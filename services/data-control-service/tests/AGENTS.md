# AGENTS.md — data-control-service/tests

本文件继承仓库根目录与服务目录的全部约束，并适用于 `tests/**`。

开始编写测试前必须阅读：

- `../VIBE_CODING_CONSTRAINTS.md`；
- `../VIBE_CODING.md`；
- `../../../docs/architecture/data-control-service-architecture-original.png`。

当用户当前任务只是补充约束或上传架构图时，禁止新增业务测试或用测试倒逼未获授权的业务实现。

进入实现模式后，任何垂直切片必须同时覆盖：

- Agent 路径与业务服务路径在统一入口汇合；
- Gateway 不直接调用 Adapter；
- `tenant_id + biz_domain` 在数据执行层强制生效；
- 未知 Tool、Action、Operation、Route、Adapter 和数据范围 fail closed；
- 写操作幂等和同 Key 不同 Payload 冲突；
- 拒绝请求零业务副作用、产生 DENY Audit 并可关联 Trace；
- Access Audit、Change Audit 和 Agent Tool Audit 的职责不混淆；
- 旧 `claria/data-access-gateway` 的请求体身份信任、硬编码路由和 MongoDB 范围没有被继承。

必须至少使用以下隔离矩阵，并允许相同 `resource_id` 同时存在：

```text
tenant_A + LEGAL
tenant_A + ROBOT_DOG
tenant_B + LEGAL
```

禁止通过 Mock 掉权限、路由、Adapter Guard 或执行层 Scope 后宣称安全测试通过。
