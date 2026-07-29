from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    environment: Literal["test", "development", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "FMS_ENVIRONMENT"),
    )
    infrastructure_mode: Literal["inmemory", "production"] = Field(
        default="inmemory", validation_alias="FMS_INFRASTRUCTURE_MODE"
    )
    log_level: str = Field(default="INFO", validation_alias="FMS_LOG_LEVEL")
    api_version: str = Field(default="v1", validation_alias="FMS_API_VERSION")
    stream_lease_seconds: int = Field(default=300, validation_alias="FMS_STREAM_LEASE_SECONDS")
    max_filename_length: int = Field(default=180, validation_alias="FMS_MAX_FILENAME_LENGTH")

    database_url: SecretStr | None = Field(default=None, validation_alias="DATABASE_URL")
    database_pool_size: int = Field(default=5, ge=1, validation_alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=10, ge=0, validation_alias="DATABASE_MAX_OVERFLOW")
    database_connect_timeout_seconds: float = Field(
        default=5, gt=0, validation_alias="DATABASE_CONNECT_TIMEOUT_SECONDS"
    )
    redis_url: SecretStr | None = Field(default=None, validation_alias="REDIS_URL")
    redis_socket_timeout_seconds: float = Field(
        default=2, gt=0, validation_alias="REDIS_SOCKET_TIMEOUT_SECONDS"
    )
    redis_lease_ttl_seconds: int = Field(
        default=30, gt=0, validation_alias="REDIS_LEASE_TTL_SECONDS"
    )
    minio_endpoint: str | None = Field(default=None, validation_alias="MINIO_ENDPOINT")
    minio_access_key: SecretStr | None = Field(default=None, validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: SecretStr | None = Field(default=None, validation_alias="MINIO_SECRET_KEY")
    minio_bucket: str | None = Field(default=None, validation_alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=True, validation_alias="MINIO_SECURE")
    minio_presigned_upload_ttl_seconds: int = Field(
        default=900, ge=60, le=3600, validation_alias="MINIO_PRESIGNED_UPLOAD_TTL_SECONDS"
    )
    minio_presigned_download_ttl_seconds: int = Field(
        default=300, ge=60, le=3600, validation_alias="MINIO_PRESIGNED_DOWNLOAD_TTL_SECONDS"
    )

    @model_validator(mode="after")
    def validate_mode(self) -> "Settings":
        if self.infrastructure_mode == "production":
            required = {
                "DATABASE_URL": self.database_url,
                "REDIS_URL": self.redis_url,
                "MINIO_ENDPOINT": self.minio_endpoint,
                "MINIO_ACCESS_KEY": self.minio_access_key,
                "MINIO_SECRET_KEY": self.minio_secret_key,
                "MINIO_BUCKET": self.minio_bucket,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(f"production infrastructure configuration missing: {missing}")
        return self
