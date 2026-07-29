from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "data-control-service"
    app_env: str = "development"
    log_level: str = "INFO"
    auth_provider: str = "development"
    contract_version: str = "1.0"
    default_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    max_timeout_ms: int = Field(default=10_000, ge=100, le=60_000)
    max_page_limit: int = Field(default=100, ge=1, le=1000)
    max_batch_size: int = Field(default=100, ge=1, le=1000)
    idempotency_ttl_seconds: int = Field(default=86_400, ge=60)
    max_redis_ttl_seconds: int = Field(default=86_400, ge=1)
    max_object_size_bytes: int = Field(default=10_485_760, ge=1)
    max_presigned_url_ttl_seconds: int = Field(default=900, ge=1)
    max_vector_top_k: int = Field(default=20, ge=1)
    max_timeseries_query_days: int = Field(default=31, ge=1)
