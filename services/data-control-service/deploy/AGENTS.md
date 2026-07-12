# AGENTS.md — data-control-service/deploy

继承仓库根目录和服务目录全部约束。

约束维护模式下禁止新增或修改实际部署清单。只有用户明确要求实施部署 Phase，并且服务已有可验证构建产物时，才可修改本目录。

部署必须保持 `data-control-service` 独立构建、发布、迁移、扩缩容和故障隔离。不得把三个微服务打入同一进程或单一强耦合镜像。

Data Access Gateway、统一数据入口与 Adapter 可以位于同一服务部署单元内，但运行时职责必须保持分层；Gateway 不得获得绕过统一入口的数据库权限。

Secret 只能通过最小权限引用注入，禁止提交真实连接串、密码、Token 或私钥。Readiness 必须反映必需的 Registry、Route 和关键 Adapter 可用性；Liveness 不得因暂时依赖故障造成重启风暴。
