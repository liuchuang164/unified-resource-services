from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "data-access-gateway"
    app_env: str = "development"
    log_level: str = "INFO"
    data_control_base_url: str = "http://127.0.0.1:8000"
    data_control_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    capability_token_algorithm: str = "HS256"  # noqa: S105
    capability_token_issuer: str = "unified-access-plane"  # noqa: S105
    capability_token_audience: str = "data-access-gateway"  # noqa: S105
    capability_token_shared_secret: str | None = None
    capability_token_public_key: str | None = None
    contract_version: str = "1.0"
    max_timeout_ms: int = Field(default=10_000, ge=100, le=60_000)

    @model_validator(mode="after")
    def validate_capability_token_configuration(self) -> "Settings":
        algorithm = self.capability_token_algorithm.upper()
        if algorithm not in {"HS256", "RS256", "ES256"}:
            raise ValueError("capability token algorithm is not supported")
        if self.app_env.lower() == "production" and algorithm.startswith("HS"):
            raise ValueError("symmetric capability tokens are not allowed in production")
        key = (
            self.capability_token_public_key
            if algorithm.startswith(("RS", "ES", "PS", "ED"))
            else self.capability_token_shared_secret
        )
        if not key:
            raise ValueError("capability token verification key is required")
        return self
