from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from data_access_gateway.minio_tool import MINIO_TOOL


def main() -> None:
    parser = argparse.ArgumentParser(description="issue a development-only capability token")
    parser.add_argument("--agent-id", default="agent_demo")
    parser.add_argument("--tenant-id", default="tenant_demo")
    parser.add_argument("--biz-domain", default="demo")
    parser.add_argument("--session-id", default="session_demo")
    parser.add_argument("--task-id", default="task_demo")
    parser.add_argument("--ttl-seconds", type=int, default=900)
    args = parser.parse_args()

    shared_secret = os.environ.get("CAPABILITY_TOKEN_SHARED_SECRET")
    if not shared_secret:
        raise SystemExit("CAPABILITY_TOKEN_SHARED_SECRET is required")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": os.environ.get("CAPABILITY_TOKEN_ISSUER", "unified-access-plane"),
            "aud": ["data-access-gateway", "data-control-service"],
            "sub": args.agent_id,
            "subject_type": "AGENT",
            "tenant_id": args.tenant_id,
            "biz_domain": args.biz_domain,
            "session_id": args.session_id,
            "task_id": args.task_id,
            "roles": ["AGENT"],
            "permissions": [
                "data:object:read",
                "data:object:write",
                "data:asset:read",
                "data:asset:write",
                "data:high-risk:execute",
            ],
            "allowed_tools": [MINIO_TOOL.name],
            "allowed_actions": [
                f"{MINIO_TOOL.name}:{action.name}" for action in MINIO_TOOL.actions
            ],
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=args.ttl_seconds),
            "jti": f"jti_{uuid4().hex}",
        },
        shared_secret,
        algorithm="HS256",
    )
    print(token)


if __name__ == "__main__":
    main()
