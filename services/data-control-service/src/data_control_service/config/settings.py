from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "data-control-service"
    app_env: str = "development"
    log_level: str = "INFO"
    auth_provider: str = "development"
    capability_token_algorithm: str = "HS256"  # noqa: S105
    capability_token_issuer: str = "unified-access-plane"  # noqa: S105
    capability_token_audience: str = "data-control-service"  # noqa: S105
    capability_token_shared_secret: str | None = None
    capability_token_public_key: str | None = None
    control_database_url: str | None = None
    control_database_migration_url: str | None = None
    control_migration_head_revision: str = "0007"
    postgresql_adapter_enabled: bool = False
    postgresql_adapter_required: bool = True
    postgresql_adapter_database_url: str | None = None
    target_migration_head_revision: str = "target_0001"
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)
    database_pool_timeout_seconds: int = Field(default=30, ge=1)
    database_statement_timeout_ms: int = Field(default=5000, ge=100)
    database_connect_timeout_seconds: int = Field(default=10, ge=1)
    redis_adapter_enabled: bool = False
    redis_adapter_required: bool = True
    redis_url: str | None = None
    redis_username: str | None = None
    redis_password: str | None = None
    redis_socket_connect_timeout_seconds: float = Field(default=2.0, gt=0)
    redis_socket_timeout_seconds: float = Field(default=2.0, gt=0)
    redis_health_check_interval_seconds: int = Field(default=30, ge=0)
    redis_max_connections: int = Field(default=50, ge=1)
    redis_default_ttl_seconds: int = Field(default=3600, ge=1)
    redis_max_ttl_seconds: int = Field(default=86_400, ge=1)
    redis_lock_default_ttl_seconds: int = Field(default=30, ge=1)
    redis_lock_max_ttl_seconds: int = Field(default=300, ge=1)
    redis_key_prefix: str = Field(default="dcs", min_length=1, max_length=32)
    redis_scan_disabled: bool = True
    redis_max_value_bytes: int = Field(default=65_536, ge=1)
    minio_adapter_enabled: bool = False
    minio_adapter_required: bool = True
    minio_endpoint: str | None = None
    minio_secure: bool = False
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_connect_timeout_seconds: float = Field(default=3.0, gt=0)
    minio_read_timeout_seconds: float = Field(default=30.0, gt=0)
    minio_max_concurrency: int = Field(default=20, ge=1)
    minio_default_bucket: str = Field(default="dcs-objects", min_length=3, max_length=63)
    minio_auto_create_buckets: bool = False
    minio_max_object_size_bytes: int = Field(default=52_428_800, ge=1)
    minio_default_presigned_upload_ttl_seconds: int = Field(default=900, ge=1)
    minio_default_presigned_download_ttl_seconds: int = Field(default=300, ge=1)
    minio_max_presigned_ttl_seconds: int = Field(default=3600, ge=1)
    minio_allowed_content_types: str = (
        "application/pdf,image/png,image/jpeg,text/plain,application/json,"
        "audio/mpeg,audio/wav,video/mp4"
    )
    minio_allowed_extensions: str = ".pdf,.png,.jpg,.jpeg,.txt,.json,.mp3,.wav,.mp4"
    minio_multipart_threshold_bytes: int = Field(default=10_485_760, ge=1)
    minio_multipart_part_size_bytes: int = Field(default=5_242_880, ge=1)
    minio_pending_upload_expiry_seconds: int = Field(default=3600, ge=60)
    idempotency_processing_timeout_seconds: int = Field(default=120, ge=1)
    idempotency_recovery_max_attempts: int = Field(default=3, ge=1, le=10)
    audit_enabled: bool = True
    audit_fail_closed_for_writes: bool = True
    audit_payload_max_bytes: int = Field(default=4096, ge=128)
    audit_outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    audit_outbox_max_attempts: int = Field(default=10, ge=1, le=100)
    audit_outbox_lock_timeout_seconds: int = Field(default=300, ge=1)
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
