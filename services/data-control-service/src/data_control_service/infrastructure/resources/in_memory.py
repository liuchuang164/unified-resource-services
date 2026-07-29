from data_control_service.contracts.enums import DataTarget
from data_control_service.domain.policies import ResourceMapping, ResourceRegistry
from data_control_service.ports.resource_mapping_repository import ResourceMappingRepository


class InMemoryResourceMappingRepository(ResourceMappingRepository):
    def __init__(self, registry: ResourceRegistry) -> None:
        self._registry = registry

    def get_mapping(
        self,
        *,
        tenant_id: str,
        biz_domain: str,
        target: DataTarget,
        resource_type: str,
        logical_name: str,
    ) -> ResourceMapping | None:
        return self._registry.get(
            tenant_id=tenant_id,
            biz_domain=biz_domain,
            target=target,
            resource_type=resource_type,
            logical_name=logical_name,
        )

    async def health(self) -> dict[str, str]:
        return {"status": "ok", "backend": "in_memory"}
