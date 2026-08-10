# External Access Service 运维部署文档

适用范围：`services/external-access-service`

面向对象：运维、SRE、平台部署同学。

## 1. 服务定位

External Access Service 是统一外部接入服务。当前生产能力只启用 Alibaba Farui (`ALI_FARUI`) Provider。

必须保持的调用链：

- Agent 调用链：`Agent/OpenClaw/Hermes -> /eag/tools/* -> UnifiedExternalEntry -> Provider Runtime -> ALI_FARUI Adapter -> Alibaba Farui`
- 业务服务调用链：`Business service -> /external/dispatch -> UnifiedExternalEntry -> Provider Runtime -> ALI_FARUI Adapter -> Alibaba Farui`

禁止：

- 不部署独立 `farui-service` 或 `farui-gateway`。
- 不让 Agent 或业务服务直接调用法睿。
- 不把 API key、token、签名、原始法睿响应写入日志、审计、工单或部署文档。

## 2. Docker 运行环境

| 项目 | 要求 |
|---|---|
| Docker | 建议 `24.x` 或以上 |
| Docker Compose | 建议 Compose v2，即 `docker compose` |
| Git | 可访问 `liuchuang164/unified-resource-services` |
| 网络 | 服务器可访问阿里云法睿/百炼 endpoint |
| 镜像构建目录 | `services/external-access-service` |
| 容器内端口 | `8000` |
| 宿主机端口 | 默认示例 `8000`，可由部署平台映射 |
| 健康检查 | `GET /health` |
| 就绪检查 | `GET /ready` |
| Secret 挂载 | `/run/secrets/external-access-service/farui-api-key.csv` |

Python 3.12 已在 Docker 镜像内提供，运维主流程不需要在宿主机安装 Python。只有在部署机上运行 pytest/ruff/mypy 时，才需要安装 Python 或使用测试镜像。

### 2.1 安装 Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker --version
docker compose version
git --version
```

CentOS/RHEL 示例：

```bash
sudo yum install -y yum-utils git curl
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker --version
docker compose version
git --version
```

如运维账号需要直接执行 Docker 命令：

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker ps
```

### 2.2 生产目录约定

以下命令假设使用这些目录：

```bash
sudo mkdir -p /opt/unified-resource-services
sudo mkdir -p /etc/external-access-service/secrets
sudo mkdir -p /var/log/external-access-service
sudo chown -R "$USER":"$USER" /opt/unified-resource-services
sudo chown -R root:root /etc/external-access-service
sudo chmod 750 /etc/external-access-service
sudo chmod 750 /etc/external-access-service/secrets
```

服务目录：

```text
/opt/unified-resource-services/services/external-access-service
```

生产环境变量文件：

```text
/etc/external-access-service/external-access-service.env
```

法睿 CSV Secret 文件：

```text
/etc/external-access-service/secrets/farui-api-key.csv
```

容器内 Secret 挂载路径：

```text
/run/secrets/external-access-service/farui-api-key.csv
```

### 2.3 镜像信息

| 项目 | 值 |
|---|---|
| Dockerfile | `services/external-access-service/Dockerfile` |
| 镜像名示例 | `external-access-service` |
| 标签示例 | Git short SHA，例如 `162c0b5` |
| 容器用户 | `65532:65532` |
| 启动命令 | `uvicorn external_access_service.main:app --host 0.0.0.0 --port 8000` |

## 3. 配置项

服务使用 `pydantic-settings`，默认读取 `EXTERNAL_ACCESS_` 前缀配置；法睿兼容变量也会直接读取 `ALI_FARUI_*` / `FARUI_*`。

### 3.1 基础配置

| 变量 | 示例 | 说明 |
|---|---|---|
| `EXTERNAL_ACCESS_ENVIRONMENT` | `prod` | 环境名。`test` 会启用本地 mock transport。 |
| `EXTERNAL_ACCESS_LOG_LEVEL` | `INFO` | 日志级别。 |
| `EXTERNAL_ACCESS_ALLOW_FAKE_CREDENTIALS` | `false` | 生产必须为 `false`。 |
| `EXTERNAL_ACCESS_ALLOW_LEGACY_BODY_CONTEXT` | `false` | 建议生产关闭 body legacy context。 |
| `EXTERNAL_ACCESS_CAPABILITY_SECRET` | secret ref | Capability token 签名密钥，必须来自密钥系统。 |
| `EXTERNAL_ACCESS_CAPABILITY_ISSUER` | `hermes` | Capability token issuer。 |
| `EXTERNAL_ACCESS_MAX_CONCURRENCY` | `8` | 并发上限，范围 1 到 64。 |

### 3.2 法睿 ACS3 AK/SK 模式

用于阿里法睿官方 ACS3 签名接口。

| 变量 | 说明 |
|---|---|
| `EXTERNAL_ACCESS_FARUI_BASE_URL` | 默认建议 `https://farui.cn-beijing.aliyuncs.com` |
| `ALI_FARUI_ACCESS_KEY_ID` 或 `FARUI_ACCESS_KEY_ID` | AccessKey ID |
| `ALI_FARUI_ACCESS_KEY_SECRET` 或 `FARUI_ACCESS_KEY_SECRET` | AccessKey Secret |
| `ALI_FARUI_WORKSPACE_ID` 或 `FARUI_WORKSPACE_ID` | 法睿 workspace id |

### 3.3 业务空间 API Key / CSV 模式

用于用户提供的业务空间 CSV。当前验证通过的默认路径是 CSV 中的 `openAiCompatible` endpoint + `qwen-plus` 模型。

| 变量 | 说明 |
|---|---|
| `EXTERNAL_ACCESS_FARUI_CREDENTIALS_FILE` | CSV 凭据文件路径 |
| `ALI_FARUI_CREDENTIALS_FILE` 或 `FARUI_CREDENTIALS_FILE` | CSV 凭据文件路径别名 |
| `ALI_FARUI_ENDPOINT` 或 `FARUI_ENDPOINT` | 不使用 CSV 时可显式设置 endpoint |
| `ALI_FARUI_APP_KEY` | 不使用 CSV 时可显式设置 API key |
| `ALI_FARUI_MODEL` 或 `FARUI_MODEL` | 可覆盖默认模型，默认 `qwen-plus` |

CSV 文件字段要求：

| 字段 | 是否必需 | 说明 |
|---|---|---|
| `apiKey` | 是 | 业务空间 API key |
| `openAiCompatible` | 建议 | 已验证通过的 OpenAI-compatible endpoint |
| `dashScope` | 可选 | DashScope endpoint。只有 app 授权确认后才建议使用 app completion。 |
| `workspaceId` | 可选 | 业务空间 id，作为连接元数据 |
| `id` | 可选 | 业务空间导出的 app/model id；当前不要默认当作 app completion id 使用 |

注意：不要将 CSV 文件提交到 Git。部署时通过密钥系统、挂载 Secret 文件或受控配置分发。

## 4. 端口和接口

### 4.1 运维检查接口

| 方法 | 路径 | 预期 |
|---|---|---|
| `GET` | `/health` | `{"status":"ok"}` |
| `GET` | `/ready` | `status=ready`，providers 显示 provider 状态 |
| `GET` | `/external/providers/health` | 返回各 provider 健康状态 |

### 4.2 Agent Tool 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/eag/tools?tenant_id=tenant_A&biz_domain=LEGAL` | 列出 Agent 可见 tools |
| `GET` | `/eag/tools/ali_farui/schema` | 查看 `ali_farui` action schema |
| `POST` | `/eag/tools/execute` | Agent Tool 执行入口 |

当前 Agent Tool：

| Tool | Action | Canonical operation |
|---|---|---|
| `ali_farui` | `legal_consult` | `ALI_FARUI_LEGAL_CONSULT` |
| `ali_farui` | `law_search` | `ALI_FARUI_LAW_SEARCH` |
| `ali_farui` | `case_search` | `ALI_FARUI_CASE_SEARCH` |
| `ali_farui` | `legal_research_full` | `ALI_FARUI_LEGAL_RESEARCH_FULL` |

### 4.3 业务服务接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/external/operations?tenant_id=tenant_A&biz_domain=LEGAL` | 列出 canonical operations |
| `GET` | `/external/operations/{operation}/schema` | 查看 operation payload schema |
| `POST` | `/external/dispatch` | 业务服务统一外部派发入口 |
| `GET` | `/external/usage` | 查询用量 |
| `GET` | `/external/audit` | 查询审计 |

## 5. Docker 部署步骤

### 5.1 拉取代码

首次部署：

```bash
cd /opt
git clone https://github.com/liuchuang164/unified-resource-services.git
cd /opt/unified-resource-services
git checkout codex/external-access-ali-farui-constraints
git rev-parse --short HEAD
```

已有目录升级：

```bash
cd /opt/unified-resource-services
git fetch origin
git checkout codex/external-access-ali-farui-constraints
git pull --ff-only
git rev-parse --short HEAD
```

### 5.2 准备配置目录和 Secret 文件

创建目录：

```bash
sudo mkdir -p /etc/external-access-service/secrets
sudo chmod 750 /etc/external-access-service
sudo chmod 750 /etc/external-access-service/secrets
```

如果使用 CSV 凭据，把 CSV 复制到 Secret 目录。不要在命令行粘贴真实 key：

```bash
sudo cp /path/to/默认业务空间-apiKey-6381250.csv \
  /etc/external-access-service/secrets/farui-api-key.csv
sudo chown root:root /etc/external-access-service/secrets/farui-api-key.csv
sudo chmod 640 /etc/external-access-service/secrets/farui-api-key.csv
```

检查文件存在和权限：

```bash
sudo test -f /etc/external-access-service/secrets/farui-api-key.csv
sudo ls -l /etc/external-access-service/secrets/farui-api-key.csv
```

只检查 CSV 字段，不输出密钥：

```bash
docker run --rm \
  -v /etc/external-access-service/secrets/farui-api-key.csv:/run/secrets/external-access-service/farui-api-key.csv:ro \
  python:3.12-slim \
  python - <<'PY'
import csv
from pathlib import Path

path = Path("/run/secrets/external-access-service/farui-api-key.csv")
with path.open(newline="", encoding="utf-8-sig") as handle:
    values = {row[0].strip(): row[1].strip() for row in csv.reader(handle) if len(row) >= 2}

for key in ["apiKey", "openAiCompatible", "workspaceId", "id"]:
    print(f"{key}: {'PRESENT' if values.get(key) else 'MISSING'}")
PY
```

### 5.3 创建环境变量文件

CSV 模式推荐配置：

```bash
sudo tee /etc/external-access-service/external-access-service.env >/dev/null <<'EOF'
EXTERNAL_ACCESS_ENVIRONMENT=prod
EXTERNAL_ACCESS_LOG_LEVEL=INFO
EXTERNAL_ACCESS_ALLOW_FAKE_CREDENTIALS=false
EXTERNAL_ACCESS_ALLOW_LEGACY_BODY_CONTEXT=false
EXTERNAL_ACCESS_FARUI_BASE_URL=https://farui.cn-beijing.aliyuncs.com
EXTERNAL_ACCESS_FARUI_CREDENTIALS_FILE=/run/secrets/external-access-service/farui-api-key.csv
EXTERNAL_ACCESS_CAPABILITY_ISSUER=hermes
EXTERNAL_ACCESS_MAX_CONCURRENCY=8
EXTERNAL_ACCESS_CAPABILITY_SECRET=<replace-with-secret-ref-or-secret>
EOF
sudo chmod 640 /etc/external-access-service/external-access-service.env
```

ACS3 AK/SK 模式配置：

```bash
sudo tee /etc/external-access-service/external-access-service.env >/dev/null <<'EOF'
EXTERNAL_ACCESS_ENVIRONMENT=prod
EXTERNAL_ACCESS_LOG_LEVEL=INFO
EXTERNAL_ACCESS_ALLOW_FAKE_CREDENTIALS=false
EXTERNAL_ACCESS_ALLOW_LEGACY_BODY_CONTEXT=false
EXTERNAL_ACCESS_FARUI_BASE_URL=https://farui.cn-beijing.aliyuncs.com
EXTERNAL_ACCESS_CAPABILITY_ISSUER=hermes
EXTERNAL_ACCESS_MAX_CONCURRENCY=8
ALI_FARUI_ACCESS_KEY_ID=<replace-with-secret>
ALI_FARUI_ACCESS_KEY_SECRET=<replace-with-secret>
ALI_FARUI_WORKSPACE_ID=<replace-with-workspace-id>
EXTERNAL_ACCESS_CAPABILITY_SECRET=<replace-with-secret-ref-or-secret>
EOF
sudo chmod 640 /etc/external-access-service/external-access-service.env
```

检查配置文件，不打印密钥值：

```bash
sudo grep -E '^(EXTERNAL_ACCESS_ENVIRONMENT|EXTERNAL_ACCESS_ALLOW_FAKE_CREDENTIALS|EXTERNAL_ACCESS_FARUI_BASE_URL|EXTERNAL_ACCESS_FARUI_CREDENTIALS_FILE|ALI_FARUI_WORKSPACE_ID)=' \
  /etc/external-access-service/external-access-service.env
```

### 5.4 构建 Docker 镜像

```bash
cd /opt/unified-resource-services/services/external-access-service
IMAGE_TAG="$(git -C /opt/unified-resource-services rev-parse --short HEAD)"
docker build -t external-access-service:${IMAGE_TAG} .
docker image ls external-access-service:${IMAGE_TAG}
```

也可以同时打 `latest` 标签：

```bash
docker tag external-access-service:${IMAGE_TAG} external-access-service:latest
```

### 5.5 使用 docker run 启动

先清理旧容器：

```bash
docker rm -f external-access-service || true
```

CSV 模式启动：

```bash
IMAGE_TAG="$(git -C /opt/unified-resource-services rev-parse --short HEAD)"
docker run -d \
  --name external-access-service \
  --restart unless-stopped \
  --env-file /etc/external-access-service/external-access-service.env \
  -p 8000:8000 \
  -v /etc/external-access-service/secrets/farui-api-key.csv:/run/secrets/external-access-service/farui-api-key.csv:ro \
  external-access-service:${IMAGE_TAG}
```

ACS3 AK/SK 模式启动不需要挂载 CSV：

```bash
IMAGE_TAG="$(git -C /opt/unified-resource-services rev-parse --short HEAD)"
docker run -d \
  --name external-access-service \
  --restart unless-stopped \
  --env-file /etc/external-access-service/external-access-service.env \
  -p 8000:8000 \
  external-access-service:${IMAGE_TAG}
```

查看容器状态：

```bash
docker ps --filter name=external-access-service
docker logs --tail 100 external-access-service
```

### 5.6 使用 docker compose 启动

如果运维更习惯 compose，可以直接使用仓库中的模板：

```bash
sudo cp /opt/unified-resource-services/services/external-access-service/docker-compose.example.yml \
  /etc/external-access-service/docker-compose.yml
sudo chmod 640 /etc/external-access-service/docker-compose.yml
cd /etc/external-access-service
docker compose config
```

启动：

```bash
cd /etc/external-access-service
docker compose up -d
docker compose ps
docker compose logs --tail 100 external-access-service
```

如果使用 ACS3 AK/SK 模式，请删除 compose 中 `volumes` 里 CSV 挂载行，或保留一个存在但不会被使用的只读文件。

### 5.7 执行健康检查

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
docker inspect --format='{{json .State.Health}}' external-access-service
```

预期：

- `/health` 返回 `{"status":"ok"}`。
- `/ready` 返回 `status=ready`。
- Docker health 为 `healthy`。

### 5.8 执行 smoke test

```bash
curl -fsS "http://127.0.0.1:8000/eag/tools?tenant_id=tenant_A&biz_domain=LEGAL"
curl -fsS "http://127.0.0.1:8000/external/operations?tenant_id=tenant_A&biz_domain=LEGAL"
curl -fsS "http://127.0.0.1:8000/external/providers"
curl -fsS "http://127.0.0.1:8000/external/providers/health"
```

预期：

- `/eag/tools` 返回 `ali_farui`。
- `actions` 包含 `legal_consult`、`law_search`、`case_search`、`legal_research_full`。
- `/external/operations` 返回 4 个 `ALI_FARUI_*` operations。
- `/external/providers` 返回 `ALI_FARUI`。

### 5.9 容器内执行接口验证

使用正在运行的容器执行检查：

```bash
docker exec external-access-service python - <<'PY'
import urllib.request

for path in ["/health", "/ready"]:
    with urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=5) as resp:
        print(path, resp.status, resp.read(120).decode("utf-8"))
PY
```

### 5.10 执行自动化测试

Docker 生产镜像不包含测试依赖。测试请在源码目录执行：

```bash
cd /opt/unified-resource-services/services/external-access-service
python3.12 -m venv .venv-test
source .venv-test/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m ruff check .
PYTHONPATH=src python -m mypy src/external_access_service
```

预期：

- `56 passed, 2 skipped`
- `All checks passed!`
- `Success: no issues found in 58 source files`

### 5.11 执行真实法睿门禁

```bash
cd /opt/unified-resource-services/services/external-access-service
source .venv-test/bin/activate
set -a
source /etc/external-access-service/external-access-service.env
set +a
RUN_REAL_FARUI_GATE=1 PYTHONPATH=src python -m pytest tests/integration/test_real_farui_gate.py -q
```

通过标准：`2 passed`。

真实门禁会实际外呼 6 次：

- Business path：`legal_consult`、`law_search`、`case_search`
- Agent path：`legal_consult`、`law_search`、`case_search`

## 6. 部署后验收

| 检查项 | 命令 | 通过标准 |
|---|---|---|
| 容器进程 | `docker ps --filter name=external-access-service` | 容器 `Up` |
| Docker health | `docker inspect --format='{{json .State.Health.Status}}' external-access-service` | `healthy` |
| 服务存活 | `curl -fsS http://127.0.0.1:8000/health` | HTTP 200，`status=ok` |
| 服务就绪 | `curl -fsS http://127.0.0.1:8000/ready` | HTTP 200，`status=ready` |
| Provider 注册 | `curl -fsS http://127.0.0.1:8000/external/providers` | `ALI_FARUI` 状态 enabled |
| Tool 可见 | `curl -fsS "http://127.0.0.1:8000/eag/tools?tenant_id=tenant_A&biz_domain=LEGAL"` | 返回 `ali_farui` 和 4 个 actions |
| Operation 可见 | `curl -fsS "http://127.0.0.1:8000/external/operations?tenant_id=tenant_A&biz_domain=LEGAL"` | 返回 4 个 `ALI_FARUI_*` operations |
| 真实门禁 | `RUN_REAL_FARUI_GATE=1 PYTHONPATH=src python -m pytest tests/integration/test_real_farui_gate.py -q` | `2 passed` |

## 7. 回滚策略

### 7.1 查看当前版本

```bash
cd /opt/unified-resource-services
git rev-parse --short HEAD
git log --oneline -5
docker inspect --format='{{.Config.Image}}' external-access-service
docker images external-access-service
```

### 7.2 使用 docker run 回滚到指定镜像标签

```bash
cd /opt/unified-resource-services
TARGET_TAG=<target-image-tag>
docker image inspect external-access-service:${TARGET_TAG}
docker rm -f external-access-service || true
docker run -d \
  --name external-access-service \
  --restart unless-stopped \
  --env-file /etc/external-access-service/external-access-service.env \
  -p 8000:8000 \
  -v /etc/external-access-service/secrets/farui-api-key.csv:/run/secrets/external-access-service/farui-api-key.csv:ro \
  external-access-service:${TARGET_TAG}
docker ps --filter name=external-access-service
```

### 7.3 使用 docker compose 回滚到指定镜像标签

修改 `/etc/external-access-service/docker-compose.yml` 中的 image：

```yaml
image: external-access-service:<target-image-tag>
```

然后执行：

```bash
cd /etc/external-access-service
docker compose up -d
docker compose ps
docker compose logs --tail 100 external-access-service
```

### 7.4 回滚后验证

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
curl -fsS "http://127.0.0.1:8000/eag/tools?tenant_id=tenant_A&biz_domain=LEGAL"
docker inspect --format='{{json .State.Health.Status}}' external-access-service
```

如回滚原因与法睿真实链路有关，重新执行真实门禁并记录 PASS/FAIL/NOT_RUN。

## 8. 常见故障

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `/health` 失败 | 服务进程未启动或端口不通 | 检查进程、端口、容器日志 |
| `/ready` provider 不正常 | Provider 初始化或配置异常 | 检查 `EXTERNAL_ACCESS_*` 和 `ALI_FARUI_*` 配置 |
| `PROVIDER_AUTH_FAILED` | API key、AK/SK、workspace、endpoint 不匹配 | 换用正确 Secret；不要在日志中打印密钥 |
| `PROVIDER_TIMEOUT` | 法睿响应慢或网络抖动 | 复跑门禁，检查网络出口和 provider SLA |
| `PROVIDER_RATE_LIMITED` | Provider 限流 | 降低并发，检查 retry-after |
| `OPERATION_NOT_ALLOWED` | operation 未注册或 policy 禁止 | 检查 operation 名称、tenant、biz_domain、角色 |
| `INVALID_REQUEST` | 请求 schema 不合法 | 检查必填字段和 payload |

## 9. 安全要求

- 生产必须设置 `EXTERNAL_ACCESS_ALLOW_FAKE_CREDENTIALS=false`。
- 密钥只能通过 Secret 管理系统、环境变量或受控挂载文件注入。
- 不允许把 `apiKey`、AK/SK、token、Authorization、签名写入日志、监控 label、审计记录或工单。
- 调用方不得在 payload 中传入 provider credential。
- 所有请求必须带 `tenant_id + biz_domain`，并由服务端可信上下文校验。

## 10. 变更发布检查单

- [ ] 配置已按环境注入，未使用本地测试密钥。
- [ ] `EXTERNAL_ACCESS_ALLOW_FAKE_CREDENTIALS=false`。
- [ ] `/health` 通过。
- [ ] `/ready` 通过。
- [ ] `/eag/tools` 返回 `ali_farui`。
- [ ] `/external/operations` 返回 4 个法睿 operations。
- [ ] 本地质量门或 CI：pytest、ruff、mypy 通过。
- [ ] 真实法睿门禁按需 PASS，或明确记录 NOT_RUN/FAIL 原因。
