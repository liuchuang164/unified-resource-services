# Data Access Gateway

Data Access Gateway is the Agent Tool protocol layer in front of
`data-control-service`. It validates capability tokens and Tool schemas, then converts
pre-registered Tool actions into the frozen `DataRequest` contract.

The Gateway does not connect to MinIO and does not store business idempotency state.
All data authorization, idempotency, routing, physical object-key generation, adapter
execution and authoritative data auditing remain in `POST /data/dispatch`.

## Endpoints

- `GET /dag/tools`
- `GET /dag/tools/{tool_name}/schema`
- `POST /dag/tools/execute`
- `GET /health/live`
- `GET /health/ready`

## Development

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
export CAPABILITY_TOKEN_SHARED_SECRET="$(openssl rand -hex 32)"
uvicorn data_access_gateway.app:app --host 127.0.0.1 --port 8081
```

The downstream service must use the same verification material:

```env
AUTH_PROVIDER=capability_token
CAPABILITY_TOKEN_ALGORITHM=HS256
CAPABILITY_TOKEN_ISSUER=unified-access-plane
CAPABILITY_TOKEN_AUDIENCE=data-control-service
CAPABILITY_TOKEN_SHARED_SECRET=<same-development-secret>
```

Issue a short-lived development token:

```bash
TOKEN="$(python scripts/issue_dev_token.py)"
```

Discover visible tools:

```bash
curl -s http://127.0.0.1:8081/dag/tools \
  -H "Authorization: Bearer ${TOKEN}"
```

Execute a logical MinIO action:

```bash
curl -s -X POST http://127.0.0.1:8081/dag/tools/execute \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "contract_version": "1.0",
    "request_id": "req_agent_minio_001",
    "trace_id": "trace_agent_minio_001",
    "session_id": "session_demo",
    "task_id": "task_demo",
    "tool_call_id": "call_agent_minio_001",
    "tenant_id": "tenant_demo",
    "biz_domain": "demo",
    "tool_name": "minio_file_access",
    "action": "object_exists",
    "params": {"logical_object_id": "obj_demo"},
    "timeout_ms": 10000
  }'
```

Never commit capability-token keys, MinIO credentials, presigned URLs or local
connection files.

## Full-chain Docker deployment

Create untracked `.env.data-control` and `.env.gateway` files, then run:

```bash
docker compose -f docker-compose.full-chain.yml up -d --build
docker compose -f docker-compose.full-chain.yml ps
```

Both services must use the same capability-token verification material. Only
`.env.data-control` contains PostgreSQL, Redis and MinIO connection settings; the
Gateway environment contains no target-data credentials.
