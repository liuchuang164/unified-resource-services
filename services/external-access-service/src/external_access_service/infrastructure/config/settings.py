from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EXTERNAL_ACCESS_", extra="ignore")

    environment: str = "test"
    api_version: str = "v1"
    log_level: str = "INFO"
    farui_base_url: str = "https://farui.example.invalid"
    farui_api_key: str | None = None
    farui_api_secret: str | None = None
    farui_token: str | None = None
    farui_enabled: bool = True
    allow_fake_credentials: bool = True
    allow_legacy_body_context: bool = True
    capability_secret: str = "test-capability-secret"
    capability_issuer: str = "hermes"
    max_concurrency: int = Field(default=8, ge=1, le=64)

    @model_validator(mode="after")
    def validate_credentials(self) -> "Settings":
        if (
            self.farui_enabled
            and not self.allow_fake_credentials
            and (not self.farui_api_key or not self.farui_api_secret)
        ):
            raise ValueError("ALI_FARUI credentials are required when fake credentials are off")
        return self
