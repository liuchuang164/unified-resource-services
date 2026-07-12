# Local Infrastructure

本目录用于三个微服务的本地联调编排，例如 PostgreSQL、Redis、MinIO、消息中间件和本地网络。

约束：

- 不在这里存放服务业务迁移；
- 不把三个服务合并为一个进程；
- Compose 只用于本地开发和集成测试；
- 生产部署定义由各服务目录和 `infra/kubernetes` 共同组织。
