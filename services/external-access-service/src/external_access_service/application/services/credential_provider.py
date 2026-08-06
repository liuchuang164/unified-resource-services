import csv
import os
from pathlib import Path

from external_access_service.application.ports.protocols import CredentialProviderPort
from external_access_service.domain.errors import ProviderNotConfigured
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCredential
from external_access_service.infrastructure.config import Settings


class EnvironmentCredentialProvider(CredentialProviderPort):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_credential(self, request: ExternalDispatchRequest) -> ProviderCredential:
        if request.provider.provider_code.value == "MOCK_LEGAL_PROVIDER":
            return ProviderCredential(
                credential_ref=(
                    f"{request.auth_context.tenant_id}:{request.biz_context.biz_domain}:"
                    "MOCK_LEGAL_PROVIDER:test"
                ),
                version="test",
                api_key="mock-provider-key",
                api_secret="mock-provider-secret",
            )
        if request.provider.provider_code.value != "ALI_FARUI":
            raise ProviderNotConfigured("Provider credentials are not configured")
        configured = self._load_farui_credential()
        api_key = configured.get("api_key")
        api_secret = configured.get("api_secret")
        auth_mode = configured.get("auth_mode") or "acs3"
        if self.settings.allow_fake_credentials and (not api_key or not api_secret):
            api_key = "test-api-key"
            api_secret = "test-api-secret"
            configured["workspace_id"] = configured.get("workspace_id") or "test-workspace"
            configured["endpoint"] = configured.get("endpoint") or self.settings.farui_base_url
            auth_mode = "acs3"
        if not api_key or not api_secret:
            raise ProviderNotConfigured("ALI_FARUI credentials are missing")
        return ProviderCredential(
            credential_ref=(
                f"{request.auth_context.tenant_id}:{request.biz_context.biz_domain}:"
                "ALI_FARUI:test"
            ),
            version="test",
            api_key=api_key,
            api_secret=api_secret,
            token=configured.get("token"),
            workspace_id=configured.get("workspace_id"),
            endpoint=configured.get("endpoint"),
            auth_mode=auth_mode,
            model=configured.get("model"),
        )

    def _load_farui_credential(self) -> dict[str, str | None]:
        env = os.environ
        api_key = (
            self.settings.farui_api_key
            or env.get("ALI_FARUI_ACCESS_KEY_ID")
            or env.get("FARUI_ACCESS_KEY_ID")
            or env.get("ALI_FARUI_APP_KEY")
        )
        api_secret = (
            self.settings.farui_api_secret
            or env.get("ALI_FARUI_ACCESS_KEY_SECRET")
            or env.get("FARUI_ACCESS_KEY_SECRET")
            or env.get("ALI_FARUI_APP_SECRET")
        )
        workspace_id = (
            self.settings.farui_workspace_id
            or env.get("ALI_FARUI_WORKSPACE_ID")
            or env.get("FARUI_WORKSPACE_ID")
        )
        endpoint = (
            self.settings.farui_endpoint
            or env.get("ALI_FARUI_ENDPOINT")
            or env.get("FARUI_ENDPOINT")
        )
        model = self.settings.farui_model or env.get("ALI_FARUI_MODEL") or env.get("FARUI_MODEL")
        token = self.settings.farui_token or env.get("ALI_FARUI_TOKEN") or env.get("FARUI_TOKEN")

        credentials_file = (
            self.settings.farui_credentials_file
            or env.get("ALI_FARUI_CREDENTIALS_FILE")
            or env.get("FARUI_CREDENTIALS_FILE")
            or env.get("EXTERNAL_ACCESS_FARUI_CREDENTIALS_FILE")
        )
        file_values = self._read_credentials_file(credentials_file) if credentials_file else {}
        if file_values:
            api_key = api_key or file_values.get("api_key")
            endpoint = endpoint or file_values.get("endpoint")
            workspace_id = workspace_id or file_values.get("workspace_id")
            model = model or file_values.get("model")
            if api_secret is None and file_values.get("auth_mode") == "workspace_api_key":
                api_secret = file_values.get("api_key")
        if api_key and endpoint and not api_secret:
            api_secret = api_key

        auth_mode = (
            "workspace_api_key" if endpoint and api_key and api_secret == api_key else "acs3"
        )
        return {
            "api_key": api_key,
            "api_secret": api_secret,
            "workspace_id": workspace_id,
            "endpoint": endpoint,
            "auth_mode": auth_mode,
            "model": model,
            "token": token,
        }

    @staticmethod
    def _read_credentials_file(path: str | None) -> dict[str, str]:
        if not path:
            return {}
        file_path = Path(path).expanduser()
        if not file_path.exists():
            raise ProviderNotConfigured("ALI_FARUI credentials file is missing")
        if file_path.suffix.lower() != ".csv":
            raise ProviderNotConfigured("ALI_FARUI credentials file must be a CSV")
        with file_path.open(newline="", encoding="utf-8-sig") as handle:
            values = {row[0].strip(): row[1].strip() for row in csv.reader(handle) if len(row) >= 2}
        api_key = values.get("apiKey") or values.get("api_key")
        endpoint = (
            values.get("dashScope")
            or values.get("openAiCompatible")
            or values.get("apiHost")
            or values.get("endpoint")
        )
        if endpoint and "://" not in endpoint:
            endpoint = f"https://{endpoint}"
        return {
            "api_key": api_key or "",
            "endpoint": endpoint or "",
            "workspace_id": values.get("workspaceId", ""),
            "model": values.get("model") or values.get("id") or "farui",
            "auth_mode": "workspace_api_key",
        }
