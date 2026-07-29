from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FMS_", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    api_version: str = "v1"
    stream_lease_seconds: int = 300
    max_filename_length: int = 180
