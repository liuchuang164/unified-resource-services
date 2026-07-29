# 文件/音视频流式服务 Vibe Coding 开发约束

> 适用目录：`services/file-media-stream-service/**`、相关 `packages/**`、文档、测试与部署文件。
>
> 当前阶段目标：**只建立架构基线、开发约束和实施边界，不实现业务代码。** 未经用户明确指令，不得提前创建服务骨架、接口实现、数据库迁移或部署资源。

## 1. 架构事实源与优先级

发生冲突时按以下顺序执行：

1. `docs/architecture/file-media-stream-service/文件-音视频访问服务.png`，用户原始架构图，必须原样保留；
2. `docs/architecture/file-media-stream-service/architecture-baseline.md`；
3. 本文件；
4. 仓库级 `AGENTS.md`、现有公共契约与 CI；
5. 编码 Agent 的默认习惯。

不得因实现简单、框架惯例或现有代码相似而偏离前三项。发现架构冲突或信息不清时，停止相关实现，列出冲突、方案、影响和建议，等待确认，不得自行拍板。

## 2. 服务定位与边界

本服务负责：

- 文件上传、下载、受控读取、Range 和临时访问地址；
- 文件与媒体元数据、版本和生命周期；
- 音频、视频、WebSocket、WebRTC 等流式会话；
- 媒体流转发、协议适配和处理服务路由；
- 对象存储、媒体服务器、OCR、ASR、转码、切片和分析能力的受控适配；
- 租户隔离、业务域隔离、能力鉴权、策略、配额、幂等、审计和可观测。

本服务不负责：

- 数据库通用读写、跨库事务和数据分发；
- 第三方 API 的通用接入、密钥托管和计费治理；
- OCR、ASR、转码或内容理解算法本身；
- 庭策、机器狗、政务等业务规则；
- Agent 任务规划、SOP、多 Agent 生命周期；
- 将原始大文件或音视频载荷写入业务数据库、日志或审计表。

外部处理能力必须通过 Adapter/Provider 接入，核心管线只负责受控调用、状态编排和结果引用。

## 3. 双入口模型不可破坏

### 3.1 File & Media Stream Access Gateway

仅面向 Agent / OpenClaw / Hermes，提供 Tool 列表、Tool Schema、Tool 执行、Agent 上下文解析、Tool 到 operation 的映射和 ToolResponse 包装。

Gateway 不得成为业务服务统一 API，也不得直接访问 MinIO、媒体服务器、数据库或处理服务。

### 3.2 File/Media Unified Entry

同时承接 Gateway 转换后的请求与业务本体服务的直接请求，统一执行：

1. 请求结构与版本校验；
2. `tenant_id`、`biz_domain`、调用主体和资源作用域解析；
3. 身份、能力令牌、权限、策略和配额校验；
4. 幂等与重放保护；
5. 文件路径、对象键、资源 ID、会话 ID 的服务端生成；
6. 操作路由、Adapter 选择和执行编排；
7. 审计、指标、Trace 和统一错误映射；
8. 统一响应封装。

业务本体服务直接调用 Unified Entry，不得伪装成 Agent Tool。Agent 只能通过 Gateway 进入，但 Unified Entry 仍必须执行最终授权，不能信任 Gateway 的“已校验”声明。

## 4. 强制分层与依赖方向

建议目录语义：

```text
services/file-media-stream-service/
  src/
    gateway/              # Tool 协议、schema、mapping、response wrapper
    entry/                # Unified Entry transport/controller
    application/          # use case / command / query / orchestration
    domain/               # resource、session、job、grant 等领域模型
    adapters/
      object-storage/
      media-server/
      processors/
      metadata-store/
      event-bus/
    security/
    audit/
    observability/
    config/
  tests/
    unit/
    contract/
    integration/
    e2e/
    security/
    failure-injection/
```

依赖只能由外向内：Gateway/transport → application → domain；Adapter 实现 application/domain 定义的 port。Domain 不得导入 HTTP、ORM、MinIO、媒体服务器、消息中间件或 Agent Tool 类型。

禁止 Controller/Gateway 直接调用 SDK；禁止 Adapter 内嵌租户授权；禁止万能 Service 同时承担鉴权、路由、存储、转码和审计；禁止全局变量保存请求、租户或会话上下文。

## 5. 核心资源模型

实现前先冻结契约，至少区分：

- `FileResource`：资源 ID、租户/业务域、归属主体、object key、摘要、MIME、大小、状态、版本、创建者；
- `MediaResource`：音视频编码、时长、分辨率和衍生物引用；
- `StreamSession`：协议、方向、权限、状态、租约和端点引用；
- `ProcessingJob`：OCR/ASR/转码/切片/分析任务与输入输出引用；
- `ResourceGrant`：主体对资源和操作的短期授权；
- `AuditEvent`：元数据、摘要、结果和引用，不包含原始载荷。

所有持久化资源必须显式包含或不可变推导 `tenant_id + biz_domain`。所有查询必须先带作用域条件再带资源 ID，禁止先按全局 ID 查询后补做租户判断。

## 6. 对象键和路径安全

- 客户端不得提交最终 object key、物理 bucket、磁盘路径或媒体服务器内部路径；
- object key 必须由服务端根据租户、业务域、资源类型、时间/散列/ID 生成；
- 原始文件名只作元数据，必须规范化，不参与物理路径拼接；
- 防御路径穿越、Unicode 混淆、双扩展名、MIME 欺骗和超长文件名；
- 下载和读取基于 resource ID 或受控 token，不接受任意 object key；
- 预签名 URL 必须短期、最小权限、绑定操作，并关联审计。

## 7. 流式会话约束

- 创建会话属于写操作，必须鉴权、幂等、限额和审计；
- 状态至少覆盖 `CREATING`、`READY`、`ACTIVE`、`DRAINING`、`CLOSED`、`FAILED`、`EXPIRED`；
- 会话必须有租约、心跳/活性判定、超时回收，不得永久驻留；
- 会话凭据短期化、不可写日志、不可长期持久化；
- 控制面和媒体数据面分离，普通 JSON API 不承载媒体帧；
- 服务重启后通过持久化状态与媒体服务器状态 reconciliation，不依赖进程内 Map；
- 关闭、超时、失败和重复关闭必须幂等。

## 8. Gateway Tool 插件化

新增 Tool 只允许增加局部插件：Tool 定义、输入输出 Schema、Tool→operation mapping、对应 use case/port 和合同测试。不得为新增 Tool 修改核心执行 pipeline。

首批候选 Tool：

- `file_media.list_tools`
- `file_media.get_tool_schema`
- `file.create_upload_url`
- `file.create_download_url`
- `file.register_metadata`
- `file.read_content`
- `media.create_stream_session`
- `media.forward_stream`
- `media.close_stream_session`
- `media.submit_processing_job`
- `media.get_processing_result`

命名仅为规划基线，正式实现前必须在契约阶段冻结版本和名称。

## 9. API 与契约优先

任何实现 PR 必须先提供或同步更新：OpenAPI/JSON Schema/ToolSpec、操作与权限矩阵、状态机、错误码、幂等语义、审计字段、超时/重试/大小限制和兼容性说明。

公共响应至少包含 `request_id`、`trace_id`、`success`、`data` 或标准化 `error`。错误必须机器可识别；不得向调用方泄露堆栈、存储路径、凭据或 SDK 内部异常。

## 10. 多租户、安全和能力令牌

每次调用必须验证：

- token 签名、过期、issuer/audience；
- nonce/jti、撤销和 replay；
- `tenant_id + biz_domain`；
- caller 类型与主体 ID；
- operation/action；
- resource scope；
- 文件大小、MIME、协议、带宽、并发、时长等配额；
- 策略版本。

跨租户访问默认拒绝。平台运维能力必须使用独立主体、独立 action、显式审计和最小作用域，不得通过特殊 tenant ID 或隐藏 header 绕过。

## 11. 大载荷与性能

- 大文件和媒体不得放入 JSON、消息队列正文、审计日志或数据库大字段；
- 服务间传递 resource ID、受控引用、摘要和元数据；
- 上传/下载使用预签名 URL、分片上传、Range、流式 backpressure；
- 显式配置单文件上限、请求体上限、租户并发、会话上限、带宽、任务并发和队列深度；
- 流式路径禁止整段缓冲到内存，必须有界缓冲和背压；
- 外部调用设置连接、首包、空闲和总超时。

## 12. 幂等、一致性和恢复

- 上传初始化、元数据登记、会话创建、任务提交等写操作必须接受幂等键；
- 幂等作用域至少包含 `tenant_id + biz_domain + caller + operation + idempotency_key`；
- 对象存储成功但元数据失败、会话创建成功但持久化失败等部分失败必须补偿或 reconciliation；
- 禁止捕获异常后返回成功；
- 只重试明确可重试错误，采用退避、抖动和上限；
- 非幂等外部调用不得盲目重试；
- 后台任务按可能重复投递设计，消费端必须幂等。

## 13. 审计、日志与隐私

审计可以记录主体、租户、业务域、operation、resource/session/job ID、摘要、MIME/大小、策略结果、状态、耗时、错误类别、Adapter 和 Trace。

绝对禁止记录：原始文件、音频帧、视频帧、完整 OCR/ASR 文本、预签名 URL、Authorization、Cookie、API Key、session secret、未经脱敏文件名和 SDK 请求签名。

日志必须结构化，并可按 `trace_id/request_id/tenant_id/biz_domain/resource_id/session_id` 关联。敏感字段必须在日志入口集中脱敏。

## 14. 测试门禁

每个功能增量至少覆盖：

- 单元测试：领域规则、路径生成、状态机、错误映射；
- Contract：ToolSpec、OpenAPI、统一入口请求响应；
- 集成：对象存储、元数据存储、媒体服务/处理器；
- E2E：Agent Gateway 和业务服务 Unified Entry 两条路径；
- 安全：跨租户、越权、token 过期/撤销/replay、路径穿越、MIME 欺骗；
- 幂等：重复上传初始化、重复创建/关闭会话、重复任务投递；
- 故障注入：存储超时、媒体服务半成功、数据库失败、事件重复/乱序；
- 资源：大文件、慢客户端、断流、背压、并发和泄漏；
- 日志机密审计：凭据、URL、原始媒体和完整转写不得进入日志。

测试不得只断言 HTTP 200，必须验证副作用、作用域、审计、状态迁移和失败恢复。

## 15. Vibe Coding 工作流

每个 Codex 任务必须：

1. 先阅读原始架构图、architecture baseline、本约束和现有契约；
2. 先列目标、非目标、文件清单、契约变化、风险和测试计划；
3. 小步提交，一个提交只解决一个清晰问题，禁止一次生成完整服务；
4. 先契约后实现，接口和状态机确认后再写 Adapter；
5. 每一步运行格式化、静态检查、单测和合同测试；
6. 使用另一个模型或独立 Agent 复核架构偏离、安全和测试缺口；
7. PR 写清实现映射、测试命令/结果和已知限制；
8. 禁止 TODO、空实现、恒真 mock、吞错、跳过测试后宣称完成。

不确定时应提出问题，不得编造架构事实。禁止无关重构、升级全仓依赖或修改其他服务行为。

## 16. PR 必填检查项

```markdown
## 架构映射
- [ ] 变更属于 Gateway、Unified Entry、application、domain 或 adapter 的明确一层
- [ ] 没有绕过 Unified Entry 访问底层资源
- [ ] Agent 与业务服务入口保持分离

## 租户与安全
- [ ] 所有资源操作绑定 tenant_id + biz_domain
- [ ] 无客户端可控物理路径/object key
- [ ] token、replay、scope、配额已覆盖
- [ ] 原始媒体和凭据未进入日志/审计

## 可靠性
- [ ] 写操作幂等
- [ ] 外部调用有超时/重试边界
- [ ] 部分失败有补偿或 reconciliation
- [ ] 流式路径有背压和资源回收

## 验证
- [ ] 单元/合同/集成/E2E 测试
- [ ] 跨租户与越权测试
- [ ] 故障注入与重复请求测试
- [ ] 日志机密扫描
- [ ] 文档与契约同步更新
```

## 17. 当前阶段禁止事项

在用户明确下达“开始实现某 Phase/里程碑”前，本分支只允许加入约束和架构资料。禁止创建可运行服务骨架、锁定 Web 框架/ORM/媒体服务器、新增数据库迁移、实现 API/Tool/Adapter、创建云资源/密钥/部署流水线，禁止删除、改绘、压缩或替换用户原始架构图。
