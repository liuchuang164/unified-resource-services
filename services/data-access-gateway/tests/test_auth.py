from datetime import UTC, datetime, timedelta

import jwt
import pytest

from data_access_gateway.auth import CapabilityTokenVerifier
from data_access_gateway.config import Settings
from data_access_gateway.errors import GatewayError

SECRET = "test-capability-secret-with-sufficient-length"  # noqa: S105


def test_verifier_rejects_expired_token() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "unified-access-plane",
            "aud": "data-access-gateway",
            "sub": "agent_demo",
            "tenant_id": "tenant_demo",
            "biz_domain": "demo",
            "session_id": "session_demo",
            "task_id": "task_demo",
            "iat": now - timedelta(minutes=10),
            "exp": now - timedelta(minutes=5),
            "jti": "expired",
        },
        SECRET,
        algorithm="HS256",
    )
    verifier = CapabilityTokenVerifier(
        Settings(app_env="test", capability_token_shared_secret=SECRET)
    )
    with pytest.raises(GatewayError) as exc_info:
        verifier.verify_authorization(f"Bearer {token}")
    assert exc_info.value.code == "CAPABILITY_TOKEN_INVALID"


def test_production_rejects_shared_secret_algorithm() -> None:
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            capability_token_shared_secret=SECRET,
        )
