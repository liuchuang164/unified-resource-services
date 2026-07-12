# AGENTS.md — Unified Resource Services

本文件适用于整个 Monorepo。子目录中的 `AGENTS.md` 可以增加更严格的约束，但不得放宽本文件要求。

## 1. 项目定位

本仓库包含三个完整、独立运行的微服务，不是三个 Agent 插件：

- `file-media-service`
- `data-control-service`
- `external-integration-service`

Agent Tool API 只是服务的一种调用适配层，不能成为服务的内部架构中心。

### 1.1 Data Control Service 的 Codex 必读材料

任何修改 `services/data-control-service/**` 的 Codex、AI Coding Agent 或人工开发者，开始工作前必须完整阅读：

1. 本文件；
2. `services/data-control-service/AGENTS.md`；
3. `services/data-control-service/VIBE_CODING_CONSTRAINTS.md`；
4. `services/data-control-service/VIBE_CODING.md`；
5. `docs/architecture/data-control-service-architecture-original.png`；
6. `docs/architecture/data-control-service-architecture.md`。

用户提供的原始架构图是该服务的架构事实源。文字文档只能解释和细化，不能改变图中调用方向、层级职责、统一入口、审计链路和 Adapter 范围。

历史 `claria/main/data-access-gateway` 仅是只读参考，不是目标架构。禁止因复用旧代码而让旧仓库的结构、接口、数据库类型或信任模型覆盖原始架构图。

### 1.2 任务模式护栏

必须先识别当前任务模式：

- **约束维护模式**：当用户要求补充约束、整理 Vibe Coding 规则、上传架构图或完善 Codex 任务书时，只能修改文档、`AGENTS.md`、架构原图及其校验说明；禁止修改 `src/`、业务测试、迁移、运行依赖、Dockerfile、部署清单和业务配置。
- **实现模式**：只有用户明确要求实现某个 Phase、垂直切片或功能时，才可以修改业务代码，并且只能实现被点名的范围。

不得把“为 Codex 准备约束”误解成“直接替 Codex 开发业务功能”。

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
