from external_access_service.application.ports.protocols import CredentialProviderPort
from external_access_service.domain.errors import ProviderNotConfigured
from external_access_service.domain.models import ExternalDispatchRequest, ProviderCredential
from external_access_service.infrastructure.config import Settings


class EnvironmentCredentialProvider(CredentialProviderPort):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_credential(self, request: ExternalDispatchRequest) -> ProviderCredential:
        if request.provider.provider_code.value != "ALI_FARUI":
            raise ProviderNotConfigured("Provider credentials are not configured")
        api_key = self.settings.farui_api_key
        api_secret = self.settings.farui_api_secret
        if self.settings.allow_fake_credentials and (not api_key or not api_secret):
            api_key = "test-api-key"
            api_secret = "test-api-secret"
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
            token=self.settings.farui_token,
        )
