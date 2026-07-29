from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "data-control-service"
    environment: str = "local"
    log_level: str = "INFO"
    contract_version: str = "1.0"
    default_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    max_timeout_ms: int = Field(default=10_000, ge=100, le=60_000)
    max_page_limit: int = Field(default=100, ge=1, le=1000)
    max_batch_size: int = Field(default=100, ge=1, le=1000)
    idempotency_ttl_seconds: int = Field(default=86_400, ge=60)
