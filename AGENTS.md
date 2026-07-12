# AGENTS.md — Unified Resource Services

本文件适用于整个 Monorepo。子目录中的 `AGENTS.md` 可以增加更严格的约束，但不得放宽本文件要求。

## 1. 项目定位

本仓库包含三个完整、独立运行的微服务，不是三个 Agent 插件：

- `file-media-service`
- `data-control-service`
- `external-integration-service`

Agent Tool API 只是服务的一种调用适配层，不能成为服务的内部架构中心。

## 2. 微服务硬边界

必须：

- 每个服务独立构建、测试、发布、部署和迁移；
- 每个服务独立提供 `/health/live` 与 `/health/ready`；
- 每个服务拥有自己的业务数据和迁移；
- 服务间通过正式网络协议或生成客户端通信；
- 一个服务失败时，另外两个服务仍可独立启动和运行。

禁止：

- 从一个服务直接导入另一个服务的 `src/`；
- 在根目录创建同时修改多个服务业务表的迁移；
- 通过共享数据库表绕过服务接口；
- 把三个服务构建成一个进程或一个统一运行时镜像；
- 为了复用而把业务核心抽成共享包，形成分布式单体。

## 3. 共享包规则

允许提前存在的最小公共包：

- `contracts`
- `common-errors`
- `capability-token-sdk`
- `observability`
- `test-kit`

新的共享包只有在以下条件全部满足时才能创建：

1. 至少两个服务已经出现真实重复；
2. 代码无服务专属语义；
3. 不直接连接业务数据库、缓存、对象存储或 Provider；
4. 不拥有业务状态；
5. 不要求所有服务同步升级；
6. 有独立测试、SemVer 兼容说明和明确所有者。

默认留在服务内部：授权、策略、幂等、审计实现、资源归属、路由、Repository、Adapter、Migration。

## 4. 租户与业务上下文

所有业务资源访问必须具有可信的：

```text
tenant_id + biz_domain
```

请求体中由调用方随意填写的租户字段不能直接作为可信身份。生产实现必须由认证上下文、内部签名上下文或 Capability Token 建立可信 `TenantBizContext`。

所有 Repository、对象路径、向量查询、缓存键、图查询、审计和 Trace 都必须显式携带租户及业务范围。禁止先做全局查询后在应用内过滤。

## 5. 安全与隐私

- 禁止提交密码、Token、私钥、API Key、Cookie 和生产连接字符串；
- 日志必须对敏感字段递归脱敏；
- Tool 权限必须细化到 `tool_name + action`；
- Gateway 和统一入口均需 fail closed；
- 未识别的租户、业务、操作、Tool、Action、Route、Adapter 必须拒绝；
- 越权测试必须验证拒绝、零副作用、Audit DENY 和 Trace 关联。

## 6. 工程质量

- TypeScript 必须开启 `strict`；
- 禁止未经说明使用 `any`；
- 外部输入必须先经过 Schema 校验；
- 关键写操作必须幂等；
- 状态与审计的一致性优先使用事务或 Outbox；
- 时间相关代码必须支持注入时钟，禁止测试真实等待；
- 不得伪造测试输出或声称未实际完成的部署验证。

## 7. 开发策略

不要先写万能公共框架。先完成一个真实服务的最小垂直切片，再依据真实重复提炼公共代码。

每个阶段应：

1. 阅读当前目录和祖先目录的 `AGENTS.md`；
2. 给出文件级计划；
3. 实际修改代码；
4. 运行 lint、typecheck、相关测试；
5. 修复失败；
6. 更新文档；
7. 提交小而清晰的 commit。
